# SQL-инструмент: убрать зависимость `scope` от БД — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить узел `scope` (тянул реальные колонки из БД) на DB-less узел `init`, полагаясь на рукописное `desc_full` как источник имён+смысла колонок.

**Architecture:** Один узел графа перестаёт ходить в БД: `scope` → `init` (только инициализация аккумуляторов). Имена колонок модель берёт из `desc_full`, который уже в промпте `generate`. Рассинхрон схемы ловится существующим бэкстопом — Postgres-ошибкой на выполнении, уходящей в retry-цикл. Все прочие узлы, маршрутизация и retry не меняются.

**Tech Stack:** Python 3.13, langgraph, langchain-core, pytest, uv.

**Спека:** `docs/superpowers/specs/2026-07-17-sql-tool-drop-scope-design.md`

## Global Constraints

- Публичная сигнатура `build_sql_graph(model, executor, max_queries, candidates_per_round)` не меняется (её зовёт `studio/graph.py`).
- Вход графа `SqlToolInput` (5 полей: `question, chunk_id, table, desc_vector, desc_full`) не меняется.
- Тесты гонять из каталога `backend/`: `uv run pytest`.
- Read-only исполнитель и его тесты не затрагиваются.

---

### Task 1: Заменить `scope` на DB-less `init`, убрать `columns`, поправить промпт

**Files:**
- Modify: `backend/toast/sql_graph.py` (FIXED_SCHEMA `47-53`; `SqlToolState.columns` `88`; `scope` `156-159`; `generate` промпт `173`; сборка графа `258-270`; docstring графа `7-13, 16`)
- Test: `backend/tests/test_sql_graph.py` (добавить 2 теста)

**Interfaces:**
- Consumes: `ScriptedChatModel` (из `tests/fakes.py`), `FakeExecutor`, хелперы `_rows`, `_inp`, `_run` (уже есть в `test_sql_graph.py`).
- Produces: узел графа `init` (внутренний, имя не экспортируется); `SqlToolState` без поля `columns`. Публичный API (`build_sql_graph`, `SqlToolInput`) без изменений.

- [ ] **Step 1: Написать падающий тест — `init` не ходит в БД**

В `backend/tests/test_sql_graph.py` добавить в конец файла:

```python
def test_init_does_not_query_columns_from_db():
    # init — DB-less: имена колонок берутся из desc_full, а не из БД.
    class NoFetchExecutor(FakeExecutor):
        async def fetch_columns(self, table):
            raise AssertionError("init не должен запрашивать колонки из БД")

    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="ok"),
    ])
    exe = NoFetchExecutor(["column_1"], results=[_rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"
    assert len(exe.calls) == 1


def test_state_has_no_columns_field():
    from toast.sql_graph import SqlToolState

    assert "columns" not in SqlToolState.__annotations__
```

- [ ] **Step 2: Запустить тесты — убедиться, что падают**

Run: `cd backend && uv run pytest tests/test_sql_graph.py::test_init_does_not_query_columns_from_db tests/test_sql_graph.py::test_state_has_no_columns_field -v`
Expected: FAIL — первый падает с `AssertionError: init не должен запрашивать колонки из БД` (текущий `scope` зовёт `fetch_columns`); второй падает, т.к. `columns` пока в `SqlToolState`.

- [ ] **Step 3: Заменить `scope` на `init` в `sql_graph.py`**

Заменить функцию `scope` (строки ~156-159):

```python
    async def scope(state: SqlToolState) -> SqlToolState:
        """Детерминированный старт: реальные колонки + инициализация счётчиков."""
        columns = await executor.fetch_columns(state["table"])
        return {"columns": columns, "attempts": [], "executed_count": 0, "round": 0}
```

на:

```python
    async def init(state: SqlToolState) -> SqlToolState:
        """Детерминированный старт: инициализация аккумуляторов (без БД).

        Имена и смысл колонок приходят из desc_full (рукописное описание),
        поэтому реальные колонки из БД тянуть не нужно.
        """
        return {"attempts": [], "executed_count": 0, "round": 0}
```

- [ ] **Step 4: Убрать строку с колонками из промпта `generate`**

В функции `generate` удалить строку (было ~173):

```python
            f"Реальные колонки: {', '.join(state['columns'])}\n"
```

Итоговый `prompt` в `generate`:

```python
        prompt = (
            f"Вопрос: {state['question']}\n"
            f"Таблица: {state['table']}\n"
            f"Описание (кратко): {state['desc_vector']}\n"
            f"Описание (полно): {state['desc_full']}\n"
            f"Нужно вернуть до {n} разных SELECT."
        )
```

