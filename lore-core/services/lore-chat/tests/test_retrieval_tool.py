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
    assert "result" not in container  # nothing captured on failure


def test_metadata_carries_citations_snake_case():
    md = to_message_metadata(_result("a", [_citation()]))
    assert [c["chunk_id"] for c in md["citations"]] == ["c1"]
    assert md["citations"][0]["deep_link"].startswith("/files?")
