# SQL-инструмент: eval-харнесс для сравнения LLM (LangSmith self-hosted)

Дата: 2026-07-20
Ветка: `backend`
Статус: одобрено (дизайн), готово к плану реализации

## Цель

Прогонять SQL-инструмент (`toast`) на одном и том же наборе вопросов с разными
LLM и сравнивать результаты бок о бок: корректность ответа, выполнимость SQL,
латентность, токены/стоимость. Инструмент оценки — **LangSmith
(self-hosted)**: данные не покидают контур.

Не-цель: гейтить CI, строить устойчивый HTML-парсер отчёта, менять код `toast/`.

## Ключевые решения (из брейншторма)

1. **LangSmith self-hosted** — код эксперимента идентичен облачному, отличаются
   только `LANGSMITH_ENDPOINT` + `LANGSMITH_API_KEY`, указывающие на свой инстанс.
2. **Только OpenRouter** — «разные LLM» = разные имена моделей OpenRouter через
   один API-ключ. Единственная варьируемая ось прогона.
3. **Датасет из `problem-questions-report.html`** — одноразовое ассистированное
   извлечение ~5 сильных кейсов в закоммиченный `sql_cases.json` (не парсер).
4. **Оценщики: эвристика + LLM-judge** — детерминированные проверки плюс судья,
   сравнивающий ответ с «Проверенным ответом» из отчёта.

## Подход (выбран A)

Отдельный CLI-скрипт на `langsmith.aevaluate()` + закоммиченный датасет-файл,
синкаемый в LangSmith при запуске. Для каждой модели из списка — свой
эксперимент с `experiment_prefix=<модель>`; сравнение в LangSmith UI.

Отклонённые: (B) eval через pytest-плагин LangSmith — отложен на потом для
CI-гейта поверх тех же evaluators; (C) чистый офлайн — не даёт eval-UI.

## Раскладка модулей

Следует конвенции репозитория (пакет-директория как `agents/`, `toast/`):

```
backend/evals/
  __init__.py
  run_sql_eval.py      # CLI: перебор моделей → aevaluate(), точка входа
  dataset.py           # загрузка sql_cases.json → примеры; sync в LangSmith-датасет
  evaluators.py        # эвристики + LLM-judge корректности
  models.py            # build_eval_model(name) — ChatOpenAI по имени OpenRouter-модели
  datasets/
    sql_cases.json     # ~5 кейсов: входы SqlToolInput + reference_answer
docs/evals.md          # как запускать: env, команда, чтение результатов
backend/tests/test_evals.py  # юнит на evaluators + загрузку датасета, на фейках, без сети
```

`toast/` не трогаем: `run_sql_tool(inputs, model, executor, max_queries,
candidates_per_round)` уже спроектирован как точка входа для eval.

## Поток данных

```
sql_cases.json ──dataset.py──> LangSmith dataset (self-hosted, sync по имени)
                                      │
run_sql_eval.py: для каждой модели M ─┤
   target(inputs) = run_sql_tool(inputs, build_eval_model(M),
                                  PgExecutor(toast_dsn), max_queries, cpr)
                                      │
   aevaluate(target, data, evaluators, experiment_prefix=M)
                                      ▼
        LangSmith UI: эксперименты M1..Mn бок о бок + трейсы узлов графа
```

## Компоненты и контракты

### `models.build_eval_model(name: str) -> BaseChatModel`
Строит `ChatOpenAI(model=name, base_url=openrouter_base_url,
api_key=openrouter_api_key, temperature=0)`. Переиспользует `_max_tokens_kwargs`
из `agents/base.py`. Единственная варьируемая ось эксперимента.

### `target` (в `run_sql_eval.py`)
Тонкая async-обёртка над существующим `run_sql_tool`. `PgExecutor(toast_dsn)`
создаётся один раз на прогон и шарится между примерами (соединение берётся
на запрос внутри самого executor'а). Возвращает проекцию `run_sql_tool`.

### `dataset` (в `dataset.py`)
- Загружает и валидирует `sql_cases.json`.
- Каждый кейс: `inputs` = поля `SqlToolInput` (question, chunk_id, table,
  desc_vector, desc_full) + `outputs` = `{ reference_answer }`.
- Идемпотентно создаёт/обновляет LangSmith-датасет по фиксированному имени.

### `evaluators` (в `evaluators.py`)
Вход — output `run_sql_tool` + reference из примера:
- `executes_ok` — есть хоть один `sql_attempts[*].ok` без error (детерм.).
- `status_ok` — `status == "ok"` (детерм.).
- `has_rows` — `rows_used > 0` (детерм.).
- `answer_correct` — **LLM-judge**: сравнивает `answer` с `reference_answer`.
  Модель-судья **фиксирована** на все эксперименты (env `EVAL_JUDGE_MODEL`) —
  иначе сравнение кандидатов нечестное. Судья ≠ оцениваемая модель.
- latency / токены / стоимость — LangSmith берёт из трейсов автоматически,
  отдельного кода не требуют.

## Решение по `desc_vector` / `desc_full`

В отчёте этих полей нет, а `SqlToolInput` их требует. Заполняем вручную в
`sql_cases.json` по каждой таблице, сидируя из имён колонок (схемы уже есть в
`sql_reqults.txt`): `desc_full` = назначение таблицы + список колонок;
`desc_vector` = одна строка-саммари. В проде их даёт пайплайн Lore; для eval
фиксируем в датасете ради воспроизводимости.

## Извлечение из отчёта

Одноразовое, ассистированное: вытащить ~5 кейсов (question, table, chunk_id,
reference_answer) из `problem-questions-report.html` в `sql_cases.json`,
проверить глазами. Устойчивый HTML-парсер ради 5 кейсов не пишем (YAGNI).

## Обработка ошибок

- Сбой одного примера (недоступная модель, 402, битый SQL) роняет только этот
  пример как ошибку прогона в LangSmith, не весь эксперимент.
- Отсутствие обязательного окружения (`TOAST_DB_*`, LangSmith env,
  `OPENROUTER_API_KEY`) — ранний выход с внятным сообщением.

## Тестирование

`backend/tests/test_evals.py` — юнит на evaluators (фейковые output'ы) и на
загрузку/валидацию `sql_cases.json`. Без сети и без LangSmith, как существующие
тесты на фейках.

## Прекондиции запуска (окружение, не код)

- Развёрнутый self-hosted LangSmith + `LANGSMITH_ENDPOINT`, `LANGSMITH_API_KEY`,
  `LANGSMITH_TRACING=true`.
- `OPENROUTER_API_KEY`.
- `TOAST_DB_*` с доступом к реальным `splitter_toast.*`.

## Зависимости

Добавить `langsmith` в `backend/pyproject.toml`.

## Что вне скоупа (следующие итерации)

- pytest-плагин LangSmith для CI-гейта (подход B) поверх тех же evaluators.
- Расширение датасета за пределы ~5 кейсов отчёта.
- Сравнение с Ollama-моделями (сейчас только OpenRouter).
