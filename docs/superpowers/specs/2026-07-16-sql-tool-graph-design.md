# SQL-инструмент как langgraph-граф (одна таблица)

Дата: 2026-07-16. Статус: утверждён.

## Контекст

Toast-логика пересматривается. На этом этапе разрабатывается **только один
SQL-инструмент** — будущая часть большего пайплайна (роутинг запроса → RAG →
топ-чанки из Qdrant → по каждому чанку SQL-инструмент → объединение ответов).
Остальное из прошлой итерации (discover/inspect/policy/header-recovery)
выкидывается.

Инструмент отвечает на запрос пользователя по **ровно одной** таблице,
привязанной к чанку, генерируя SQL в несколько попыток и суммируя результат.
Оформляется как langgraph-граф, обёрнутый в LangChain-tool.

## Решения обсуждения

| Вопрос | Решение |
| --- | --- |
| Форма графа | Гибрид: раунды × параллель. В раунде — батч параллельных SQL-кандидатов; нет ответа → новый раунд, до бюджета |
| Знание о таблице | Имя + два описания (векторное + полное) в промпте; фиксированная схема toast-таблиц зашита в системный промпт; в узле scope — детерминированный фетч реальных колонок из `information_schema` |
| Судья | Отдельный семантический LLM-узел: вердикт `sufficient | need_more` |
| Роль chunk id | Фильтр строк таблицы (предикат). Конкретный механизм пиним по реальной БД (открытый пункт) |
| Контракт выхода | Структура: `status`, `answer`, `chunk_id`, `table`, `sql_attempts`, `rows_used` |
| Модель | Отдельный `sql_model` в конфиге (OpenRouter); все три роли на нём |
| Старый код | Удалить лишнее, оставить ядро (read-only исполнитель + guardrails, ужесточённые под одну таблицу) |

## Вход и выход инструмента

**Вход** (структурированный; для этой итерации — захардкоженные чанки/таблицы):

```
{
  question: str,                    # запрос пользователя
  chunk_id: str,                    # для scope-фильтра и провенанса
  table_name: str,                  # splitter_toast.toast_tbl_<hex>
  table_description_vector: str,    # короткое семантическое описание
  table_description_full: str,      # подробное описание
}
```

**Источник описаний в этой итерации.** Отдельных «векторного» и «полного»
описаний в `loreagent_test` пока нет — это концепции будущего RAG-пайплайна.
Единственный реальный артефакт — `lore_core.chunks.display_text` (в отчёте
брался как `summary`). Поэтому для захардкоженных тестовых чанков:
`table_description_full` = реальный `display_text` из БД;
`table_description_vector` = короткая выжимка (первая строка/предложение
`display_text`). Оба поля сохраняются в контракте как future-proof; когда RAG
появится, векторное описание придёт из своего источника.

**Выход:**

```
{
  status: "ok" | "no_data" | "error",
  answer: str,                      # текст суммаризатора или «данных нет»
  chunk_id: str,
  table: str,
  sql_attempts: [{ sql, ok: bool, error: str | None, row_count: int }],
  rows_used: int,
}
```

## Граф (langgraph)

```
scope → generate → execute(∥) → judge ──sufficient | budget──→ summarize → END
           ▲                        │
           └──── need_more & budget ┘
```

### Узлы

- **scope** (детерминированный, БД): фетч реальных колонок таблицы из
  `information_schema.columns`. Обязателен: физические имена колонок часто
  переименованы (`senior_legal_manager`, `j_suvorova_adventum_ru`,
  `col_1999_11_04_00_00_00`, `column_18`…) и НЕ совпадают с человеческими
  заголовками в `display_text` — без реальных имён SQL не построить. Кладёт в
  состояние `columns`. Фильтра строк по чанку НЕТ (см. ниже): чанк = целая
  таблица.

- **generate** (LLM `sql_model`): системный промпт с фиксированной схемой
  toast-таблиц; пользовательский промпт с вопросом, именем, обоими описаниями,
  реальными колонками и (при retry) прошлыми ошибками. Возвращает **батч** из
  `sql_candidates_per_round` разнообразных SELECT (диверсификация через
  temperature и/или разные инструкции-«углы»), с учётом остатка бюджета.

- **execute** (параллельно): каждый кандидат — через read-only исполнитель
  одной таблицы. Guardrails: только `SELECT`, ссылка **ровно** на переданную
  таблицу, JOIN к другим таблицам запрещён. `statement_timeout`, лимит строк.
  Результат каждого — `{sql, ok, error, rows, row_count, truncated}`, копится в
  `attempts`, `executed_count += len(batch)`.

- **judge** (LLM): вопрос + накопленные строки (обрезанные до K для контекста)
  → структурный вердикт `sufficient | need_more`. Ловит «строки есть, но не по
  теме».

- **условный переход:** `sufficient` **или** `executed_count >= sql_max_queries`
  → summarize; иначе новый раунд generate.

- **summarize** (LLM): ответ строго по накопленным строкам; если данных нет или
  они не отвечают — «данных нет». Жёсткий anti-hallucination-промпт.

### Состояние

