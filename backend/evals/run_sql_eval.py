"""CLI eval-харнесса: прогон SQL-инструмента по моделям в LangSmith.

Пример:
    cd backend && python -m evals.run_sql_eval \
        --models "openai/gpt-4o, anthropic/claude-sonnet-4.6"

Требует окружения: OPENROUTER_API_KEY, TOAST_DB_*, LANGSMITH_ENDPOINT/
LANGSMITH_API_KEY (self-hosted). Латентность и токены LangSmith снимает из
трейсов автоматически.
"""

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from langsmith import Client, aevaluate

from config import get_settings
from evals.dataset import ensure_dataset, load_cases
from evals.evaluators import executes_ok, has_rows, make_answer_correct, status_ok
from evals.models import build_eval_model
from toast.executor import PgExecutor
from toast.sql_tool import run_sql_tool

DATASET_PATH = Path(__file__).resolve().parent / "datasets" / "sql_cases.json"
DEFAULT_DATASET_NAME = "sql-tool-eval"


def make_target(model, executor, settings) -> Callable[[dict], Awaitable[dict]]:
    """Async-target для aevaluate: прогон одного примера через run_sql_tool."""

    async def target(inputs: dict) -> dict:
        return await run_sql_tool(
            inputs, model, executor,
            settings.sql_max_queries, settings.sql_candidates_per_round,
        )

    return target


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Eval SQL-инструмента по моделям")
    p.add_argument("--models", required=True,
                   help="OpenRouter-модели через запятую")
    p.add_argument("--judge-model", default=None,
                   help="модель-судья (по умолчанию EVAL_JUDGE_MODEL)")
    p.add_argument("--dataset-name", default=DEFAULT_DATASET_NAME)
    p.add_argument("--limit", type=int, default=None,
                   help="ограничить число кейсов (для дымового прогона)")
    p.add_argument("--max-concurrency", type=int, default=4)
    ns = p.parse_args(argv)
    ns.models = [m.strip() for m in ns.models.split(",") if m.strip()]
    return ns


async def main(argv=None) -> None:
    args = parse_args(argv)
    settings = get_settings()
    if settings.toast_dsn is None:
        raise SystemExit("TOAST_DB_* обязателен для eval (доступ к splitter_toast.*)")

    cases = load_cases(DATASET_PATH)
    if args.limit is not None:
        cases = cases[: args.limit]

    client = Client()  # LANGSMITH_ENDPOINT / LANGSMITH_API_KEY из окружения
    ensure_dataset(client, args.dataset_name, cases)

    executor = PgExecutor(settings.toast_dsn)
    judge = build_eval_model(
        args.judge_model or settings.eval_judge_model, settings, temperature=0.0
    )
    evaluators = [executes_ok, status_ok, has_rows, make_answer_correct(judge)]

    for model_name in args.models:
        model = build_eval_model(model_name, settings)
        await aevaluate(
            make_target(model, executor, settings),
            data=args.dataset_name,
            evaluators=evaluators,
            experiment_prefix=model_name,
            client=client,
            max_concurrency=args.max_concurrency,
        )
        print(f"готово: {model_name}")


if __name__ == "__main__":
    asyncio.run(main())
