# SQL-инструмент: рефакторинг читаемости (без изменения поведения)

**Дата:** 2026-07-17
**Статус:** утверждён, ждёт плана реализации
**Ветка:** `toast-logic`; затем merge в `demo/sql-chat` и `backend`
**Затрагивает:** `backend/toast/*` (новые модули), тесты (только импорты и
разбиение), `docs/sql-tool.md` (ссылки на файлы)

## Проблема

`toast/sql_graph.py` вырос до ~450 строк и совмещает четыре ответственности:
промпты, LLM-обвязку с фолбэками, чистые функции над данными и сборку
графа. Модели объявлены в случайных местах (`SqlCandidates`/`JudgeVerdict`
среди хелперов, `SelectResult` в executor). Служебные контракты — строковые
и неявные: результат исполнителя `SelectResult | str`, где вид строки
различается ПАРСИНГОМ ПРЕФИКСА «Отказ:», причём от этого префикса зависит
подсчёт бюджета в `execute` — переформулировка текста отказа в guardrails
молча сломала бы бюджет, не уронив ни одного теста guardrails.

## Решение

Рефакторинг **строго без изменения поведения**: все существующие тесты
проходят с правкой только импортов; вход/выход графа, сигнатура
`build_sql_graph`, Studio-совместимость и модель безопасности не меняются.

### 1. Раскладка модулей `backend/toast/`

- **`models.py`** — ВСЕ типы в одном месте: `SqlToolInput`, `SqlToolState`
  (pydantic), `SqlCandidates`, `JudgeVerdict` (pydantic, structured output),
  `Attempt`, `SelectResult` (TypedDict), новые `Refusal`/`DbError`
  (dataclass), enum'ы `Status` и `Verdict` (StrEnum); рядом — чистые
  функции над попытками: `make_attempt` (бывш. `_attempt`), `ok_rows`
  (бывш. `_ok_rows`).
- **`prompts.py`** — константы `FIXED_SCHEMA`, `GENERATE_SYS`, `JUDGE_SYS`,
  `SUMMARIZE_SYS`, `NO_DATA_MSG`, `NO_CANDIDATES_MSG`, капы
  (`JUDGE_ROWS_CAP`, `JUDGE_CONTEXT_CHARS`, `SAMPLE_LIMIT`,
  `SAMPLE_CONTEXT_CHARS`) + сборка текстов: `generate_prompt(state, n)`
  (секции фидбека — отдельные маленькие функции, возвращающие
  `str | None`, соединяются join'ом), `rows_context(attempts)`
  (бывш. `_rows_context`).
- **`llm.py`** — вся «грязь» structured output с фолбэком:
  `generate_candidates`, `judge_verdict`, `parse_sql_candidates`,
  `_log_fallback`. Один докстринг модуля объясняет, почему фолбэки
  обязательны (OpenRouter/фейки).
- **`sql_graph.py`** — класс `SqlToolNodes` (зависимости `model`,
  `executor`, `max_queries`, `candidates_per_round` в `__init__`;
  узлы и роутеры — методы по 10–15 строк) + `build_sql_graph(...)` —
  чистая топология на ~15 строк. Сигнатура не меняется.
- `sql_guardrails.py`, `executor.py`, `sql_tool.py` — остаются;
  `SelectResult` переезжает в models, executor его импортирует.

### 2. Типизированные контракты вместо строк

- `run_select(...) -> SelectResult | Refusal | DbError`:
  `Refusal(reason)` — отказ guardrails (бюджет НЕ тратится),
  `DbError(message)` — ошибка БД/сети/таймаут (бюджет потрачен).
  Подсчёт бюджета в `execute` — `isinstance(res, Refusal)` вместо
  `startswith("Отказ:")`; строковый префикс перестаёт быть контрактом.
  `validate_select` в guardrails по-прежнему возвращает `str | None`
  (чистая текстовая валидация) — в `Refusal` оборачивает executor.
- `Status` (`OK/NO_DATA/ERROR`) и `Verdict` (`SUFFICIENT/NEED_MORE`) —
  StrEnum; наружу в контракте `_project` уходят те же строки
  (`"ok"/"no_data"/"error"`), внешний контракт не меняется.
- В `Attempt` текст ошибки/отказа остаётся строкой (`error`), как сейчас, —
  формат попыток в `sql_attempts` наружу не меняется.

### 3. Тесты

- Существующие: только правка импортов (`SqlCandidates`/`JudgeVerdict` из
  `toast.models`, и т.п.) и подмена скриптованных строк-отказов на
  `Refusal(...)` в сценариях FakeExecutor, где тестируется бюджет.
- `test_sql_graph.py` разбивается по темам: `test_graph_flow.py` (happy
  path, retry, параллельность), `test_graph_budget.py` (бюджет, раунды,
  дедуп, отказы), `test_graph_llm.py` (парсер, structured фолбэки, судья,
  промпт-фидбек), `test_graph_context.py` (rows_context, капы). Сами
  проверки не меняются.
- Новый маленький тест: `Refusal` не списывает бюджет / `DbError`
  списывает — уже есть по сути, переформулируется на типы.

### 4. Документация

`docs/sql-tool.md`: обновить упоминания файлов (models/prompts/llm) и
описание контракта исполнителя (типизированные результаты вместо
«str = отказ/ошибка»). Поведенческие разделы не меняются.

## Не делаем (осознанно)

- Не сливаем guardrails с executor (раздельность слоёв — часть модели
  безопасности); не делаем «правила валидации как данные».
- Не меняем топологию, фолбэки, капы, промпты по содержанию.
- Не трогаем внешний контракт `run_sql_tool`/`_project` и вход Studio.
- Демо-ветка: после merge чинится только то, что сломают импорты
  (ожидаемо — ничего: `sql_demo.py` импортирует лишь `build_sql_graph`).

## Критерий готовности

Все тестовые наборы зелёные без изменения ассертов поведения (только
импорты/типы в фикстурах); ruff чисто; Studio smoke зелёный; diff
`docs/sql-tool.md` — только имена файлов и контракт исполнителя.