```
{
  question, chunk_id, table, desc_vector, desc_full,
  columns: list[str],
  round: int, executed_count: int,
  attempts: list[{sql, ok, error, rows, row_count, truncated}],
  verdict: "sufficient" | "need_more" | None,
  answer: str, status: str,
}
```

## Конфиг (новые поля, OpenRouter)

- `sql_model` (`SQL_MODEL`) — «умная» модель по умолчанию для дебага; ключ и
  base_url — общие openrouter (`openrouter_api_key`, `openrouter_base_url`).
- `sql_max_queries` (`SQL_MAX_QUERIES`, дефолт 3) — бюджет всего SQL-выполнений
  за все раунды.
- `sql_candidates_per_round` (`SQL_CANDIDATES_PER_ROUND`, дефолт 2) — сколько
  параллельных кандидатов в раунде (последний раунд урезается под остаток
  бюджета).

## Файлы

- `toast/executor.py` (новый/из `pg.py`) — read-only пул + `run_select(sql,
  table_name)` одной таблицы (без discover/inspect). `information_schema`-фетч
  колонок.
- `toast/guardrails.py` (правится) — `validate_select(sql, allowed_table)`:
  ровно эта таблица, JOIN к другим запрещён, только SELECT, read-only.
- `toast/sql_graph.py` (новый) — узлы, состояние, `build_sql_graph(...)`.
- `toast/sql_tool.py` (новый) — обёртка графа в LangChain-tool с входным
  контрактом выше.
- `config.py` (правится) — поля `sql_model`, `sql_max_queries`,
  `sql_candidates_per_round`.
- **Удаляем:** `toast/subagent.py`, `toast/policy.py`, discover/inspect/
  трёхволновый поиск из `pg.py`, `query_document_tables` и его промпт-часть,
  соответствующие тесты (`test_subagent.py`, PII-тесты) и toast-eval-кейсы.

## Обработка ошибок

- Все кандидаты раунда упали (ошибки БД) → ошибки в `attempts`, новый раунд.
- Бюджет исчерпан, судья `need_more` или строк нет → `status=no_data`,
  `answer` = «данных нет».
- Все SQL за все раунды — ошибки БД (валидных строк ни разу) → `status=error`.
- Строки в judge/summarize обрезаются до K строк (пометка `truncated`), чтобы
  не раздувать контекст.
- Ошибка соединения с БД → `status=error` с текстом.

## Тестирование

- **guardrails** (`test_guardrails.py`, переписать): пиннинг к одной таблице;
  запрет чужих таблиц, JOIN, не-SELECT, мутаций.
- **граф** (`test_sql_graph.py`, новый) на фейках (модель + исполнитель):
  раунд-1 достаточно; retry затем достаточно; бюджет исчерпан → no_data; все
  ошибки → error; параллельные кандидаты выполняются; scope применяет
  `row_filter`.
- **исполнитель** (`test_executor.py`, интеграция, skip без `TOAST_DATABASE_URL`):
  фетч колонок и `run_select` против живой `loreagent_test` на захардкоженной
  таблице из отчёта; мутация отвергается.
- Тесты гоняются на Node не нужны — это backend (`cd backend && uv run pytest`).

## Открытые пункты (резолвятся в плане по реальной БД)

1. **Дефолт `sql_model`:** конкретный slug «умной» модели OpenRouter выбирается
   при реализации.

## Что подтверждено выгрузкой из loreagent_test (папка sqls/)

- **Фиксированная схема toast-таблицы:** первые 3 служебные колонки —
  `_splitter_row_number` (int), `_splitter_source_row` (int),
  `_splitter_source_range` (text); дальше колонки данных (`column_N` или
  переименованные, типы text/numeric/date). Зашивается в системный промпт
  generate.
- **chunk = целая таблица:** 99 из 114 payload имеют ровно 1 чанк; где несколько
  — это разные представления одной таблицы, НЕ разбиение по строкам.
  Под-диапазона строк на чанк нет → `row_filter` не нужен, `chunk_id` = провенанс
  и идентичность таблицы (1:1). `payload_refs` = `[{kind:table, payload_id, …}]`.
- **Переименованные колонки:** физические имена (`senior_legal_manager`,
  `j_suvorova_adventum_ru`, `col_…`) не совпадают с человеческими заголовками в
  `display_text`. → фетч колонок из `information_schema` в scope обязателен.
- **Фикстуры описаний:** `display_text` вида «Table payload: <sheet> <a1_range>\n
  Columns: …\nRows: N» → `table_description_full`; `table_description_vector` =
  первая строка выжимки. Реальные примеры — в `sqls/second_sql.csv`.

## Известное ограничение (вне scope этой итерации)

**header-as-data:** у части таблиц первая строка стала именами колонок
(например у юр-таблицы Суворова закодирована в именах колонок/`display_text`, а
в строках есть только Каневский). Без header-recovery (вырезан) инструмент по
такой таблице вернёт неполный набор. Принимаем как ограничение; восстановление
заголовков — отдельная задача позже.

## Вне scope (YAGNI)

- Никакого discovery/роутинга/RAG — вход уже содержит чанк и таблицу.
- Никаких JOIN и мульти-табличных запросов.
- Никакой PII-policy (вырезается) — вернётся отдельным решением позже.
- Объединение ответов по чанкам — задача upstream, не этого инструмента.
