"""Mock-tested Neo4j adapters (code-ahead; live behaviour validated with an instance).

A tiny fake async driver/session records the Cypher + params and returns canned
records, so we lock query construction and result mapping without a real Neo4j.
"""
from lore_retrieval import neo4j_spike
from lore_retrieval.adapters.neo4j_backends import (
    Neo4jChunkSearchBackend,
    Neo4jGraphExpansionBackend,
    Neo4jTableSearchBackend,
)
from lore_retrieval.contracts import Route
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import SourceChunk


class FakeResult:
    def __init__(self, records):
        self._records = records

    def __aiter__(self):
        self._it = iter(self._records)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None


class FakeSession:
    def __init__(self, script=None):
        self.calls = []
        self._script = script or []
        self._i = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def run(self, cypher, **params):
        self.calls.append((cypher, params))
        records = self._script[self._i] if self._i < len(self._script) else []
        self._i += 1
        return FakeResult(records)


class FakeDriver:
    def __init__(self, session):
        self._session = session

    def session(self, database=None):
        return self._session


class FakeEmbedder:
    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


async def test_chunk_vector_search_calls_text_vector_index_and_maps():
    sess = FakeSession(script=[[{"chunk_id": "a", "score": 0.9}, {"chunk_id": "b", "score": 0.5}]])
    backend = Neo4jChunkSearchBackend(FakeDriver(sess), "neo4j", "spike1", FakeEmbedder())
    assert await backend.vector_search("q", 10) == [("a", 0.9), ("b", 0.5)]
    cypher, params = sess.calls[0]
    assert "db.index.vector.queryNodes" in cypher
    assert params["index"] == "vec_TextChunk_spike1" and params["k"] == 10


async def test_table_fulltext_uses_table_index():
    sess = FakeSession(script=[[{"chunk_id": "t1", "score": 2.0}]])
    backend = Neo4jTableSearchBackend(FakeDriver(sess), "neo4j", "spike1", FakeEmbedder())
    assert await backend.table_fulltext_search("q", 5) == [("t1", 2.0)]
    assert sess.calls[0][1]["index"] == "ft_TableChunk_spike1"


async def test_expand_maps_routes_excludes_seed_and_is_parameterized():
    records = [
        {"chunk_id": "n1", "route": "next_neighbor"},
        {"chunk_id": "s1", "route": "section_child"},
        {"chunk_id": "seed", "route": "section_child"},   # seed itself: dropped
        {"chunk_id": "p1", "route": "section_parent"},
    ]
    sess = FakeSession(script=[records])
    backend = Neo4jGraphExpansionBackend(FakeDriver(sess), "neo4j", "spike1")
    out = await backend.expand(["seed"])
    assert {c.chunk_id: c.route for c in out} == {
        "n1": Route.next_neighbor, "s1": Route.section_child, "p1": Route.section_parent,
    }
    cypher, params = sess.calls[0]
    assert "$seed" in cypher and params["seed"] == "seed" and params["max_siblings"] == 3


async def test_expand_respects_parent_ascent_and_max_next_flags():
    records = [
        {"chunk_id": "n1", "route": "next_neighbor"},
        {"chunk_id": "p1", "route": "section_parent"},
    ]
    sess = FakeSession(script=[records])
    backend = Neo4jGraphExpansionBackend(FakeDriver(sess), "neo4j", "spike1")
    out = await backend.expand(["seed"], max_next=0, parent_ascent=0)
    assert out == []                                   # both routes suppressed by flags


async def test_project_structure_writes_sections_edges_and_next():
    corpus = [
        SourceChunk(chunk_id="c0", document_id="d", run_id="d", chunk_type="text", position=0,
                    heading_path=("Root",), vector_text="v", fulltext="f",
                    vector_text_hash="h", fulltext_hash="h"),
        SourceChunk(chunk_id="c1", document_id="d", run_id="d", chunk_type="text", position=1,
                    heading_path=("Root", "Child"), vector_text="v", fulltext="f",
                    vector_text_hash="h", fulltext_hash="h"),
    ]
    proj = build_structural_projection(corpus)
    sess = FakeSession()
    await neo4j_spike.project_structure(FakeDriver(sess), "neo4j", "spike1", proj)
    joined = "\n".join(c for c, _ in sess.calls)
    assert "MERGE (s:Section_spike1" in joined
    assert "HAS_SUBSECTION" in joined
    assert "HAS_CHUNK" in joined
    assert ":NEXT]" in joined
