# Toast-логика: SQL-субагент над TOAST-таблицами (итерация 1)

Дата: 2026-07-16. Статус: утверждён.

Источник требований: `problem-questions-report.html` (разбор проблемных
вопросов старого Lore, контракт субагента, eval-набор). Предыдущая
реализация TOAST-слоя удалена коммитом 5022ddf и восстанавливается из
git history (`5022ddf^`) с адаптацией под реальную БД.

## Решения, принятые в обсуждении

| Вопрос | Решение |
| --- | --- |
| Источник данных | Напрямую тестовая БД `loreagent_test` (data-postgres-internal2) |
| Права юзера БД | Пишущий юзер → вся read-only защита на нашей стороне |
| Объём итерации 1 | Discovery + inspect + guarded SELECT + abstention (кейсы grade, mobile, abstain). Header recovery — итерация 2, authz privacy gate — итерация 3. Примитивный PII block-list остаётся уже в итерации 1, т.к. БД живая |
| Модель | OpenRouter для всего backend (`ChatOpenAI` + base_url), фолбэк на Ollama через env-переключатель |
| Архитектура | Вариант A: весь пайплайн в одном инструменте `query_document_tables`, добавляется в оба режима рядом с calculator; режимы fast/deep не меняются |

## Архитектура

Toast-субагент — детерминированный пайплайн из отчёта, упакованный в
один LangChain-инструмент `query_document_tables(question)`. LLM внутри
используется ровно в одной точке — планирование SELECT по найденной
схеме; discovery, inspect, валидация, выполнение и provenance — код.

```
вопрос → агент (fast/deep) → tool: query_document_tables
           ├─ 1. discover   — 3 волны поиска по lore_core (фраза → слова → стемы)
           │       └─ пусто → status=no_table (abstention, SQL не генерируется)
           ├─ 2. inspect    — колонки, row_count, header_hint для топ-5 таблиц
           ├─ 3. policy     — детерминированный PII block-list ДО планирования
           ├─ 4. plan SQL   — LLM: вопрос + схемы таблиц → один SELECT
           ├─ 5. validate   — guardrails: SELECT-only, allowlist схем, шаблон toast_tbl
           ├─ 6. execute    — READ ONLY транзакция, timeout 5s, лимит 200 строк
           │       └─ ошибка SQL → один retry шага 4 с текстом ошибки
           └─ 7. результат  — JSON: status, rows, sql, sources (provenance)
```

Финальный ответ пользователю пишет основной агент из этого JSON.
Системный промпт требует: указывать источник (файл/таблицу), при
`no_table` — честный отказ, не выдумывать данные.

## Компоненты

### `backend/toast/` — восстановить из `5022ddf^` с адаптацией

- `port.py` — без изменений: протокол `ToastStorePort`, типы
  `DiscoveredTable` / `TableInfo` / `SelectResult`.
- `pg.py` — `PgToastStore`. DSN из нового env `TOAST_DATABASE_URL`
  (→ `loreagent_test`). Новое: каждый запрос в READ ONLY транзакции
  (юзер БД пишущий) + `statement_timeout` через server_settings пула.
  Трёхволновый discovery и inspect остаются как были. `MAX_ROWS = 200`.
- `guardrails.py` — без изменений: одна команда, только SELECT,
  allowlist схем `lore_core|splitter_toast|information_schema`, имена
  таблиц по шаблону `^toast_tbl_[0-9a-f]{20}$`, автоквалификация
  `splitter_toast.` для голых имён.
- `policy.py` — block-list с реальным id графика отпусков
  `toast_tbl_9c6dcab0dfdd486cfddf` (в старом коде был фейковый id).
  Полноценный authz-gate — итерация 3.
- `subagent.py` — новый: пайплайн как обычная async-функция (не
  langgraph), переработанная логика старого fast.py. Сигнатура
  `(model, store, question) -> результат`; один retry планирования SQL.

### `backend/agents/`

- `tools.py` — `make_tools(model, store)` возвращает
  `[calculator, query_document_tables]`. `header_hint` из inspect
  прокидывается в результат как есть; логика восстановления
  header-строк — итерация 2.
- `base.py` — `build_model()` переходит на `ChatOpenAI`
  (пакет `langchain-openai`): env `OPENROUTER_API_KEY`,
  `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`
  (дефолт `https://openrouter.ai/api/v1`). Переключатель
  `MODEL_PROVIDER=openrouter|ollama` сохраняет фолбэк на Ollama.
  Системные промпты дополняются: для вопросов о сотрудниках, отделах,
  грейдах и документах — использовать `query_document_tables`;
  provenance обязателен; при `no_table` не придумывать ответ.

### Инфраструктура

- `app.py` — lifecycle `PgToastStore` (создание/закрытие пула; код был
  в истории), передача store в `make_tools`.
- `docker-compose.yml` — env `TOAST_DATABASE_URL`, `OPENROUTER_API_KEY`,
  `OPENROUTER_MODEL`, `MODEL_PROVIDER`. Сервис ollama остаётся, но
  перестаёт быть обязательным.

## Формат результата инструмента

JSON со статусом и данными:

- `status`: `ok | no_table | refused | error`
- `rows`, `row_count`, `truncated` — при `ok`
- `sql` — выполненный запрос
- `sources` — список `{source_path, table_id, coordinates}` (provenance)
- `header_hints` — display_text чанков для найденных таблиц (passthrough)
- `message` — текст отказа/ошибки при `refused | error | no_table`

## Обработка ошибок

- БД недоступна / таймаут → `status=error`, короткий текст; агент честно
  сообщает о технической проблеме.
- SQL не прошёл guardrails или упал → один retry планирования с текстом
  ошибки; вторая неудача → `status=error` с последней ошибкой.
- Discovery пуст → `status=no_table` — эталонное abstention-поведение.
- PII-гейт двойной: до планирования (все найденные таблицы — PII → SQL
  не планируется вовсе) и повторно на готовом SQL (`check_policy`);
  срабатывание → `status=refused` с текстом policy-отказа.
- Больше 200 строк → `truncated=true`; агент обязан упомянуть неполноту.

## Тестирование

- **Unit (pytest, без сети):** восстановить `test_guardrails.py` из
  истории; новый `test_subagent.py` на фейковом store + фейковой модели
  (паттерны фейков — в `test_agents.py`): happy path, no_table,
  PII-отказ, retry после ошибки SQL, truncated.
- **Eval (`infra/eval-agents.py`):** кейсы отчёта в текущем формате
  must_any/must_not:
  - `toast-grade-001` — упоминание уровней (3–4 vs 5) и lead-only
    компетенций; must_not: утверждение, что матрицы нет;
  - `toast-mobile-001` — in-app источники, MMP/AppsFlyer;
  - `toast-abstain-001` — формулировка отказа; must_not: выдуманные
    данные.
  - Запуск вручную при поднятом стеке с доступом к тестовой БД и ключом
    OpenRouter; диагностика, не CI-гейт.

## Вне итерации 1

- Итерация 2: header recovery (восстановление первой строки блока из
  `lore_core.chunks.display_text` в ответах) — кейсы
  `toast-roster-001`, `toast-legal-001`.
- Итерация 3: authz/policy gate вместо block-list — кейс
  `toast-privacy-001`.
