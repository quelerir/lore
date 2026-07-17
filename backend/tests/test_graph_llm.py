from langchain_core.messages import AIMessage

from fakes import ScriptedChatModel
from graph_utils import (
    LEGAL, FakeExecutor, _rows, _run, _sample,
)
from toast.models import Refusal



def test_structured_output_path_used_when_supported():
    from fakes import StructuredScriptedChatModel
    from toast.models import JudgeVerdict, SqlCandidates

    model = StructuredScriptedChatModel(responses=[
        SqlCandidates(candidates=["SELECT column_1 FROM %s" % LEGAL]),
        JudgeVerdict(sufficient=True, reason="ок"),  # судья тоже structured
        AIMessage(content="Ответ."),
    ])
    exe = FakeExecutor(results=[_sample(), _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"
    assert exe.calls[1:] == ["SELECT column_1 FROM %s" % LEGAL]



def test_judge_reason_feeds_next_generate_prompt():
    from fakes import StructuredScriptedChatModel
    from toast.models import JudgeVerdict, SqlCandidates

    captured: list[str] = []

    class CapturingModel(StructuredScriptedChatModel):
        def with_structured_output(self, schema, **kwargs):
            model = self

            class _S:
                async def ainvoke(self, messages, config=None):
                    captured.append("\n".join(str(m.content) for m in messages))
                    return model.responses.pop(0)

            return _S()

    model = CapturingModel(responses=[
        SqlCandidates(candidates=["SELECT column_1 FROM %s" % LEGAL]),
        JudgeVerdict(sufficient=False, reason="строки не про юристов"),
        SqlCandidates(candidates=["SELECT column_2 FROM %s" % LEGAL]),
        JudgeVerdict(sufficient=True, reason="ок"),
        AIMessage(content="Ответ."),
    ])
    exe = FakeExecutor(results=[_sample(), _rows(1), _rows(1)])
    out = _run(model, exe, candidates=1, max_queries=3)
    assert out["status"] == "ok"
    # причина судьи попала в промпт ВТОРОГО generate (порядок structured-
    # вызовов в captured: generate, judge, generate, judge)
    assert "строки не про юристов" in captured[2]



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



def test_parse_candidates_multiline_sql_fallback():
    from toast.llm import parse_sql_candidates

    text = ("SELECT column_1,\n       column_2\n"
            "FROM splitter_toast.%s\nWHERE column_2 IS NOT NULL" % LEGAL)
    out = parse_sql_candidates(text, 2)
    assert len(out) == 1
    assert "column_2" in out[0] and "WHERE" in out[0]



def test_attempt_from_refusal_result_and_exception():
    from toast.models import make_attempt

    ref = make_attempt("SELECT 1", Refusal("Отказ: только чтение"))
    assert ref == {"sql": "SELECT 1", "ok": False, "error": "Отказ: только чтение",
                   "rows": [], "row_count": 0, "truncated": False}

    ok = make_attempt("SELECT 2",
                  {"rows": [{"a": 1}], "row_count": 1, "truncated": False})
    assert ok == {"sql": "SELECT 2", "ok": True, "error": None,
                  "rows": [{"a": 1}], "row_count": 1, "truncated": False}

    boom = make_attempt("SELECT 3", RuntimeError("boom"))
    assert boom["ok"] is False and "boom" in boom["error"]
