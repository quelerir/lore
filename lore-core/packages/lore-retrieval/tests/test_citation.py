from lore_retrieval.contracts import EvidenceEnvelope
from lore_retrieval.pipeline.citation import build_citations, build_deep_link


def env(chunk_id, run_id="run-1", display="текст источника", heading=("Root", "Раздел")):
    return EvidenceEnvelope(
        chunk_id=chunk_id, fulltext=display, display_text=display,
        coordinates={"heading_path": list(heading)}, payload_refs=[],
        run_id=run_id, index_version="spike1", fulltext_hash="fh",
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


def test_non_provided_marker_is_ignored():
    # [9] was never shown to the model -> no invented source.
    cites = build_citations("вывод [9]", {1: ["c1"]}, ENV_BY_CHUNK, FILE_KEY_BY_RUN)
    assert cites == []


def test_dedup_by_chunk_and_marker_order():
    ans = "утверждение [2] и ещё [1] и снова [2]."
    cites = build_citations(ans, {1: ["c1"], 2: ["c2"]}, ENV_BY_CHUNK, FILE_KEY_BY_RUN)
    assert [c.chunk_id for c in cites] == ["c2", "c1"]   # first-appearance order, deduped


def test_no_markers_gives_no_citations():
    assert build_citations("ответ без ссылок", {1: ["c1"]}, ENV_BY_CHUNK, FILE_KEY_BY_RUN) == []


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
