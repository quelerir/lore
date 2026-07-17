import asyncio

from langchain_core.messages import AIMessage

from fakes import ScriptedChatModel

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


def test_round1_sufficient_ok():
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s", "SELECT column_2 FROM %s"]' % (LEGAL, LEGAL)),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Юрист: Каневский Георгий."),
    ])
    exe = FakeExecutor(results=[_sample(), _rows(1), _rows(1)])
    out = _run(model, exe)
    assert out["status"] == "ok"
    assert "Каневский" in out["answer"]
    assert len(exe.calls) == 3  # сэмпл + оба кандидата раунда


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
    exe = FakeExecutor(results=[_sample(), _rows(1), _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"
    assert len(exe.calls) == 3


def test_budget_exhausted_no_data():
    # Все кандидаты возвращают 0 строк. Судья при пустом результате НЕ зовёт
    # модель (короткое замыкание в need_more), поэтому скриптуем только 3
    # ответа generate. Бюджет исчерпан -> no_data. SQL в раундах разные —
    # повторы не выполняются (дедупликация), но бюджет списывают.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_2 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_3 FROM %s"]' % LEGAL),
    ])
    exe = FakeExecutor(results=[_sample(), _rows(0), _rows(0), _rows(0)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "no_data"
    assert len(exe.calls) == 4  # сэмпл + 3 кандидата


def test_duplicate_candidates_stopped_by_round_cap():
    # Повтор SQL не гоняется в БД и бюджет НЕ двигает — цикл останавливает
    # предел раундов (== max_queries).
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),  # дубликат
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),  # дубликат
    ])
    exe = FakeExecutor(results=[_sample(), _rows(0)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "no_data"
    assert len(exe.calls) == 2  # сэмпл + один реальный SELECT


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


def test_all_sql_errors_status_error():
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT bad FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT worse FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT nope FROM %s"]' % LEGAL),
    ])
    exe = FakeExecutor(results=[_sample(), "Ошибка SQL: a", "Ошибка SQL: b", "Ошибка SQL: c"])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "error"


def test_no_candidates_terminates_with_error():
    # Модель не вернула ни одного SELECT: без ветки generate->summarize это
    # крутилось бы до GraphRecursionError (executed_count не растёт).
    model = ScriptedChatModel(responses=[
        AIMessage(content="Извините, не могу составить запрос."),
    ])
    exe = FakeExecutor(results=[_sample()])
    out = _run(model, exe, candidates=2, max_queries=3)
    assert out["status"] == "error"
    assert exe.calls == [f"SELECT * FROM {LEGAL} LIMIT 5"]


def test_insufficient_verdict_means_need_more():
    # «INSUFFICIENT» содержит подстроку «sufficient» — вердикт обязан быть
    # need_more (регресс: 'suffic' in text давал sufficient).
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content="Данных мало: INSUFFICIENT"),            # судья
        AIMessage(content='["SELECT column_2 FROM %s"]' % LEGAL),  # ещё раунд
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Ответ."),
    ])
    exe = FakeExecutor(results=[_sample(), _rows(1), _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"
    assert len(exe.calls) == 3


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


def test_executor_exception_becomes_failed_attempt():
    # Неожиданное исключение исполнителя не роняет граф — становится
    # неуспешной попыткой (gather(return_exceptions=True)).
    class BoomExecutor(FakeExecutor):
        async def run_select(self, sql, table):
            self.calls.append(sql)
            raise RuntimeError("connection refused")

    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_2 FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT column_3 FROM %s"]' % LEGAL),
    ])
    exe = BoomExecutor(results=[])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "error"
    assert "connection refused" in out["answer"]


def test_structured_output_path_used_when_supported():
    from fakes import StructuredScriptedChatModel
    from toast.sql_graph import SqlCandidates

    model = StructuredScriptedChatModel(responses=[
        SqlCandidates(candidates=["SELECT column_1 FROM %s" % LEGAL]),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Ответ."),
    ])
    exe = FakeExecutor(results=[_sample(), _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"
    assert exe.calls[1:] == ["SELECT column_1 FROM %s" % LEGAL]


def test_candidates_run_in_parallel_batch():
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s","SELECT column_2 FROM %s"]' % (LEGAL, LEGAL)),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="ok"),
    ])
    exe = FakeExecutor(results=[_sample(), _rows(1), _rows(1)])
    out = _run(model, exe, candidates=2, max_queries=3)
    assert out["status"] == "ok"
    assert len(exe.calls) == 3


def test_input_schema_exposes_five_fields():
    from toast.sql_graph import SqlToolInput

    keys = set(SqlToolInput.__annotations__)
    assert keys == {"question", "chunk_id", "table", "desc_vector", "desc_full"}


def test_state_has_defaults_instead_of_init():
    from toast.sql_graph import SqlToolState

    assert "columns" not in SqlToolState.model_fields
    state = SqlToolState(question="q", chunk_id="c", table="t",
                         desc_vector="v", desc_full="f")
    assert state.attempts == [] and state.executed_count == 0 and state.round == 0


def test_rows_context_caps_by_size():
    from toast.sql_graph import JUDGE_CONTEXT_CHARS, _rows_context

    big = {"column_1": "x" * JUDGE_CONTEXT_CHARS}
    small = {"column_1": "y"}
    ctx = _rows_context([], [big, small])
    assert "Показано строк: 1 из 2" in ctx
    assert '"y"' not in ctx

    # Хотя бы одна строка отдаётся всегда, даже если сама больше лимита.
    ctx_one = _rows_context([], [big])
    assert "Показано строк: 1 из 1" in ctx_one


def test_attempt_from_refusal_result_and_exception():
    from toast.sql_graph import _attempt

    ref = _attempt("SELECT 1", "Отказ: только чтение")
    assert ref == {"sql": "SELECT 1", "ok": False, "error": "Отказ: только чтение",
                   "rows": [], "row_count": 0, "truncated": False}

    ok = _attempt("SELECT 2",
                  {"rows": [{"a": 1}], "row_count": 1, "truncated": False})
    assert ok == {"sql": "SELECT 2", "ok": True, "error": None,
                  "rows": [{"a": 1}], "row_count": 1, "truncated": False}

    boom = _attempt("SELECT 3", RuntimeError("boom"))
    assert boom["ok"] is False and "boom" in boom["error"]
