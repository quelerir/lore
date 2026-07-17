# SQL Tool Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть находки внешнего ревью: денайлист функций в guardrails, судья с причиной, честный бюджет с пределом раундов, pydantic-состояние вместо init, узел sample с примерами строк, гигиена (парсер/qualify/statement_cache/логи), группировка контекста и честность ответа.

**Architecture:** Все изменения — в `backend/toast/` при неизменном входе/выходе графа и сигнатуре `build_sql_graph`. Состояние переезжает на pydantic-модель с дефолтами (узел `init` умирает), топология: `START → sample → generate → execute → judge → summarize`.

**Tech Stack:** Python 3.13+/langgraph/pydantic/sqlglot/asyncpg/pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-sql-tool-review-fixes-design.md`
**Ревью-источник:** `docs/sql-tool-review.md`

## Global Constraints

- Ветка `toast-logic`; демо получает изменения merge'ем в конце (Task 10).
- Toast-БД неприкосновенна; вход/выход графа и сигнатура `build_sql_graph` стабильны; в `toast/` нет импортов Chainlit; smoke-тесты Studio зелёные.
- Команды бэкенда из `backend/`: `uv run pytest tests/ -q`, `uv run ruff check .`.
- Проверенные факты sqlglot: `exp.Anonymous` → имя в `.name` (`query_to_xml`, `pg_sleep`, `dblink`); типизированные `exp.Func` → `sql_name()` (`COUNT`, `X_M_L_TABLE`); сверять по нормализации `name.lower().replace("_", "")`. `tree.transform(...)` не трогает строковые литералы. `invoke` графа с pydantic-схемой возвращает dict.

---

### Task 1: Guardrails — денайлист функций (ревью 2.1)

**Files:**
- Modify: `backend/toast/sql_guardrails.py`
- Test: `backend/tests/test_sql_guardrails.py`

**Interfaces:**
- Produces: `validate_select` отклоняет вызовы опасных функций текстом «Отказ: функция <имя> запрещена.»; внутренние `_FORBIDDEN_FUNC_PREFIXES: tuple[str, ...]`, `_forbidden_func(stmt) -> str | None`.

- [ ] **Step 1: Падающие тесты**

Добавить в `backend/tests/test_sql_guardrails.py`:

```python
@pytest.mark.parametrize("bad", [
    f"SELECT query_to_xml('SELECT * FROM public.users', true, false, '') FROM splitter_toast.{T}",
    f"SELECT query_to_xml_and_xmlschema('SELECT 1', true, false, '') FROM splitter_toast.{T}",
    f"SELECT * FROM splitter_toast.{T}, xmltable('/x' PASSING column_1 COLUMNS a text)",
    f"SELECT * FROM splitter_toast.{T} t, dblink('c', 'SELECT 1') AS d(x int)",
    f"SELECT pg_sleep(10) FROM splitter_toast.{T}",
    f"SELECT pg_read_file('/etc/passwd') FROM splitter_toast.{T}",
    f"SELECT current_setting('server_version') FROM splitter_toast.{T}",
])
def test_dangerous_functions_rejected(bad):
    refusal = validate_select(bad, T)
    assert refusal is not None and "функция" in refusal


def test_benign_functions_allowed():
    sql = (f"SELECT count(*), lower(column_1), coalesce(column_2, '-') "
           f"FROM splitter_toast.{T} GROUP BY column_1, column_2")
    assert validate_select(sql, T) is None
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && uv run pytest tests/test_sql_guardrails.py -q`
Expected: FAIL все 7 параметризованных (сейчас функции не проверяются), `test_benign_functions_allowed` PASS.

- [ ] **Step 3: Реализация**

В `backend/toast/sql_guardrails.py` после `ALLOWED_SCHEMA` добавить:

```python
# Денайлист функций (сравнение по нормализации: lower + без подчёркиваний,
# по префиксу — накрывает семейства вида query_to_xml*/dblink_*/pg_read_*).
# Классы: исполнение SQL-текста (query_to_xml, xmltable, dblink), чтение
# файлов/каталогов сервера, large objects, DoS/управление сессиями, GUC.
_FORBIDDEN_FUNC_PREFIXES = (
    "querytoxml", "xmltable", "dblink", "pgread", "pgls", "pgstatfile",
    "loimport", "loexport", "pgsleep", "pgterminatebackend",
    "pgcancelbackend", "currentsetting", "setconfig",
)


def _forbidden_func(stmt: exp.Expression) -> str | None:
    """Имя первой запрещённой функции в выражении, иначе None."""
    for f in stmt.find_all(exp.Func):
        name = f.name if isinstance(f, exp.Anonymous) else f.sql_name()
        normalized = name.lower().replace("_", "")
        if normalized.startswith(_FORBIDDEN_FUNC_PREFIXES):
            return name
    return None
```

В `validate_select` после проверки `into`/`locks` (до сбора таблиц) добавить:

```python
    if bad_func := _forbidden_func(stmt):
        return f"Отказ: функция {bad_func} запрещена."
