"""Property-based invariants for the pure cores (hypothesis)."""
from hypothesis import given
from hypothesis import strategies as st

from lore_retrieval.contracts import EvidenceEnvelope
from lore_retrieval.identity import section_id, section_prefixes
from lore_retrieval.neo4j_spike import rrf_fuse
from lore_retrieval.pipeline.citation import build_citations
from lore_retrieval.projection_model import build_structural_projection, validate_projection
from lore_retrieval.source import SourceChunk

_ids = st.text("abcde", min_size=1, max_size=3)
_headings = st.lists(st.text("XYZ", min_size=1, max_size=2), max_size=3).map(tuple)


# --- identity ---------------------------------------------------------------

@given(_headings)
def test_section_prefixes_are_real_prefixes(path):
    prefixes = section_prefixes(path)
    assert len(prefixes) == len(path)
    for i, p in enumerate(prefixes):
        assert p == tuple(path[: i + 1])


@given(st.text(min_size=1, max_size=6), _headings)
def test_section_id_is_deterministic(doc, path):
    assert section_id(doc, path) == section_id(doc, path)


# --- RRF fusion -------------------------------------------------------------

@given(st.lists(st.lists(st.tuples(_ids, st.floats(0, 1)), max_size=6), max_size=4))
def test_rrf_dedups_and_preserves_union(routes):
    fused = rrf_fuse(routes)
    ids = [cid for cid, _ in fused]
    assert len(ids) == len(set(ids))                      # deduped
    assert set(ids) == {cid for r in routes for cid, _ in r}   # union preserved
    scores = [s for _, s in fused]
    assert scores == sorted(scores, reverse=True)          # ranked


# --- structural projection --------------------------------------------------

@st.composite
def _corpus(draw):
    n = draw(st.integers(min_value=1, max_value=8))
    paths = draw(st.lists(_headings, min_size=n, max_size=n))
    return [
        SourceChunk(
            chunk_id=f"c{i}", document_id="d", run_id="d", chunk_type="text", position=i,
            heading_path=paths[i], vector_text="v", fulltext="f",
            vector_text_hash="h", fulltext_hash="h",
        )
        for i in range(n)
    ]


@given(_corpus())
def test_projection_always_satisfies_invariants(corpus):
    projection = build_structural_projection(corpus)
    assert validate_projection(projection, corpus) is True


# --- citations --------------------------------------------------------------

@given(
    st.dictionaries(st.integers(1, 5), st.lists(_ids, min_size=1, max_size=3), max_size=5),
    st.lists(st.integers(1, 9), max_size=8),
)
def test_citations_never_invent_sources(evidence_map, marker_indices):
    answer = " ".join(f"[{i}]" for i in marker_indices)
    provided = {cid for ids in evidence_map.values() for cid in ids}
    env_by_chunk = {
        cid: EvidenceEnvelope(
            chunk_id=cid, fulltext="t", display_text="t", coordinates={}, payload_refs=[],
            run_id="r", index_version="v", fulltext_hash="h",
        )
        for cid in provided
    }
    cites = build_citations(answer, evidence_map, env_by_chunk, {}, limit=8)
    cited = [c.chunk_id for c in cites]
    assert all(c in provided for c in cited)      # only provided evidence
    assert len(cited) == len(set(cited))           # deduped
    assert len(cited) <= 8                          # capped
