"""Live validation of the code-ahead Neo4j path against a real instance.

Uses a deterministic fake embedder (no Ollama) + a tiny synthetic corpus to
exercise the SHIPPING code — ensure_indexes / project_batch / project_structure
and the Neo4j{ChunkSearch,TableSearch,GraphExpansion}Backend adapters — then
cleans up (drops the version-labelled indexes + nodes). Run:

    PYTHONPATH=src uv run python spikes/live_validate_neo4j.py
"""
import asyncio
import hashlib

from neo4j import AsyncGraphDatabase

from lore_retrieval.adapters.neo4j_backends import (
    Neo4jChunkSearchBackend,
    Neo4jGraphExpansionBackend,
    Neo4jTableSearchBackend,
)
from lore_retrieval.config import get_settings
from lore_retrieval.neo4j_spike import ensure_indexes, project_batch, project_structure
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import SourceChunk

VERSION = "livecheck"


class FakeEmbedder:
    dim = 8

    def _vec(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in h[: self.dim]]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def _chunk(cid, ordinal, path, text, ctype="text", payload=None):
    return SourceChunk(
        chunk_id=cid, document_id="livedoc", run_id="livedoc", chunk_type=ctype, position=ordinal,
        heading_path=tuple(path), vector_text=text, fulltext=text, display_text=text,
        payload_refs=[{"payload_id": payload}] if payload else [],
        vector_text_hash="h", fulltext_hash="h",
    )


CORPUS = [
    _chunk("c0", 0, ("Root",), "введение раздел"),
    _chunk("c1", 1, ("Root", "Премия"), "премия сотрудника формула расчёта"),
    _chunk("c2", 2, ("Root", "Премия"), "формула премия учитывает оклад"),
    _chunk("t1", 3, ("Root", "Таблицы"), "таблица оклад сотрудник", "table_payload", "pay1"),
]


async def main():
    s = get_settings()
    emb = FakeEmbedder()
    driver = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    text_label, table_label = f"TextChunk_{VERSION}", f"TableChunk_{VERSION}"
    try:
        await ensure_indexes(driver, s.neo4j_database, VERSION, emb.dim)
        n = await project_batch(driver, s.neo4j_database, VERSION, CORPUS, emb)
        proj = build_structural_projection(CORPUS)
        await project_structure(driver, s.neo4j_database, VERSION, proj)
        async with driver.session(database=s.neo4j_database) as sess:
            await sess.run("CALL db.awaitIndexes(60)")
        print(f"projected {n} chunk nodes + structure")

        chunk_be = Neo4jChunkSearchBackend(driver, s.neo4j_database, VERSION, emb)
        table_be = Neo4jTableSearchBackend(driver, s.neo4j_database, VERSION, emb)
        exp_be = Neo4jGraphExpansionBackend(driver, s.neo4j_database, VERSION)

        vec = await chunk_be.vector_search("премия формула", 5)
        ft = await chunk_be.fulltext_search("премия", 5)
        tvf = await table_be.table_fulltext_search("таблица", 5)
        exp = await exp_be.expand(["c1"])

        print("vector_search:  ", vec)
        print("fulltext_search:", ft)
        print("table_fulltext: ", tvf)
        print("expansion(c1):  ", [(c.chunk_id, c.route.value) for c in exp])

        assert vec, "vector_search returned nothing"
        assert any(cid == "c1" for cid, _ in ft), "fulltext missed c1"
        assert any(cid == "t1" for cid, _ in tvf), "table lane missed t1"
        assert {c.chunk_id for c in exp} >= {"c0", "c2"}, "expansion missed neighbours"
        print("\nALL LIVE CHECKS PASSED ✅")
    finally:
        async with driver.session(database=s.neo4j_database) as sess:
            for lbl in (text_label, table_label):
                await sess.run(f"DROP INDEX vec_{lbl} IF EXISTS")
                await sess.run(f"DROP INDEX ft_{lbl} IF EXISTS")
                await sess.run(f"MATCH (n:{lbl}) DETACH DELETE n")
            await sess.run(f"MATCH (n:Section_{VERSION}) DETACH DELETE n")
        await driver.close()
        print("cleaned up (indexes + nodes dropped)")


if __name__ == "__main__":
    asyncio.run(main())
