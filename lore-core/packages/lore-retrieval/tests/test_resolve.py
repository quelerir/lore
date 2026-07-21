import pytest

from lore_retrieval.fakes import InMemoryEvidenceResolver
from lore_retrieval.pipeline.resolve import resolve_evidence
from lore_retrieval.source import SourceChunk


def mk(cid, ctype="text"):
    return SourceChunk(
        chunk_id=cid, document_id="d", run_id="run-1", chunk_type=ctype, position=0,
        heading_path=("Root",), vector_text=f"vt {cid}", fulltext=f"ft {cid}",
        display_text=f"dt {cid}", coordinates={"heading_path": ["Root"]},
        payload_refs=[{"payload_id": "p1"}] if ctype == "table_payload" else [],
        vector_text_hash="vh", fulltext_hash="fh",
    )


@pytest.fixture
def corpus():
    return [mk("c1"), mk("c2"), mk("t1", "table_payload")]


async def test_resolves_valid_chunks_with_lineage(corpus):
    resolver = InMemoryEvidenceResolver(corpus)
    res = await resolve_evidence(resolver, ["c1", "t1"], index_version="spike1")
    assert [e.chunk_id for e in res.resolved] == ["c1", "t1"]
    assert res.rejected == []
    t1 = next(e for e in res.resolved if e.chunk_id == "t1")
    assert t1.payload_refs == [{"payload_id": "p1"}]      # SQL lineage carried
    assert t1.display_text == "dt t1"


async def test_rejects_missing(corpus):
    resolver = InMemoryEvidenceResolver(corpus)
    res = await resolve_evidence(resolver, ["nope"], index_version="spike1")
    assert res.resolved == []
    assert res.rejected == [("nope", "missing")]


async def test_rejects_wrong_version(corpus):
    resolver = InMemoryEvidenceResolver(corpus, active_index_version="spike1")
    res = await resolve_evidence(resolver, ["c1"], index_version="OLD")
    assert res.rejected == [("c1", "wrong_version")]


async def test_rejects_superseded_and_hash_mismatch(corpus):
    resolver = InMemoryEvidenceResolver(
        corpus, superseded=frozenset({"c1"}), hash_mismatch=frozenset({"c2"})
    )
    res = await resolve_evidence(resolver, ["c1", "c2"], index_version="spike1")
    assert res.resolved == []
    assert set(res.rejected) == {("c1", "superseded"), ("c2", "hash_mismatch")}
