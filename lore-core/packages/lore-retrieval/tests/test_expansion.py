import pytest

from lore_retrieval.contracts import FanoutResult, Route
from lore_retrieval.fakes import InMemoryGraphExpansion
from lore_retrieval.pipeline.expansion import expand_from_fanout
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import SourceChunk


def mk(cid, ordinal, path):
    return SourceChunk(
        chunk_id=cid, document_id="d", run_id="d", chunk_type="text", position=ordinal,
        heading_path=tuple(path), vector_text=cid, fulltext=cid,
        vector_text_hash="h", fulltext_hash="h",
    )


@pytest.fixture
def expansion():
    corpus = [
        mk("c0", 0, ("Root",)),
        mk("c1", 1, ("Root", "Child")),
        mk("c2", 2, ("Root", "Child")),
        mk("c3", 3, ("Root", "Child")),
        mk("c4", 4, ("Root", "Other")),
        mk("c5", 5, ("Root", "Child")),   # same section, non-adjacent to c2
    ]
    return InMemoryGraphExpansion(build_structural_projection(corpus))


async def test_expand_discovers_next_siblings_and_parent(expansion):
    out = await expansion.expand(["c2"])
    routes = {c.chunk_id: c.route for c in out}
    assert routes["c1"] is Route.next_neighbor    # previous
    assert routes["c3"] is Route.next_neighbor    # next
    assert routes["c5"] is Route.section_child     # sibling, not adjacent
    assert routes["c0"] is Route.section_parent    # one-level parent ascent
    assert "c2" not in routes                       # the seed itself is never re-emitted


async def test_expansion_is_bounded_and_carries_path(expansion):
    out = await expansion.expand(["c2"], max_siblings=1, parent_ascent=0)
    # parent ascent disabled -> no parent chunk
    assert all(c.route is not Route.section_parent for c in out)
    child = next(c for c in out if c.chunk_id == "c1")
    assert child.structural_path_summary == "Root/Child"


async def test_expand_from_fanout_uses_top_seeds(expansion):
    fanout = FanoutResult(per_route=[], fused=[("c2", 0.9), ("c9", 0.1)])
    out = await expand_from_fanout(expansion, fanout, seed_count=1)
    ids = {c.chunk_id for c in out}
    assert "c3" in ids and "c1" in ids            # neighbours of the single seed c2
