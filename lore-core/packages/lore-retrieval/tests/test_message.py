from lore_retrieval.contracts import AgentDecision, Citation, PipelineResult
from lore_retrieval.pipeline.message import to_message_metadata


def _result(citations, *, note=None, degradations=None):
    return PipelineResult(
        decision=AgentDecision(
            answer="a", used_evidence_chunk_ids=[], used_sql_payload_ids=[], citations=[], note=note
        ),
        groups=[], sql_results=[], table_candidates=[], citations=citations,
        degradations=degradations or [],
    )


def _cite(chunk_id="c1"):
    return Citation(
        chunk_id=chunk_id, run_id="r1", logical_file_key="m.pdf", preview_text="p",
        heading_path=("Root",), deep_link=f"/files?file=m.pdf&run=r1&chunk={chunk_id}&tab=display",
    )


def test_metadata_carries_snake_case_citations():
    meta = to_message_metadata(_result([_cite("c1")]))
    assert list(meta) == ["citations"]
    c = meta["citations"][0]
    assert c["chunk_id"] == "c1"
    assert c["deep_link"].startswith("/files?file=m.pdf")
    assert "debug" not in meta


def test_no_citations_is_empty_list():
    assert to_message_metadata(_result([])) == {"citations": []}


def test_include_debug_adds_gated_fields():
    meta = to_message_metadata(
        _result([_cite()], note="conflicting_sql_results", degradations=["table_lane_unavailable"]),
        include_debug=True,
    )
    assert meta["debug"]["note"] == "conflicting_sql_results"
    assert meta["debug"]["degradations"] == ["table_lane_unavailable"]