```

- [ ] **Step 4: Тесты и линтер**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`
Expected: 0 failed, `All checks passed!`

- [ ] **Step 5: Commit**

```bash
cd backend
git add toast/sql_guardrails.py tests/test_sql_guardrails.py
git commit -m "fix(toast): deny SQL-executing and file-reading functions in guardrails"
```

---

### Task 2: Guardrails — `qualify_table` AST-трансформом (ревью 2.6)

**Files:**
- Modify: `backend/toast/sql_guardrails.py` (функция `qualify_table`, удалить `_BARE`)
- Test: `backend/tests/test_sql_guardrails.py`

**Interfaces:**
- Produces: `qualify_table(sql: str, table: str) -> str` — та же сигнатура; литералы не переписываются; неразбираемый SQL возвращается как есть.

- [ ] **Step 1: Падающий тест**

```python
def test_qualify_does_not_touch_string_literals():
    sql = f"SELECT * FROM {T} WHERE column_1 = 'from {T}'"
    out = qualify_table(sql, T)
    assert f"FROM splitter_toast.{T}" in out
    assert f"'from {T}'" in out  # литерал цел


def test_qualify_unparseable_sql_passthrough():
    assert qualify_table("Извините, не могу", T) == "Извините, не могу"
```

- [ ] **Step 2: Убедиться, что первый падает**

Run: `cd backend && uv run pytest tests/test_sql_guardrails.py -q`
Expected: FAIL `test_qualify_does_not_touch_string_literals` (regex перепишет литерал).

- [ ] **Step 3: Реализация — заменить `qualify_table` и удалить `_BARE`**

```python
def qualify_table(sql: str, table: str) -> str:
    """Дописывает splitter_toast. к голому имени переданной таблицы.

    AST-трансформ, а не regex: подстрока в строковом литерале не
    переписывается. Неразбираемый SQL возвращается как есть — упадёт в
    validate_select с внятным отказом.
    """
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return sql

    def _qualify(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.Table) and not node.db and node.name == table:
            node.set("db", exp.to_identifier(ALLOWED_SCHEMA))
        return node

    return tree.transform(_qualify).sql(dialect="postgres")
```

Удалить определение `_BARE` (больше не используется).

- [ ] **Step 4: Тесты и линтер**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`
Expected: 0 failed (существующий `test_bare_table_name_qualified` сравнивает строки — sqlglot рендерит эквивалентный SQL; если ассерты на точное совпадение упадут из-за форматирования, заменить в них `==` на проверку `"FROM splitter_toast." in`).

- [ ] **Step 5: Commit**

```bash
cd backend
git add toast/sql_guardrails.py tests/test_sql_guardrails.py
git commit -m "fix(toast): qualify bare table via sqlglot transform, not regex"
```

---

### Task 3: Executor — `statement_cache_size=0` (ревью 2.7)

**Files:**
- Modify: `backend/toast/executor.py:53-55`
- Test: `backend/tests/test_executor_pool.py`

- [ ] **Step 1: Падающий тест**

В `test_connect_has_no_startup_params` добавить ассерт:

```python
    # prepared statements ломаются за transaction-pooling пулером
    assert captured.get("statement_cache_size") == 0
```

- [ ] **Step 2: Убедиться, что падает**

Run: `cd backend && uv run pytest tests/test_executor_pool.py -q`
Expected: FAIL (ключа нет).

- [ ] **Step 3: Реализация**

В `run_select`:

```python
            conn = await asyncpg.connect(
                self._dsn,
                command_timeout=STATEMENT_TIMEOUT_MS / 1000,
                statement_cache_size=0,  # prepared statements vs PgBouncer
            )
```

- [ ] **Step 4: Тесты, линтер, commit**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`

```bash
cd backend
git add toast/executor.py tests/test_executor_pool.py
git commit -m "fix(toast): disable asyncpg statement cache for transaction pooler"
```

---

### Task 4: Pydantic-состояние, удаление `init`

**Files:**
- Modify: `backend/toast/sql_graph.py` (схемы состояния, все узлы, топология)
- Test: `backend/tests/test_sql_graph.py`

**Interfaces:**
- Produces: `SqlToolInput(BaseModel)` (5 полей входа), `SqlToolState(SqlToolInput)` с дефолтами: `candidates: list[str]=[]`, `round: int=0`, `executed_count: int=0`, `attempts: list[Attempt]=[]`, `verdict: str=""`, `answer: str=""`, `status: str=""`. Узлы читают состояние атрибутами (`state.question`), возвращают dict-апдейты. `graph.ainvoke` возвращает dict — контракт `_project` в `sql_tool.py` не меняется.

- [ ] **Step 1: Заменить схемы состояния**

В `backend/toast/sql_graph.py` заменить классы `SqlToolState`/`SqlToolInput` (TypedDict) на:

