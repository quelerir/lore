"""Index the lore_core corpus into Neo4j under the configured ``index_version``.

Persistent projection (no cleanup) that the lore-chat ``knowledge_base`` tool
queries. This is the prerequisite indexing job — the chat request path only reads.
Idempotent (MERGE), so re-running refreshes. Run (VPN up, Ollama+bge-m3, creds in
the shared root .env):

    PYTHONPATH=src uv run python spikes/index_corpus.py --limit 500
"""
import argparse
import asyncio

from neo4j import AsyncGraphDatabase

from lore_retrieval.config import get_settings
from lore_retrieval.embeddings import build_embedder
from lore_retrieval.neo4j_spike import ensure_indexes, project_batch, project_structure
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import fetch_chunks


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=500, help="max chunks to index")
    ap.add_argument("--run", default=None, help="restrict to one processing run_id")
    args = ap.parse_args()

    s = get_settings()
    dsn = s.lore_core_effective_dsn
    if not (s.neo4j_password and dsn):
        print("PREFLIGHT FAILED: need Neo4j creds + a lore_core DSN in the root .env")
        return
    version = s.index_version
    print(
        f"indexing into Neo4j db={s.neo4j_database} version='{version}' "
        f"embed={s.embedding_model}/{s.embedding_dim}"
    )

    chunks = await fetch_chunks(dsn, run_id=args.run, limit=args.limit)
    if not chunks:
        print("no chunks fetched from lore_core.chunks — nothing to index")
        return

    emb = build_embedder(
        endpoint=s.embedding_endpoint, model=s.embedding_model,
        base_url=s.ollama_base_url, dim=s.embedding_dim,
    )
    driver = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    try:
        await ensure_indexes(driver, s.neo4j_database, version, emb.dim)
        n = await project_batch(driver, s.neo4j_database, version, chunks, emb)
        proj = build_structural_projection(chunks)
        await project_structure(driver, s.neo4j_database, version, proj)
        async with driver.session(database=s.neo4j_database) as sess:
            await sess.run("CALL db.awaitIndexes(300)")
        runs = len({c.run_id for c in chunks})
        print(
            f"indexed {n} chunk nodes + {len(proj.sections)} sections from "
            f"{runs} run(s) under '{version}' — the knowledge_base tool can now query it"
        )
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
