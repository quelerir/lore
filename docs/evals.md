# Eval-харнесс SQL-инструмента (LangSmith self-hosted)

Прогон `toast` на фиксированном датасете вопросов с разными OpenRouter-моделями
и сравнение в self-hosted LangSmith.

## Окружение

- `OPENROUTER_API_KEY` — ключ OpenRouter.
- `TOAST_DB_HOST/PORT/USER/PASSWORD/NAME` — доступ к реальным `splitter_toast.*`.
- `LANGSMITH_ENDPOINT` — URL self-hosted инстанса LangSmith.
- `LANGSMITH_API_KEY` — ключ инстанса.
- `LANGSMITH_TRACING=true` — включает трейсинг узлов графа.
- `EVAL_JUDGE_MODEL` — фиксированная модель-судья (по умолчанию `anthropic/claude-sonnet-4.6`).

## Запуск

    cd backend
    python -m evals.run_sql_eval --models "openai/gpt-4o, anthropic/claude-sonnet-4.6"

Флаги: `--judge-model`, `--dataset-name` (по умолчанию `sql-tool-eval`),
`--limit N` (дымовой прогон), `--max-concurrency`.

## Что смотреть в LangSmith

Каждой модели соответствует эксперимент с префиксом-именем модели. Метрики
оценщиков: `executes_ok`, `status_ok`, `has_rows`, `answer_correct`. Латентность
и токены/стоимость LangSmith берёт из трейсов автоматически. Сравнение
экспериментов бок о бок — во вкладке датасета `sql-tool-eval`.

## Датасет

`backend/evals/datasets/sql_cases.json` — 5 кейсов из
`problem-questions-report.html`. Поля `inputs` совпадают с `SqlToolInput`,
`outputs.reference_answer` — эталон для судьи. Первый прогон заливает датасет в
LangSmith; повторные переиспользуют по имени.

Инструмент работает над одной таблицей, поэтому каждый кейс привязан к одной
наиболее релевантной `toast_tbl_*`. Кейс отпусков (`toast-privacy`) намеренно
ожидает отказ/эскалацию до policy-gate — у текущего инструмента такого гейта
нет, поэтому `answer_correct` по нему покажет ожидаемый провал.
