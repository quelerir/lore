"""Regression tests for code-review findings H1 (sibling cap) and H2 (conflict)."""
from lore_retrieval.contracts import SQLResult, SQLStatus
from lore_retrieval.fakes import FakeChatModel, InMemoryGraphExpansion
from lore_retrieval.pipeline.arbitration import arbitrate_and_answer
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import SourceChunk


def _chunk(cid, ordinal, path):
    return SourceChunk(
        chunk_id=cid, document_id="d", run_id="d", chunk_type="text", position=ordinal,
        heading_path=tuple(path), vector_text=cid, fulltext=cid,
        vector_text_hash="h", fulltext_hash="h",
    )


async def test_H1_sibling_cap_holds_when_seed_is_a_later_chunk():
    # Section S has 5 chunks; seed is the last, outside the first max_siblings+1.
    corpus = [_chunk("c0", 0, ("Root",))] + [
        _chunk(f"c{i}", i, ("Root", "S")) for i in range(1, 6)
    ]
    expansion = InMemoryGraphExpansion(build_structural_projection(corpus))
    out = await expansion.expand(["c5"], max_siblings=2, max_next=0, parent_ascent=0)
    section_children = [c for c in out if c.route.value == "section_child"]
    assert len(section_children) == 2   # was 3 before the fix (off-by-one)


def _ok(payload_id, chunk_id, *, summary=None, rows=None):
    return SQLResult(payload_id=payload_id, chunk_id=chunk_id, status=SQLStatus.success,
                     answer_summary=summary, rows=rows or [])


async def test_H2_conflict_detected_when_summaries_are_none_but_rows_differ():
    model = FakeChatModel()
    results = [_ok("p1", "t1", rows=[{"n": 42}]), _ok("p2", "t2", rows=[{"n": 99}])]
    decision = await arbitrate_and_answer(model, "сколько?", [], results)
    assert decision.note == "conflicting_sql_results"   # was silently collapsed to {None}


async def test_H2_no_false_conflict_for_single_success():
    model = FakeChatModel()
    decision = await arbitrate_and_answer(model, "сколько?", [], [_ok("p1", "t1", summary="42")])
    assert decision.note is None
