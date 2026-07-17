import asyncio

from langchain_core.messages import AIMessage

from fakes import ScriptedChatModel

LEGAL = "toast_tbl_ec48a6d52d16ab405f95"


class FakeExecutor:
    def __init__(self, columns, results):
        self._columns = columns
        self._results = list(results)  # по одному на каждый вызов run_select
        self.calls = []

    async def fetch_columns(self, table):
        return self._columns

    async def run_select(self, sql, table):
        self.calls.append(sql)
        return self._results.pop(0)


def _rows(n):
    return {"columns": ["column_1"], "rows": [{"column_1": "x"}] * n,
            "row_count": n, "truncated": False}


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


def test_round1_sufficient_ok():
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s", "SELECT column_2 FROM %s"]' % (LEGAL, LEGAL)),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Юрист: Каневский Георгий."),
    ])
    exe = FakeExecutor(["_splitter_source_row", "column_1", "column_2"],
                       results=[_rows(1), _rows(1)])
    out = _run(model, exe)
    assert out["status"] == "ok"
    assert "Каневский" in out["answer"]
    assert len(exe.calls) == 2  # оба кандидата раунда выполнены (параллельно)


def test_retry_then_sufficient():
    # Раунд 1 даёт строки, но судья (LLM) считает их не по теме -> ещё раунд.
    # Судья зовёт модель ТОЛЬКО когда есть успешные строки — здесь так в обоих
    # раундах, поэтому оба вердикта скриптуются.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_2 FROM %s"]' % LEGAL),   # раунд 1
        AIMessage(content="NEED_MORE"),                             # судья -> ещё
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),   # раунд 2
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Ответ по данным."),
    ])
    exe = FakeExecutor(["column_1", "column_2"], results=[_rows(1), _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"
    assert len(exe.calls) == 2


def test_budget_exhausted_no_data():
    # Все кандидаты возвращают 0 строк. Судья при пустом результате НЕ зовёт
    # модель (короткое замыкание в need_more), поэтому скриптуем только 3
    # ответа generate. Бюджет исчерпан -> no_data.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
    ])
    exe = FakeExecutor(["column_1"], results=[_rows(0), _rows(0), _rows(0)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "no_data"
    assert len(exe.calls) == 3


def test_all_sql_errors_status_error():
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT bad FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT worse FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT nope FROM %s"]' % LEGAL),
    ])
    exe = FakeExecutor(["column_1"],
                       results=["Ошибка SQL: a", "Ошибка SQL: b", "Ошибка SQL: c"])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "error"


def test_candidates_run_in_parallel_batch():
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s","SELECT column_2 FROM %s"]' % (LEGAL, LEGAL)),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="ok"),
    ])
    exe = FakeExecutor(["column_1", "column_2"], results=[_rows(1), _rows(1)])
    out = _run(model, exe, candidates=2, max_queries=3)
    assert out["status"] == "ok"
    assert len(exe.calls) == 2


def test_input_schema_exposes_five_fields():
    from toast.sql_graph import SqlToolInput

    keys = set(SqlToolInput.__annotations__)
    assert keys == {"question", "chunk_id", "table", "desc_vector", "desc_full"}


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


def test_attempt_from_refusal_and_result():
    from toast.sql_graph import _attempt

    ref = _attempt("SELECT 1", "Отказ: только чтение")
    assert ref == {"sql": "SELECT 1", "ok": False, "error": "Отказ: только чтение",
                   "rows": [], "row_count": 0, "truncated": False}

    ok = _attempt("SELECT 2",
                  {"rows": [{"a": 1}], "row_count": 1, "truncated": False})
    assert ok == {"sql": "SELECT 2", "ok": True, "error": None,
                  "rows": [{"a": 1}], "row_count": 1, "truncated": False}
