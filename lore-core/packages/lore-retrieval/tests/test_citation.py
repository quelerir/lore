from lore_retrieval.contracts import (
    EvidenceEnvelope,
    SQLResult,
    SQLStatus,
    TableCandidate,
)
from lore_retrieval.pipeline.citation import build_citations, build_deep_link


def env(chunk_id, run_id="run-1", display="текст источника", heading=("Root", "Раздел")):
    return EvidenceEnvelope(
        chunk_id=chunk_id, fulltext=display, display_text=display,
        coordinates={"heading_path": list(heading)}, payload_refs=[],
        run_id=run_id, index_version="spike1", fulltext_hash="fh",
    )


def sql_ok(chunk_id, payload_id, summary):
    return SQLResult(
        payload_id=payload_id, chunk_id=chunk_id, status=SQLStatus.success,
        rows=[{"n": 1}], answer_summary=summary,
    )


ENV_BY_CHUNK = {"c1": env("c1"), "c2": env("c2"), "c3": env("c3", run_id="run-2")}
FILE_KEY_BY_RUN = {"run-1": "manual.pdf", "run-2": "grades.xlsx"}


def test_deep_link_shape():
    assert build_deep_link("manual.pdf", "run-1", "c1") == (
        "/files?file=manual.pdf&run=run-1&chunk=c1&tab=display"
    )


def test_markers_resolve_in_order_with_file_key_and_link():
    ans = "Премия зависит от оклада [1], а грейд из таблицы [2]."
    cites = build_citations(ans, {1: ["c1"], 2: ["c3"]}, ENV_BY_CHUNK, FILE_KEY_BY_RUN)
    assert [c.chunk_id for c in cites] == ["c1", "c3"]
    assert cites[0].logical_file_key == "manual.pdf"
    assert cites[0].heading_path == ("Root", "Раздел")
    assert cites[1].deep_link == "/files?file=grades.xlsx&run=run-2&chunk=c3&tab=display"


def test_non_provided_marker_ignored_then_fallback_uses_provided_evidence():
    # [9] was never shown -> not cited; the deterministic fallback surfaces the
    # provided top evidence instead (marker=None), so a grounded answer isn't
    # left source-less.
    cites = build_citations("вывод [9]", {1: ["c1"]}, ENV_BY_CHUNK, FILE_KEY_BY_RUN)
    assert [c.chunk_id for c in cites] == ["c1"]
    assert cites[0].marker is None


def test_dedup_by_chunk_and_marker_order():
    ans = "утверждение [2] и ещё [1] и снова [2]."
    cites = build_citations(ans, {1: ["c1"], 2: ["c2"]}, ENV_BY_CHUNK, FILE_KEY_BY_RUN)
    assert [c.chunk_id for c in cites] == ["c2", "c1"]   # first-appearance order, deduped


def test_no_markers_falls_back_to_top_n():
    # Grounding existed but the model cited nothing -> top-N fallback (marker=None).
    cites = build_citations("ответ без ссылок", {1: ["c1"]}, ENV_BY_CHUNK, FILE_KEY_BY_RUN)
    assert [c.chunk_id for c in cites] == ["c1"]
    assert cites[0].marker is None


def test_no_grounding_yields_no_citations():
    assert build_citations("ничего", {}, {}, {}) == []


def test_table_marker_builds_table_citation_with_payloads_tab():
    citations = build_citations(
        "Ответ [2].",
        {1: ["c1"]},
        {"c1": env("c1"), "a1": env("a1")},
        {"run-1": "docs/file.xlsx"},
        sql_evidence_map={2: "a1"},
        sql_result_by_chunk={"a1": sql_ok("a1", "p1", "Итог: 42")},
        table_candidate_by_chunk={"a1": TableCandidate(
            chunk_id="a1", payload_id="p1", score=1.0, run_id="run-1",
            heading_path=("H", "a1"),
        )},
    )
    assert len(citations) == 1
    cit = citations[0]
    assert cit.kind == "table"
    assert cit.marker == 2
    assert cit.preview_text == "Итог: 42"
    assert cit.logical_file_key == "docs/file.xlsx"
    assert cit.deep_link.endswith("&tab=payloads")
    assert "chunk=a1" in cit.deep_link


def test_mixed_markers_resolve_in_first_appearance_order():
    citations = build_citations(
        "Сначала [2], затем [1].",
        {1: ["c1"]},
        {"c1": env("c1"), "a1": env("a1")},
        {"run-1": "f"},
        sql_evidence_map={2: "a1"},
        sql_result_by_chunk={"a1": sql_ok("a1", "p1", "s")},
        table_candidate_by_chunk={"a1": TableCandidate(
            chunk_id="a1", payload_id="p1", score=1.0, run_id="run-1")},
    )
    assert [c.kind for c in citations] == ["table", "text"]
    assert [c.marker for c in citations] == [2, 1]


def test_fallback_top_n_shown_order_text_then_sql():
    citations = build_citations(
        "Ответ без маркеров.",
        {1: ["c1"]},
        {"c1": env("c1"), "a1": env("a1")},
        {"run-1": "f"},
        sql_evidence_map={2: "a1"},
        sql_result_by_chunk={"a1": sql_ok("a1", "p1", "s")},
        table_candidate_by_chunk={"a1": TableCandidate(
            chunk_id="a1", payload_id="p1", score=1.0, run_id="run-1")},
        fallback_limit=3,
    )
    assert [c.kind for c in citations] == ["text", "table"]
    assert all(c.marker is None for c in citations)


def test_table_dedup_by_payload_id():
    citations = build_citations(
        "[2] и снова [2].",
        {},
        {"a1": env("a1")},
        {"run-1": "f"},
        sql_evidence_map={2: "a1"},
        sql_result_by_chunk={"a1": sql_ok("a1", "p1", "s")},
        table_candidate_by_chunk={"a1": TableCandidate(
            chunk_id="a1", payload_id="p1", score=1.0, run_id="run-1")},
    )
    assert len(citations) == 1


def test_table_marker_without_provenance_is_skipped():
    # run_id="" -> no valid deep-link -> skip (and no grounding elsewhere -> []).
    citations = build_citations(
        "[1].",
        {},
        {},
        {},
        sql_evidence_map={1: "a1"},
        sql_result_by_chunk={"a1": sql_ok("a1", "p1", "s")},
        table_candidate_by_chunk={"a1": TableCandidate(
            chunk_id="a1", payload_id="p1", score=1.0)},
    )
    assert citations == []


def test_preview_truncated_and_file_key_falls_back_to_run():
    long = env("c1", display="я" * 500)
    cites = build_citations("[1]", {1: ["c1"]}, {"c1": long}, {}, preview_chars=50)
    assert len(cites[0].preview_text) == 50
    assert cites[0].logical_file_key == "run-1"          # unknown run -> run_id fallback


def test_limit_caps_citations():
    emap = {i: [f"c{i}"] for i in range(1, 6)}
    envs = {f"c{i}": env(f"c{i}") for i in range(1, 6)}
    ans = " ".join(f"[{i}]" for i in range(1, 6))
    assert len(build_citations(ans, emap, envs, {}, limit=3)) == 3
