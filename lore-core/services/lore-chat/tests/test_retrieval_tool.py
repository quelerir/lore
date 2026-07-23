"""knowledge_base tool: grounded answer, turn capture, soft failure, metadata."""
import asyncio

import retrieval
from lore_retrieval.contracts import AgentDecision, Citation, PipelineResult
from lore_retrieval.pipeline.message import to_message_metadata


def _result(answer="ответ [1]", citations=None):
    return PipelineResult(
        decision=AgentDecision(
            answer=answer, used_evidence_chunk_ids=[], used_sql_payload_ids=[], citations=[]
        ),
        groups=[],
        sql_results=[],
        table_candidates=[],
        citations=citations or [],
    )


def _citation():
    return Citation(
        chunk_id="c1", run_id="r1", logical_file_key="doc",
        preview_text="превью", heading_path=("Раздел",),
        deep_link="/files?file=doc&run=r1&chunk=c1&tab=display",
    )


class _FakePipeline:
    def __init__(self, result=None, boom=False):
        self._result = result
        self._boom = boom

    async def answer(self, query):
        if self._boom:
            raise RuntimeError("knowledge base down")
        return self._result


def test_tool_returns_grounded_answer_and_captures_result(monkeypatch):
    res = _result("ответ на основе базы [1]", [_citation()])
    monkeypatch.setattr(retrieval, "_pipeline", _FakePipeline(res))
    container: dict = {}
    token = retrieval.turn_capture.set(container)
    try:
        out = asyncio.run(retrieval.knowledge_base.ainvoke({"query": "как оформить?"}))
    finally:
        retrieval.turn_capture.reset(token)
    assert out == "ответ на основе базы [1]"
    assert container["result"] is res  # captured for on_message to attach metadata


def test_tool_soft_fails_without_capturing(monkeypatch):
    monkeypatch.setattr(retrieval, "_pipeline", _FakePipeline(boom=True))
    container: dict = {}
    token = retrieval.turn_capture.set(container)
    try:
        out = asyncio.run(retrieval.knowledge_base.ainvoke({"query": "вопрос"}))
    finally:
        retrieval.turn_capture.reset(token)
    assert "базе знаний" in out  # honest failure message names the KB
    # Must NOT invite the model to answer from general/parametric knowledge — that
    # is exactly the grounding-violation bug (defect #1). It must steer AWAY:
    # the old inviting phrasing is gone, and it explicitly forbids parametric answers.
    assert "ответь по общ" not in out.lower()  # no "ответь по общим знаниям" invite
    assert "не отвечай из общих знаний" in out.lower()  # explicit prohibition
    assert "result" not in container  # no grounded result captured on failure
    # But the failure IS recorded as a degradation so on_message surfaces a
    # deterministic error banner (not left to the LLM to mention). DEEP mode has
    # no other signal — the tool returns text the model then paraphrases.
    assert "knowledge_base_unavailable" in container.get("degradations", [])


def test_optional_langfuse_tracer_survives_missing_module(monkeypatch):
    """Optional observability must NEVER sink the pipeline build. A missing/broken
    langfuse_tracing must degrade to 'no tracer', not raise ModuleNotFoundError —
    which is exactly what silently downgraded the whole grounded session."""
    import sys

    import retrieval

    # Simulate the module being absent in the deployed image (sys.modules[x]=None
    # makes `import x` raise ImportError).
    monkeypatch.setitem(sys.modules, "langfuse_tracing", None)
    assert retrieval._optional_langfuse_tracer() is None  # degrades, does not raise


def test_metadata_carries_citations_snake_case():
    md = to_message_metadata(_result("a", [_citation()]))
    assert [c["chunk_id"] for c in md["citations"]] == ["c1"]
    assert md["citations"][0]["deep_link"].startswith("/files?")


def test_build_sql_runner_unavailable_and_loud_when_toast_not_configured(monkeypatch, caplog):
    """When TOAST isn't configured, the SQL runner is the honest Unavailable one
    (never a silent fake) and the reason is logged — not swallowed."""
    import logging

    import toast_binding

    monkeypatch.setattr(toast_binding, "toast_configured", lambda: False)
    with caplog.at_level(logging.WARNING):
        runner = retrieval._build_sql_runner()
    assert type(runner).__name__ == "UnavailableSqlRunner"
    assert "SQL" in caplog.text or "TOAST" in caplog.text


def test_build_sql_runner_unavailable_and_logged_when_wiring_raises(monkeypatch, caplog):
    import logging

    import toast_binding

    def _boom():
        raise RuntimeError("toast wiring blew up")

    monkeypatch.setattr(toast_binding, "toast_configured", lambda: True)
    monkeypatch.setattr(toast_binding, "toast_sql_runner", _boom)
    with caplog.at_level(logging.ERROR):
        runner = retrieval._build_sql_runner()
    assert type(runner).__name__ == "UnavailableSqlRunner"
    assert "toast wiring blew up" in caplog.text  # real cause surfaced, not swallowed