- [ ] **Step 5: Поправить хвост `FIXED_SCHEMA`**

Заменить последнюю фразу константы `FIXED_SCHEMA` (строки ~47-53):

```python
    "(из заголовков). Используй ТОЛЬКО реальные имена колонок из списка ниже."
```

на:

```python
    "(из заголовков). Используй физические имена колонок строго как в "
    "описании таблицы."
```

- [ ] **Step 6: Убрать поле `columns` из `SqlToolState`**

В классе `SqlToolState` удалить строку (было ~88):

```python
    columns: list[str]
```

И в docstring класса заменить `Заполняется узлами: columns (scope), candidates (generate),` на `Заполняется узлами: candidates (generate),`.

- [ ] **Step 7: Обновить сборку графа под `init`**

В `build_sql_graph` заменить три строки:

```python
    g.add_node("scope", scope)
```
→
```python
    g.add_node("init", init)
```

```python
    g.add_edge(START, "scope")
```
→
```python
    g.add_edge(START, "init")
```

```python
    g.add_edge("scope", "generate")
```
→
```python
    g.add_edge("init", "generate")
```

- [ ] **Step 8: Обновить docstring модуля графа**

В шапке модуля заменить диаграмму топологии (строки ~9-13): `START → scope → generate` на `START → init → generate`. В разделе «Ответственность узлов» заменить блок про `scope`:

```
  • scope     — детерминированный: тянет реальные имена колонок таблицы
                (обязательно: физические имена часто переименованы и не
                совпадают с человеческими заголовками из описания).
```

на:

```
  • init      — детерминированный: инициализирует аккумуляторы (без БД).
                Имена и смысл колонок берутся из desc_full (рукописное
                описание), поэтому реальные колонки из БД не тянутся.
```

- [ ] **Step 9: Запустить новые тесты — убедиться, что проходят**

Run: `cd backend && uv run pytest tests/test_sql_graph.py::test_init_does_not_query_columns_from_db tests/test_sql_graph.py::test_state_has_no_columns_field -v`
Expected: PASS (оба).

- [ ] **Step 10: Прогнать весь набор тестов графа — регрессия**

Run: `cd backend && uv run pytest tests/test_sql_graph.py -v`
Expected: PASS — все 8 тестов (6 прежних поведенческих + 2 новых). Прежние тесты зелёные подтверждают, что повисшей ссылки на `state['columns']` не осталось (иначе был бы `KeyError('columns')`).

- [ ] **Step 11: Прогнать studio smoke-тест и полный бэкенд-сьют**

Run: `cd backend && uv run pytest -q`
Expected: PASS (полный сьют).
Run: `cd studio && uv run pytest -q`
Expected: PASS — граф компилируется, интерфейс `SqlToolInput` не менялся.

- [ ] **Step 12: Commit**

```bash
git add backend/toast/sql_graph.py backend/tests/test_sql_graph.py
git commit -m "$(cat <<'EOF'
refactor(toast): replace scope DB fetch with DB-less init node

desc_full (human-authored) carries the col_N -> meaning mapping, so the
graph no longer fetches real columns from the DB. Rename scope -> init
(accumulators only), drop the columns state field and the "Реальные
колонки" prompt line, and rely on execution-time Postgres errors for
schema drift.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. Spec coverage:**
- Топология `scope` → `init` (без БД) — Task 1, Steps 3, 7, 8. ✓
- `init` только инициализация аккумуляторов — Step 3. ✓
- `generate` берёт колонки из `desc_full`, убрана строка `Реальные колонки` — Step 4. ✓
- `FIXED_SCHEMA` хвост переписан — Step 5. ✓
- Поле `columns` убрано из `SqlToolState` — Step 6. ✓
- docstring графа обновлён — Step 8. ✓
- `executor.fetch_columns` остаётся (граф не зовёт) — не трогаем, подтверждено Step 1 (тест использует его наличие). ✓
- Бэкстоп на рассинхрон (Postgres-ошибка → retry) — существующий код, отдельной задачи не требует; покрыт прежним `test_all_sql_errors_status_error`. ✓
- Тесты обновлены — Steps 1, 10, 11. ✓

**2. Placeholder scan:** плейсхолдеров нет — весь код приведён дословно. ✓

**3. Type consistency:** узел называется `init` во всех шагах (3, 7, 8); `SqlToolState`/`SqlToolInput`/`build_sql_graph` — имена совпадают со спекой и текущим кодом. ✓
