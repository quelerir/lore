import pytest

from lore_retrieval.pipeline.grouping import build_context_groups
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import SourceChunk


def mk(cid, ordinal, path):
    return SourceChunk(
        chunk_id=cid, document_id="d", run_id="d", chunk_type="text", position=ordinal,
        heading_path=tuple(path), vector_text=cid, fulltext=cid,
        vector_text_hash="h", fulltext_hash="h",
    )


@pytest.fixture
def ctx():
    corpus = [
        mk("c0", 0, ("Root",)),
        mk("c1", 1, ("Root", "Child")),
        mk("c2", 2, ("Root", "Child")),
        mk("c3", 3, ("Root", "Child")),
        mk("c4", 4, ("Root", "Other")),
    ]
    projection = build_structural_projection(corpus)
    positions = {c.chunk_id: c.position for c in corpus}
    text_by_id = {c.chunk_id: f"текст {c.chunk_id}" for c in corpus}
    return projection, positions, text_by_id


def test_adjacent_hits_merge_into_one_window(ctx):
    projection, positions, text = ctx
    groups = build_context_groups([("c1", 5.0), ("c2", 4.0)], projection, positions, text)
    assert len(groups) == 1
    g = groups[0]
    assert g.chunk_ids == ["c1", "c2"] and g.scope == "window"
    assert g.citations == ["c1", "c2"]                 # every contributing chunk cited
    assert g.text == "текст c1 текст c2"


def test_full_section_coverage_promotes_to_section_scope(ctx):
    projection, positions, text = ctx
    groups = build_context_groups(
        [("c1", 5.0), ("c2", 4.0), ("c3", 3.0)], projection, positions, text
    )
    assert len(groups) == 1
    assert groups[0].scope == "section"
    assert groups[0].chunk_ids == ["c1", "c2", "c3"]


def test_distant_hits_in_different_sections_stay_separate(ctx):
    projection, positions, text = ctx
    groups = build_context_groups([("c1", 5.0), ("c4", 4.0)], projection, positions, text)
    assert len(groups) == 2
    assert {g.section_path for g in groups} == {("Root", "Child"), ("Root", "Other")}


def test_gap_larger_than_budget_splits_runs(ctx):
    projection, positions, text = ctx
    # c1 and c3 with a chunk (c2) between them; max_gap=0 forbids the gap.
    groups = build_context_groups(
        [("c1", 5.0), ("c3", 3.0)], projection, positions, text, max_gap=0
    )
    assert len(groups) == 2
    # c1 and c3 with max_gap=1 merges into one window that fills c2.
    merged = build_context_groups(
        [("c1", 5.0), ("c3", 3.0)], projection, positions, text, max_gap=1
    )
    assert len(merged) == 1 and merged[0].chunk_ids == ["c1", "c2", "c3"]


def test_char_budget_truncates_with_reason(ctx):
    projection, positions, text = ctx
    groups = build_context_groups(
        [("c1", 5.0), ("c2", 4.0)], projection, positions, text, group_char_budget=5
    )
    assert groups[0].truncation_reason == "char_budget"
    assert len(groups[0].text) == 5
