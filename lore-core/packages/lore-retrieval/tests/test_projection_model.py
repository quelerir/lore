"""P1 core (Neo4j-independent): deterministic Section/NEXT structural derivation.

Tests encode the spec's 8 projection invariants over pure in-memory structures,
so the structural projection is proven before it is ever written to Neo4j.
"""
import pytest

from lore_retrieval.projection_model import (
    build_structural_projection,
    validate_projection,
)
from lore_retrieval.source import SourceChunk


def mk(cid, doc, ordinal, path, ctype="text"):
    return SourceChunk(
        chunk_id=cid,
        document_id=doc,
        run_id=doc,
        chunk_type=ctype,
        position=ordinal,
        heading_path=tuple(path),
        vector_text=f"vt {cid}",
        fulltext=f"ft {cid}",
        vector_text_hash="vh",
        fulltext_hash="fh",
    )


@pytest.fixture
def corpus():
    # Document d1: a real heading tree with a split continuation, a sibling,
    # and a table anchor. Document d2: a single empty-heading chunk (synthetic root).
    return [
        mk("c0", "d1", 0, ("Root",)),
        mk("c1", "d1", 1, ("Root", "Child")),
        mk("c2", "d1", 2, ("Root", "Child")),                 # split continuation of c1
        mk("c3", "d1", 3, ("Root", "Other")),                 # sibling section
        mk("c4", "d1", 4, ("Root", "Child"), "table_payload"),  # table anchor in Child
        mk("c5", "d2", 0, ()),                                # empty heading -> synthetic root
    ]


def _sections_of(proj, doc):
    return [s for s in proj.sections if s.document_id == doc]


def _by_path(proj, doc, path):
    return next(s for s in proj.sections if s.document_id == doc and s.heading_path == tuple(path))


def test_every_prefix_maps_to_exactly_one_section(corpus):
    # Invariant 2 + 6: unique section per heading-path prefix; siblings not merged.
    proj = build_structural_projection(corpus)
    d1_paths = sorted(s.heading_path for s in _sections_of(proj, "d1"))
    assert d1_paths == [("Root",), ("Root", "Child"), ("Root", "Other")]
    # d2 has one synthetic root section
    assert [s.heading_path for s in _sections_of(proj, "d2")] == [()]


def test_chunk_attaches_to_deepest_matching_section(corpus):
    # Invariant 4 + 5: structurally compatible members; split continuations share a section.
    proj = build_structural_projection(corpus)
    child = _by_path(proj, "d1", ("Root", "Child"))
    assert set(child.chunk_ids) == {"c1", "c2", "c4"}          # c1,c2 continuation; c4 table anchor
    assert _by_path(proj, "d1", ("Root",)).chunk_ids == ["c0"]
    assert _by_path(proj, "d1", ("Root", "Other")).chunk_ids == ["c3"]
    assert _by_path(proj, "d2", ()).chunk_ids == ["c5"]


def test_table_anchor_kept_as_its_own_chunk(corpus):
    # Invariant 8: the table_payload anchor is a distinct member, not dropped/merged away.
    proj = build_structural_projection(corpus)
    child = _by_path(proj, "d1", ("Root", "Child"))
    assert "c4" in child.chunk_ids
    assert proj.chunk_section["c4"] == child.section_id


def test_parent_edges_reproduce_heading_prefix_order(corpus):
    # Invariant 3: parent is the section one heading-prefix shorter; depth-1 -> Document (None).
    proj = build_structural_projection(corpus)
    root = _by_path(proj, "d1", ("Root",))
    child = _by_path(proj, "d1", ("Root", "Child"))
    assert root.parent_section_id is None                      # top-level -> Document
    assert child.parent_section_id == root.section_id
    assert child.depth == 2 and root.depth == 1


def test_next_edges_are_consecutive_within_document_only(corpus):
    # Invariant 1 + 7: NEXT never crosses documents; follows unique ordered positions.
    proj = build_structural_projection(corpus)
    assert proj.next_edges == [
        ("c0", "c1"), ("c1", "c2"), ("c2", "c3"), ("c3", "c4"),
    ]
    # no edge touches d2's chunk
    assert all("c5" not in edge for edge in proj.next_edges)


def test_validate_passes_on_well_formed_projection(corpus):
    proj = build_structural_projection(corpus)
    assert validate_projection(proj, corpus) is True


def test_validate_rejects_duplicate_positions_in_document():
    # Invariant 7: positions must be unique within a document.
    bad = [mk("a", "d1", 0, ("Root",)), mk("b", "d1", 0, ("Root",))]
    proj = build_structural_projection(bad)
    with pytest.raises(ValueError, match="unique"):
        validate_projection(proj, bad)
