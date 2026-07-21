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
        mk("c1", 1, ("Root", "A")),
        mk("c2", 2, ("Root", "B")),
    ]
    projection = build_structural_projection(corpus)
    positions = {c.chunk_id: c.position for c in corpus}
    text_by_id = {c.chunk_id: f"текст {c.chunk_id}" for c in corpus}
    return projection, positions, text_by_id


def test_hits_in_sibling_sections_promote_to_parent(ctx):
    projection, positions, text = ctx
    groups = build_context_groups(
        [("c1", 5.0), ("c2", 4.0)], projection, positions, text, promote_parents=True
    )
    assert len(groups) == 1
    g = groups[0]
    assert g.scope == "parent_section"
    assert g.section_path == ("Root",)
    assert g.chunk_ids == ["c0", "c1", "c2"]
    assert set(g.citations) == {"c1", "c2"}


def test_promotion_disabled_keeps_child_groups(ctx):
    projection, positions, text = ctx
    groups = build_context_groups(
        [("c1", 5.0), ("c2", 4.0)], projection, positions, text, promote_parents=False
    )
    assert len(groups) == 2
    assert all(g.scope != "parent_section" for g in groups)   # kept as separate child groups


def test_promotion_skipped_when_over_budget(ctx):
    projection, positions, text = ctx
    groups = build_context_groups(
        [("c1", 5.0), ("c2", 4.0)], projection, positions, text,
        promote_parents=True, parent_char_budget=3,
    )
    assert len(groups) == 2                    # doesn't fit -> smaller child groups kept
    assert all(g.scope != "parent_section" for g in groups)
