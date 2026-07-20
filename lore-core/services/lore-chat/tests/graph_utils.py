"""Общие фейки и хелперы тестов SQL-графа."""

import asyncio

LEGAL = "toast_tbl_ec48a6d52d16ab405f95"


class FakeExecutor:
    """Исполнитель без fetch_columns: граф обязан обходиться одним run_select."""

    def __init__(self, results):
        self._results = list(results)  # по одному на каждый вызов run_select
        self.calls = []

    async def run_select(self, sql, table):
        self.calls.append(sql)
        return self._results.pop(0)



def _rows(n):
    return {"columns": ["column_1"], "rows": [{"column_1": "x"}] * n,
            "row_count": n, "truncated": False}



def _sample():
    # результат сэмпл-запроса (первый run_select каждого прогона)
    return _rows(1)



def _inp(question="ФИО юристов"):
    return {
        "question": question,
        "chunk_id": "c1",
        "table": LEGAL,
        "desc_vector": "юристы",
        "desc_full": "Таблица юристов Adventum",
    }



def _run(model, executor, **cfg):
    from toast.sql_graph import build_sql_graph

    graph = build_sql_graph(model, executor,
                            max_queries=cfg.get("max_queries", 3),
                            candidates_per_round=cfg.get("candidates", 2))
    return asyncio.run(graph.ainvoke(_inp()))



def _ok_attempt(sql, rows):
    return {"sql": sql, "ok": True, "error": None, "rows": rows,
            "row_count": len(rows), "truncated": False}



def _fail_attempt(sql="SELECT bad", error="Ошибка SQL: x"):
    return {"sql": sql, "ok": False, "error": error, "rows": [],
            "row_count": 0, "truncated": False}