```python
class SqlToolInput(BaseModel):
    """Входные поля инструмента (форма ввода в Studio)."""

    question: str
    chunk_id: str
    table: str
    desc_vector: str
    desc_full: str


class SqlToolState(SqlToolInput):
    """Состояние графа: вход + аккумуляторы с дефолтами.

    Дефолты полей заменяют бывший узел init: langgraph применяет их сам,
    «забытая инициализация» перестала существовать как класс ошибки
    (инцидент KeyError: 'candidates' в TypedDict-версии).
    """

    candidates: list[str] = Field(default_factory=list)
    round: int = 0
    executed_count: int = 0
    attempts: list[Attempt] = Field(default_factory=list)
    verdict: str = ""
    answer: str = ""
    status: str = ""
```

Импорт: `from pydantic import BaseModel, Field`. `Attempt` (TypedDict) остаётся как есть.

- [ ] **Step 2: Узлы на атрибутный доступ, `init` удалить**

В `build_sql_graph`:
- удалить узел `init` целиком;
- `generate`: `state["executed_count"]` → `state.executed_count`, `state["attempts"]` → `state.attempts`, `state['question']` → `state.question` (и все остальные поля промпта), `state["round"] + 1` → `state.round + 1`;
- `execute`: `state["table"]` → `state.table`, `state["candidates"]` → `state.candidates`, `state["attempts"]` → `state.attempts`, `state.executed_count`;
- `judge`/`summarize`: `state["attempts"]` → `state.attempts`, `state['question']` → `state.question`, `state["attempts"]` в ветках summarize → `state.attempts`;
- `after_generate`: `state["candidates"]` → `state.candidates`;
- `after_execute`: `state["executed_count"]` → `state.executed_count`;
- `after_judge`: `state.get("verdict")` → `state.verdict`;
- сигнатуры узлов: `async def generate(state: SqlToolState) -> dict:` (возврат — dict-апдейт);
- топология: удалить `g.add_node("init", ...)`, `g.add_edge(START, "init")`, `g.add_edge("init", "generate")`; добавить `g.add_edge(START, "generate")`;
- докстринг модуля: топология `START → generate → …`, удалить описание init, упомянуть pydantic-дефолты.

- [ ] **Step 3: Правка тестов**

В `backend/tests/test_sql_graph.py` заменить `test_state_has_no_columns_field`:

```python
def test_state_has_defaults_instead_of_init():
    from toast.sql_graph import SqlToolState

    assert "columns" not in SqlToolState.model_fields
    state = SqlToolState(question="q", chunk_id="c", table="t",
                         desc_vector="v", desc_full="f")
    assert state.attempts == [] and state.executed_count == 0 and state.round == 0
```

- [ ] **Step 4: Тесты и линтер**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .`
Expected: 0 failed. Затем регресс Studio: `cd ../studio && uv run pytest -q` → `2 passed`.

- [ ] **Step 5: Commit**

```bash
cd backend
git add toast/sql_graph.py tests/test_sql_graph.py
git commit -m "refactor(toast): pydantic graph state with defaults, drop init node"
```

---

### Task 5: Узел `sample` — примеры строк в промпте (ревью 1.1)

**Files:**
- Modify: `backend/toast/sql_graph.py`
- Test: `backend/tests/test_sql_graph.py`

**Interfaces:**
- Consumes: `SqlToolState` из Task 4; `executor.run_select` (может вернуть str-отказ или бросить исключение).
- Produces: поле `sample_rows: list[dict]` в состоянии; константы `SAMPLE_LIMIT = 5`, `SAMPLE_CONTEXT_CHARS = 2_000`; топология `START → sample → generate`. Первый `run_select` каждого прогона — сэмпл (важно для FakeExecutor).

- [ ] **Step 1: Обновить FakeExecutor-сценарии и написать новые тесты**

В `backend/tests/test_sql_graph.py`:

1. Добавить хелпер сэмпла после `_rows`:

```python
def _sample():
    # результат сэмпл-запроса (первый run_select каждого прогона)
    return _rows(1)
```

2. Во ВСЕХ существующих тестах, создающих `FakeExecutor(results=[...])`,
   добавить `_sample()` ПЕРВЫМ элементом results и увеличить ожидаемые
   `len(exe.calls)` на 1. Пример (`test_round1_sufficient_ok`):

```python
    exe = FakeExecutor(results=[_sample(), _rows(1), _rows(1)])
    ...
    assert len(exe.calls) == 3  # сэмпл + оба кандидата раунда
