from lore_retrieval.contracts import AgentDecision, Citation, TableCandidate


def test_citation_defaults_are_backward_compatible():
    c = Citation(
        chunk_id="c1", run_id="r1", logical_file_key="f", preview_text="p",
        heading_path=(), deep_link="/files?...",
    )
    assert c.kind == "text"
    assert c.marker is None


def test_citation_accepts_table_kind_and_marker():
    c = Citation(
        chunk_id="c1", run_id="r1", logical_file_key="f", preview_text="p",
        heading_path=(), deep_link="/files?...&tab=payloads", kind="table", marker=3,
    )
    assert c.kind == "table"
    assert c.marker == 3


def test_agent_decision_sql_evidence_map_defaults_empty():
    d = AgentDecision(
        answer="a", used_evidence_chunk_ids=[], used_sql_payload_ids=[], citations=[],
    )
    assert d.sql_evidence_map == {}


def test_table_candidate_carries_optional_provenance():
    tc = TableCandidate(chunk_id="c1", payload_id="p1", score=1.0)
    assert tc.run_id == "" and tc.heading_path == ()
    tc2 = TableCandidate(
        chunk_id="c1", payload_id="p1", score=1.0, run_id="r1", heading_path=("H",),
    )
    assert tc2.run_id == "r1" and tc2.heading_path == ("H",)
