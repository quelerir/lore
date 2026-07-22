"""DIAGNOSTIC: reproduce table_discover ConnectionError / vector_search_failed.

The chat's ``retrieve()`` runs the text lane and the table lane CONCURRENTLY, so
``vector_search`` (text) and ``table_vector_search`` (table) each call Ollama
``embed_query`` at the SAME instant, through ONE shared OllamaEmbeddings/httpx
client. This probe reproduces that against the PERSISTENT ``index_version`` the
chat queries (no projection, no cleanup) and prints the FULL exception (repr +
traceback) that production swallows down to ``type(exc).__name__``.

Three probes, each repeated so an intermittent failure surfaces:
  A) two concurrent embed_query calls, isolated (no Neo4j) — isolates Ollama
  B) vector_search ∥ table_vector_search, the real retrieve() shape
  C) full retrieve(), end to end

Run (needs the same VPN + Ollama + .env as the chat):
    PYTHONPATH=src uv run python spikes/diagnose_concurrent_embed.py --rounds 15
"""
import argparse
import asyncio
import traceback

from neo4j import AsyncGraphDatabase

from lore_retrieval.config import get_settings
from lore_retrieval.embeddings import OllamaEmbeddingBackend
from lore_retrieval.pipeline.factory import build_live_pipeline

QUESTIONS = ["Какие ФИО у юристов?", "правила офиса и компенсации"]


def _show(tag: str, exc: BaseException) -> None:
    print(f"  !! {tag} FAILED: {exc!r}")
    traceback.print_exception(type(exc), exc, exc.__traceback__)


async def probe_embed_only(emb, rounds: int) -> int:
    """A: two concurrent embed_query, no Neo4j. Isolates the Ollama client."""
    fails = 0
    for i in range(rounds):
        res = await asyncio.gather(
            asyncio.to_thread(emb.embed_query, QUESTIONS[0]),
            asyncio.to_thread(emb.embed_query, QUESTIONS[1]),
            return_exceptions=True,
        )
        for r in res:
            if isinstance(r, BaseException):
                fails += 1
                _show(f"A/embed round {i}", r)
    print(f"[A] embed-only: {fails} failures / {rounds * 2} calls")
    return fails


async def probe_vector_pair(pipeline, rounds: int) -> int:
    """B: vector_search ∥ table_vector_search — the real retrieve() shape."""
    cs = pipeline._chunk_search
    ts = pipeline._table_search
    fails = 0
    for i in range(rounds):
        res = await asyncio.gather(
            cs.vector_search(QUESTIONS[0], 50),
            ts.table_vector_search(QUESTIONS[0], 20),
            return_exceptions=True,
        )
        for tag, r in (("vector_search", res[0]), ("table_vector_search", res[1])):
            if isinstance(r, BaseException):
                fails += 1
                _show(f"B/{tag} round {i}", r)
    print(f"[B] vector-pair: {fails} failures / {rounds * 2} calls")
    return fails


async def probe_retrieve(pipeline, rounds: int) -> int:
    """C: full retrieve() — captures whatever the chat actually hits."""
    fails = 0
    for i in range(rounds):
        try:
            groups, _res, tbl, degr = await pipeline.retrieve(QUESTIONS[0])
            if degr:
                fails += 1
                print(f"  !! C/retrieve round {i} degraded: {degr} "
                      f"(groups={len(groups)}, table_candidates={len(tbl)})")
        except Exception as exc:  # noqa: BLE001 — diagnostic
            fails += 1
            _show(f"C/retrieve round {i}", exc)
    print(f"[C] retrieve: {fails} degraded/failed / {rounds} runs")
    return fails


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=15)
    args = ap.parse_args()

    s = get_settings()
    emb = OllamaEmbeddingBackend(s.embedding_model, s.ollama_base_url, s.embedding_dim)
    driver = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    print(f"neo4j={s.neo4j_uri} db={s.neo4j_database} index_version={s.index_version} "
          f"embed={s.embedding_model}/{s.embedding_dim} ollama={s.ollama_base_url}")
    try:
        pipeline = build_live_pipeline(
            driver=driver,
            database=s.neo4j_database,
            dsn=s.lore_core_effective_dsn,
            embedder=emb,
            chat_model=None,  # not exercised by these probes
            index_version=s.index_version,
        )
        a = await probe_embed_only(emb, args.rounds)
        b = await probe_vector_pair(pipeline, args.rounds)
        c = await probe_retrieve(pipeline, args.rounds)
        print(f"\nSUMMARY: A(embed)={a}  B(vector-pair)={b}  C(retrieve)={c}")
    finally:
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