```

Аналогично: `test_retry_then_sufficient` (results `[_sample(), _rows(1), _rows(1)]`, calls 3), `test_budget_exhausted_no_data` (`[_sample(), _rows(0), _rows(0), _rows(0)]`, calls 4), `test_duplicate_candidate_not_reexecuted_but_counted` (`[_sample(), _rows(0)]`, calls 2), `test_all_sql_errors_status_error` (`[_sample(), "Ошибка SQL: a", "Ошибка SQL: b", "Ошибка SQL: c"]`), `test_no_candidates_terminates_with_error` (`[_sample()]`, `exe.calls == [f"SELECT * FROM {LEGAL} LIMIT 5"]`), `test_insufficient_verdict_means_need_more` (`[_sample(), _rows(1), _rows(1)]`, calls 3), `test_structured_output_path_used_when_supported` (`[_sample(), _rows(1)]`, calls: сэмпл + кандидат), `test_executor_exception_becomes_failed_attempt` — BoomExecutor кидает на ЛЮБОЙ вызов, включая сэмпл: тест остаётся валиден (сбой сэмпла не фатален), ответ по-прежнему error.

3. Новые тесты:

```python
def test_sample_failure_is_not_fatal():
    # Отказ/ошибка сэмпла не роняет граф и не мешает ответу.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Ответ."),
    ])
    exe = FakeExecutor(results=["Ошибка SQL: сеть", _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"


def test_sample_not_counted_in_budget():
    # max_queries=1: сэмпл вне бюджета, кандидат всё ещё выполняется.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content="Ответ."),  # summarize (бюджет исчерпан, судьи нет)
    ])
    exe = FakeExecutor(results=[_sample(), _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=1)
    assert out["status"] == "ok"
    assert len(exe.calls) == 2
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && uv run pytest tests/test_sql_graph.py -q`
Expected: массовые FAIL (лишний заскриптованный результат не потреблён / calls не сходятся).

- [ ] **Step 3: Реализация**

В `backend/toast/sql_graph.py`:

1. Константы после `JUDGE_CONTEXT_CHARS`:

```python
SAMPLE_LIMIT = 5  # строк-примеров для промпта generate
SAMPLE_CONTEXT_CHARS = 2_000  # кап сериализованных примеров в промпте
```

2. Поле состояния в `SqlToolState`:

```python
    sample_rows: list[dict] = Field(default_factory=list)
```

3. Узел в `build_sql_graph` (перед `generate`):

```python
    async def sample(state: SqlToolState) -> dict:
        """Детерминированные примеры строк — ВНЕ бюджета.

        Модель видит реальные имена колонок и формат значений до генерации;
        рассинхрон desc_full со схемой всплывает здесь, а не тратой бюджета.
        Сбой не фатален: пустые примеры + warning, граф продолжает.
        """
        sql = f"SELECT * FROM {state.table} LIMIT {SAMPLE_LIMIT}"
        try:
            res = await executor.run_select(sql, state.table)
        except Exception:
            logging.getLogger(__name__).warning(
                "sample query failed for %s", state.table, exc_info=True)
            return {"sample_rows": []}
        if isinstance(res, str):
            logging.getLogger(__name__).warning("sample refused: %s", res)
            return {"sample_rows": []}
        return {"sample_rows": res["rows"]}
```

4. В `generate` после блока `if errors:`/`if empty:` добавить:

```python
        if state.sample_rows:
            sample_json = json.dumps(
                state.sample_rows, ensure_ascii=False, default=str
            )[:SAMPLE_CONTEXT_CHARS]
            prompt += (
                f"\n\nПримеры строк таблицы (до {SAMPLE_LIMIT}, реальные "
                f"имена колонок и формат значений):\n{sample_json}"
            )
```

5. Топология: `g.add_node("sample", sample)`, `g.add_edge(START, "sample")`, `g.add_edge("sample", "generate")` (вместо `START → generate`). Докстринг модуля обновить: `START → sample → generate → …`, описание узла sample.

- [ ] **Step 4: Тесты, линтер, Studio, commit**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .` → 0 failed.
Run: `cd ../studio && uv run pytest -q` → `2 passed`.

```bash
cd backend
git add toast/sql_graph.py tests/test_sql_graph.py
git commit -m "feat(toast): sample node feeds real rows into SQL generation prompt"
```

---

### Task 6: Бюджет = выполненные SQL; предел раундов (ревью 2.4)

**Files:**
- Modify: `backend/toast/sql_graph.py` (узел `execute`, `after_execute`)
- Test: `backend/tests/test_sql_graph.py`

**Interfaces:**
- Produces: `executed_count` растёт только на SQL, дошедшие до БД (отказ guardrails с префиксом «Отказ:» не считается); `after_execute` уводит в summarize при `executed_count >= max_queries` ИЛИ `round >= max_queries`.

- [ ] **Step 1: Падающие тесты**

```python
def test_guardrails_refusal_does_not_consume_budget():
    # Раунд 1: два кандидата — отказ валидатора + удачный SELECT. Отказ не
    # списывается → executed=1 < 2 → зовётся СУДЬЯ. При старой семантике
    # executed=2 исчерпал бы бюджет, judge был бы пропущен, и summarize
    # съел бы заскриптованный "SUFFICIENT" как ответ — ассерт на answer
    # ловит разницу.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["DROP TABLE x", "SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Ответ."),
    ])
    exe = FakeExecutor(results=[_sample(), "Отказ: разрешён только SELECT.",
                                _rows(1)])
    out = _run(model, exe, candidates=2, max_queries=2)
    assert out["status"] == "ok"
    assert out["answer"] == "Ответ."


def test_round_cap_stops_refusal_only_batches():
    # Модель упорно генерит запрещённое: бюджет не тратится, но предел
    # раундов (== max_queries) останавливает цикл со status=error.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["DROP TABLE x"]'),
        AIMessage(content='["DROP TABLE y"]'),
    ])
    exe = FakeExecutor(results=[_sample(), "Отказ: разрешён только SELECT.",
                                "Отказ: разрешён только SELECT."])
    out = _run(model, exe, candidates=1, max_queries=2)
    assert out["status"] == "error"
    assert "Отказ" in out["answer"]
```

Обновить `test_duplicate_candidate_not_reexecuted_but_counted` → дубликаты тоже больше не двигают бюджет, цикл стопится пределом раундов; переименовать и переписать:

```python
def test_duplicate_candidates_stopped_by_round_cap():
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),  # дубликат
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),  # дубликат
    ])
    exe = FakeExecutor(results=[_sample(), _rows(0)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "no_data"
    assert len(exe.calls) == 2  # сэмпл + один реальный SELECT
```

(Судья на пустых строках не зовётся — три ответа generate в скрипте.)

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && uv run pytest tests/test_sql_graph.py -q`
Expected: FAIL новые тесты (отказ ест бюджет; раунды не ограничены).

- [ ] **Step 3: Реализация**

Узел `execute` — замена возврата:

```python
        new = [_attempt(sql, res) for sql, res in zip(unique, results)]
        # Бюджет — только SQL, дошедшие до БД: отказ guardrails существует,
        # чтобы модель ПЕРЕПИСАЛА запрос, и не должен съедать попытку.
        executed = sum(
            1 for a in new
            if a["ok"] or not (a["error"] or "").startswith("Отказ:")
        )
        return {
            "attempts": state.attempts + new,
            "executed_count": state.executed_count + executed,
        }
```

Комментарий про дубликаты в докстринге execute заменить: дубликаты не выполняются и бюджет не двигают — завершаемость держит предел раундов.

`after_execute`:

```python
    def after_execute(state: SqlToolState) -> str:
        """Бюджет или предел раундов исчерпан → summarize; иначе judge.

        Предел раундов — страховка завершаемости: батчи из дубликатов или
        отказов guardrails бюджет не двигают.
        """
        if state.executed_count >= max_queries or state.round >= max_queries:
            return "summarize"
        return "judge"
```

Докстринг модуля («Управление циклом») обновить соответственно.

- [ ] **Step 4: Тесты, линтер, commit**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .` → 0 failed.

```bash
cd backend
git add toast/sql_graph.py tests/test_sql_graph.py
git commit -m "fix(toast): budget counts executed SQL only; round cap guards termination"
```

---

### Task 7: Судья с причиной + фидбек в generate (ревью 2.2, 2.8)

**Files:**
- Modify: `backend/toast/sql_graph.py`
- Test: `backend/tests/test_sql_graph.py`

**Interfaces:**
- Produces: `JudgeVerdict(BaseModel)` с полями `sufficient: bool`, `reason: str = ""`; хелпер `_judge_verdict(model, messages) -> JudgeVerdict`; `_log_fallback(node: str, exc: Exception) -> None` (используется и в `_generate_candidates`); поле состояния `judge_reason: str = ""`; промпт generate получает секцию с причиной.

- [ ] **Step 1: Падающие тесты**

```python
def test_judge_reason_feeds_next_generate_prompt():
    from fakes import StructuredScriptedChatModel
    from toast.sql_graph import JudgeVerdict, SqlCandidates

    captured: list[str] = []

    class CapturingModel(StructuredScriptedChatModel):
        def with_structured_output(self, schema, **kwargs):
            model = self

            class _S:
                async def ainvoke(self, messages, config=None):
                    captured.append("\n".join(str(m.content) for m in messages))
                    return model.responses.pop(0)

            return _S()

    model = CapturingModel(responses=[
        SqlCandidates(candidates=["SELECT column_1 FROM %s" % LEGAL]),
        JudgeVerdict(sufficient=False, reason="строки не про юристов"),
        SqlCandidates(candidates=["SELECT column_2 FROM %s" % LEGAL]),
        JudgeVerdict(sufficient=True, reason="ок"),
        AIMessage(content="Ответ."),
    ])
    exe = FakeExecutor(results=[_sample(), _rows(1), _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"
    # причина судьи попала в промпт ВТОРОГО generate (3-й structured-вызов
    # в captured: generate, judge, generate)
    assert "строки не про юристов" in captured[2]
```

(`summarize` идёт нестрктурированным `ainvoke` — последний AIMessage.)

- [ ] **Step 2: Убедиться, что падает**

Run: `cd backend && uv run pytest tests/test_sql_graph.py::test_judge_reason_feeds_next_generate_prompt -q`
Expected: FAIL — `ImportError: cannot import name 'JudgeVerdict'`.

- [ ] **Step 3: Реализация**

1. Модель и хелперы (рядом с `SqlCandidates`):

```python
class JudgeVerdict(BaseModel):
    """Вердикт судьи: достаточно ли строк и почему нет (structured output)."""

    sufficient: bool
    reason: str = ""


def _log_fallback(node: str, exc: Exception) -> None:
    """Лог причины фолбэка structured output → текстовый путь.

    NotImplementedError — ожидаемо (фейки, модели без tools) → debug;
    остальное (сеть, 4xx) — warning: транзиентные ошибки не должны молча
    удваивать латентность.
    """
    level = logging.DEBUG if isinstance(exc, NotImplementedError) else logging.WARNING
    logging.getLogger(__name__).log(
        level, "%s: structured output недоступен (%r), текстовый фолбэк",
        node, exc,
    )


async def _judge_verdict(model: BaseChatModel, messages: list) -> JudgeVerdict:
    """Вердикт через structured output; фолбэк — текстовый парсинг без причины."""
    try:
        structured = model.with_structured_output(
            JudgeVerdict, method="function_calling"
        )
        return await structured.ainvoke(messages, config={"tags": ["internal"]})
    except Exception as e:
        _log_fallback("judge", e)
        reply = await model.ainvoke(messages, config={"tags": ["internal"]})
        text = str(reply.content).lower()
        ok = bool(_SUFFICIENT_RE.search(text)) and "need_more" not in text
        return JudgeVerdict(sufficient=ok, reason="")
```

2. В `_generate_candidates` заменить голый `except Exception:` на:

```python
    except Exception as e:
        _log_fallback("generate", e)
```

3. Поле состояния: `judge_reason: str = ""` в `SqlToolState`.

4. Узел `judge` — заменить блок вызова модели и возврат:

```python
        verdict = await _judge_verdict(
            model,
            [
                SystemMessage(JUDGE_SYS),
                HumanMessage(
                    f"Вопрос: {state.question}\n"
                    + _rows_context(state.attempts, rows)
                ),
            ],
        )
        return {
            "verdict": "sufficient" if verdict.sufficient else "need_more",
            "judge_reason": verdict.reason,
        }
```

`JUDGE_SYS` заменить на:

```python
JUDGE_SYS = (
    "Ты оцениваешь, достаточно ли полученных строк, чтобы ответить на "
    "вопрос. Верни sufficient=true/false и короткую причину reason — "
    "почему строк недостаточно (она попадёт генератору SQL)."
)
```

5. В `generate` после секции `if empty:` добавить:

```python
        if state.judge_reason:
            prompt += (
                "\n\nПрошлый результат отклонён судьёй: "
                f"{state.judge_reason} — построй запрос иначе."
            )
```

- [ ] **Step 4: Тесты, линтер, commit**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .` → 0 failed (старые Scripted-тесты идут текстовым фолбэком: `NotImplementedError` фейка).

```bash
cd backend
git add toast/sql_graph.py tests/test_sql_graph.py
git commit -m "feat(toast): judge returns reason, fed back into next SQL generation"
```

---

### Task 8: Фолбэк-парсер через sqlglot (ревью 2.5)

**Files:**
- Modify: `backend/toast/sql_graph.py` (функция `parse_sql_candidates`, импорты)
- Test: `backend/tests/test_sql_graph.py`

- [ ] **Step 1: Падающий тест**

```python
def test_parse_candidates_multiline_sql_fallback():
    from toast.sql_graph import parse_sql_candidates

    text = ("SELECT column_1,\n       column_2\n"
            "FROM splitter_toast.%s\nWHERE column_2 IS NOT NULL" % LEGAL)
    out = parse_sql_candidates(text, 2)
    assert len(out) == 1
    assert "column_2" in out[0] and "WHERE" in out[0]
```

- [ ] **Step 2: Убедиться, что падает**

Run: `cd backend && uv run pytest tests/test_sql_graph.py::test_parse_candidates_multiline_sql_fallback -q`
Expected: FAIL — вернётся обрубок `['SELECT column_1,']`.

- [ ] **Step 3: Реализация**

Импорты в `sql_graph.py`: `import sqlglot` и `from sqlglot import exp as sql_exp`.
Заменить хвост `parse_sql_candidates` (после `except json.JSONDecodeError: pass`):

```python
    # Фолбэк 1: текст целиком — SQL (в т.ч. многострочный / несколько команд).
    try:
        statements = [s for s in sqlglot.parse(cleaned, read="postgres") if s]
        sqls = [
            s.sql(dialect="postgres")
            for s in statements
            if isinstance(s, (sql_exp.Select, sql_exp.SetOperation))
        ]
        if sqls:
            return sqls[:limit]
    except sqlglot.errors.ParseError:
        pass
    # Фолбэк 2: прозаический ответ со вкраплениями однострочных SELECT.
    lines = [ln.strip() for ln in cleaned.splitlines()
             if ln.strip().lower().startswith("select")]
    return lines[:limit] or ([cleaned] if cleaned.lower().startswith("select") else [])
```

Докстринг функции дополнить описанием фолбэка-1.

- [ ] **Step 4: Тесты, линтер, commit**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .` → 0 failed.

```bash
cd backend
git add toast/sql_graph.py tests/test_sql_graph.py
git commit -m "fix(toast): sqlglot-based text fallback keeps multiline SQL intact"
```

---

### Task 9: Контекст по попыткам + честность summarize (ревью 1.3-lite, 2.3-lite)

**Files:**
- Modify: `backend/toast/sql_graph.py` (`_rows_context`, `SUMMARIZE_SYS`, вызовы в judge/summarize)
- Test: `backend/tests/test_sql_graph.py`

**Interfaces:**
- Produces: `_rows_context(attempts: list[Attempt]) -> str` — новая сигнатура (rows выводятся из attempts); группы «Запрос: <sql> / Строки: [...]»; суммарные капы прежние (`JUDGE_ROWS_CAP`, `JUDGE_CONTEXT_CHARS`).

- [ ] **Step 1: Переписать тест капов + новый тест группировки**

Заменить `test_rows_context_caps_by_size`:

```python
def _ok_attempt(sql, rows):
    return {"sql": sql, "ok": True, "error": None, "rows": rows,
            "row_count": len(rows), "truncated": False}


def test_rows_context_groups_by_attempt():
    from toast.sql_graph import _rows_context

    ctx = _rows_context([
        _ok_attempt("SELECT a", [{"a": 1}]),
        _attempt(sql="SELECT bad", ok=False, error="Ошибка SQL: x"),
        _ok_attempt("SELECT b", [{"b": 2}]),
    ])
    assert "Запрос: SELECT a" in ctx and "Запрос: SELECT b" in ctx
    assert "SELECT bad" not in ctx  # неуспешные попытки не в контексте
    assert "Показано строк: 2 из 2" in ctx


def test_rows_context_caps_by_size():
    from toast.sql_graph import JUDGE_CONTEXT_CHARS, _rows_context

    big = _ok_attempt("SELECT big", [{"column_1": "x" * JUDGE_CONTEXT_CHARS}])
    small = _ok_attempt("SELECT small", [{"column_1": "y"}])
    ctx = _rows_context([big, small])
    assert "Показано строк: 1 из 2" in ctx
    assert '"y"' not in ctx

    ctx_one = _rows_context([big])
    assert "Показано строк: 1 из 1" in ctx_one
```

`_attempt`-хелпер в тестах графа отсутствует — используется из `test_sql_demo`? Нет: добавить локально рядом с `_ok_attempt`:

```python
def _attempt(sql="SELECT 1", ok=True, error=None, rows=None, row_count=0):
    rows = rows if rows is not None else []
    return {"sql": sql, "ok": ok, "error": error, "rows": rows,
            "row_count": row_count, "truncated": False}
```

- [ ] **Step 2: Убедиться, что падают**

Run: `cd backend && uv run pytest tests/test_sql_graph.py -q`
Expected: FAIL (сигнатура и формат старые).

- [ ] **Step 3: Реализация**

Заменить `_rows_context`:

```python
def _rows_context(attempts: list[Attempt]) -> str:
    """Строки успешных попыток, сгруппированные по их SQL.

    Судья и суммаризатор видят, какой запрос что вернул, — плохой первый
    кандидат не вытесняет из контекста хороший второй безымянной смесью.
    Суммарные капы: JUDGE_ROWS_CAP строк и ~JUDGE_CONTEXT_CHARS символов;
    хотя бы одна строка отдаётся всегда.
    """
    sections: list[str] = []
    total = sum(a["row_count"] for a in attempts if a["ok"])
    shown = 0
    size = 0
    for a in attempts:
        if not a["ok"] or not a["rows"]:
            continue
        rows_out: list[dict] = []
        for row in a["rows"]:
            if shown >= JUDGE_ROWS_CAP:
                break
            piece = json.dumps(row, ensure_ascii=False, default=str)
            if shown and size + len(piece) > JUDGE_CONTEXT_CHARS:
                break
            rows_out.append(row)
            shown += 1
            size += len(piece)
        if rows_out:
            sections.append(
                f"Запрос: {a['sql']}\nСтроки: "
                + json.dumps(rows_out, ensure_ascii=False, default=str)
            )
    note = f"Показано строк: {shown} из {total}"
    if any(a["truncated"] for a in attempts):
        note += " (результат SQL дополнительно усечён лимитом исполнителя)"
    return note + ".\n" + "\n\n".join(sections)
```

Вызовы в `judge` и `summarize`: `_rows_context(state.attempts, rows)` → `_rows_context(state.attempts)`.

`SUMMARIZE_SYS` заменить:

```python
SUMMARIZE_SYS = (
    "Ответь на вопрос пользователя СТРОГО по предоставленным строкам таблицы. "
    "Не выдумывай. Если данных недостаточно — так и скажи. Если показаны не "
    "все строки выборки — явно скажи, что ответ построен по неполной выборке. "
    "Кратко, по-русски."
)
```

- [ ] **Step 4: Тесты, линтер, commit**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .` → 0 failed.

```bash
cd backend
git add toast/sql_graph.py tests/test_sql_graph.py
git commit -m "feat(toast): per-attempt rows context; summarizer discloses truncation"
```

---

### Task 10: Документация, review-файл, финальная верификация, merge в demo

**Files:**
- Modify: `docs/sql-tool.md`
- Add: `docs/sql-tool-review.md` (untracked → закоммитить)

- [ ] **Step 1: Правки `docs/sql-tool.md`**

1. Раздел 2 «Жёсткие ограничения», пункт 3 — дополнить последним предложением: «Также обязателен `statement_cache_size=0` у asyncpg: prepared statements за таким пулером спорадически ломаются.»
2. Раздел 4, топология — заменить схему на:

```
START → sample → generate → execute(∥) → judge → summarize → END

условные переходы:
  generate → summarize   если модель не дала ни одного кандидата
  execute  → summarize   если бюджет ИЛИ предел раундов исчерпан (минуя судью)
  judge    → generate    если строк недостаточно (ещё раунд)
```

3. Раздел 5: подраздел «init» заменить подразделом «Состояние и sample»:

```markdown
### Состояние — pydantic с дефолтами (узла init больше нет)

Состояние графа — pydantic-модель: аккумуляторы (`attempts`,
`executed_count`, `round`, …) получают дефолты на уровне схемы, langgraph
применяет их сам. Бывший узел `init` существовал только потому, что у
TypedDict-состояния дефолтов нет (инцидент `KeyError: 'candidates'`);
с pydantic этот класс ошибок закрыт схемой.

### sample — примеры строк (вне бюджета)

Первый узел: детерминированный `SELECT * FROM t LIMIT 5` через тот же
read-only исполнитель. Модель видит реальные имена колонок и формат
значений ДО генерации — стандартная практика text-to-SQL; заодно
рассинхрон `desc_full` со схемой всплывает здесь, а не тратой бюджета.
Сбой сэмпла не фатален (пустые примеры + warning). Бюджет не списывается.
```

4. Раздел 5, generate — в перечень фидбека добавить: «и причина отклонения от судьи (см. judge)».
5. Раздел 5, judge — заменить описание парсинга на: судья возвращает structured output `{sufficient, reason}` (фолбэк — текстовый парсинг с границей слова, причина пустая); `reason` попадает в промпт следующего generate — retry-цикл замкнут.
6. Раздел 6 — заменить формулировку завершаемости: бюджет списывается ТОЛЬКО за SQL, дошедшие до БД (отказы guardrails и дубликаты не считаются — их фидбек существует для переписывания); завершаемость держит явный предел раундов (`round >= max_queries`).
7. Раздел 7, слой 1 — добавить пункт: «вызовы функций проверяются по денайлисту (`query_to_xml*`, `xmltable`, `dblink*`, `pg_read_*`, `pg_sleep*`, `set_config`, …) — штатные функции Postgres, исполняющие SQL-текст или читающие файлы сервера, отклоняются».
8. Раздел 7 — заменить фразу «Слои независимы — пробитие одного не открывает данные» на: «Слой 2 защищает только от записи: конфиденциальность чужих схем при чтении держится на слое 1 — поэтому в нём и таблицы, и функции».
9. Раздел 7, слой 3 / раздел про исполнителя — добавить `statement_cache_size=0`.
10. Раздел 3 — `rows_used` описать честно: «строк получено успешными попытками (не число строк, использованных в ответе)».
11. Раздел 12 — пункт про «судья видит 30 строк» дополнить: «кап действует и на summarize: ответ строится по показанной выборке, и суммаризатор обязан явно сообщать о неполноте».

- [ ] **Step 2: Закоммитить ревью-файл и доку**

```bash
git add docs/sql-tool.md docs/sql-tool-review.md
git commit -m "docs: update SQL tool reference for review fixes; commit review source"
```

- [ ] **Step 3: Финальная верификация**

Run: `cd backend && uv run pytest tests/ -q && uv run ruff check .` → 0 failed.
Run: `cd ../studio && uv run pytest -q` → `2 passed`.
Run: `cd .. && git push origin toast-logic`

- [ ] **Step 4: Merge в демо-ветку и прогон её тестов**

```bash
git checkout demo/sql-chat
git merge --no-edit toast-logic
cd backend && uv run pytest tests/ -q   # 0 failed (в т.ч. test_sql_demo)
cd .. && git push origin demo/sql-chat
git checkout toast-logic
```

Примечание: `sql_demo.node_step_id(handler, "execute")` работает с узлами по имени — узел `execute` не переименовывался; новый узел `sample` просто появится в трейсе.

---

## Final Verification

- [ ] `cd backend && uv run pytest tests/ -q && uv run ruff check .` — 0 failed
- [ ] `cd studio && uv run pytest -q` — 2 passed
- [ ] Обе ветки запушены; демо-ветка смержена
- [ ] `docs/sql-tool.md` соответствует новому поведению (топология, бюджет, слои)
