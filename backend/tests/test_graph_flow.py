from langchain_core.messages import AIMessage

from fakes import ScriptedChatModel
from graph_utils import (
    LEGAL, FakeExecutor, _rows, _run, _sample,
)
from toast.models import DbError



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



def test_sample_failure_is_not_fatal():
    # Отказ/ошибка сэмпла не роняет граф и не мешает ответу.
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT column_1 FROM %s"]' % LEGAL),
        AIMessage(content="SUFFICIENT"),
        AIMessage(content="Ответ."),
    ])
    exe = FakeExecutor(results=[DbError("Ошибка SQL: сеть"), _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"



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



def test_all_sql_errors_status_error():
    model = ScriptedChatModel(responses=[
        AIMessage(content='["SELECT bad FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT worse FROM %s"]' % LEGAL),
        AIMessage(content='["SELECT nope FROM %s"]' % LEGAL),
    ])
    exe = FakeExecutor(results=[_sample(), DbError("Ошибка SQL: a"), DbError("Ошибка SQL: b"), DbError("Ошибка SQL: c")])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "error"



def test_input_schema_exposes_five_fields():
    from toast.models import SqlToolInput

    keys = set(SqlToolInput.__annotations__)
    assert keys == {"question", "chunk_id", "table", "desc_vector", "desc_full"}



def test_state_has_defaults_instead_of_init():
    from toast.models import SqlToolState

    assert "columns" not in SqlToolState.model_fields
    state = SqlToolState(question="q", chunk_id="c", table="t",
                         desc_vector="v", desc_full="f")
    assert state.attempts == [] and state.executed_count == 0 and state.round == 0
