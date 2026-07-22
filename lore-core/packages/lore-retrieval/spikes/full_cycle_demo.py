"""End-to-end LIVE cycle: user question -> answer WITH citations.

Wires the SHIPPING pipeline against real backends (no fakes except the reranker,
which is a no-op in P0, and the SQL runner, which stays a fake so this smoke test
needs no TOAST tables — the text lane carries the answer):

    Neo4j (vector+fulltext+expansion)   <- real, projected from lore_core
    bge-m3 via Ollama                    <- real embeddings
    lore_core.chunks / processing_runs   <- real resolver + file-key deep-links
    OpenRouter                           <- real final answer with [n] markers

Flow: fetch real chunks -> project into Neo4j under a demo index_version ->
RetrievalPipeline.answer(question) -> print grounded answer + resolved citations
(each a FileViewer deep-link). Cleans up the demo version unless --keep.

Run (needs VPN for Neo4j, Ollama up with bge-m3, creds in the shared root .env):

    PYTHONPATH=src uv run python spikes/full_cycle_demo.py "ваш вопрос" --limit 200
"""
import argparse
import asyncio

from neo4j import AsyncGraphDatabase

from lore_retrieval.adapters.chat_openrouter import OpenRouterChatModel
from lore_retrieval.adapters.evidence_postgres import PostgresEvidenceResolver
from lore_retrieval.adapters.file_keys import PostgresFileKeyResolver
from lore_retrieval.adapters.neo4j_backends import (
    Neo4jChunkSearchBackend,
    Neo4jGraphExpansionBackend,
    Neo4jTableSearchBackend,
)
from lore_retrieval.config import get_settings
from lore_retrieval.embeddings import OllamaEmbeddingBackend
from lore_retrieval.fakes import FakeReranker, FakeSqlRunner
from lore_retrieval.neo4j_spike import ensure_indexes, project_batch, project_structure
from lore_retrieval.pipeline.graph import RetrievalPipeline
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import fetch_chunks

VERSION = "livecycle"


def _payload_by_chunk(chunks):
    out = {}
    for c in chunks:
        if (
            c.is_table
            and c.payload_refs
            and isinstance(c.payload_refs[0], dict)
            and "payload_id" in c.payload_refs[0]
        ):
            out[c.chunk_id] = c.payload_refs[0]["payload_id"]
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default="О чём этот документ? Приведи ключевые факты.")
    ap.add_argument("--limit", type=int, default=200, help="max chunks to project")
    ap.add_argument("--run", default=None, help="restrict to one processing run_id")
    ap.add_argument("--keep", action="store_true", help="do not drop the demo projection")
    args = ap.parse_args()

    s = get_settings()

    # --- preflight: fail loud with an actionable message, never print secrets ---
    dsn = s.lore_core_effective_dsn
    problems = []
    if not s.neo4j_password:
        problems.append("RETRIEVAL_NEO4J_PASSWORD is empty (Neo4j creds)")
    if not dsn:
        problems.append("no lore_core DSN (set RETRIEVAL_LORE_CORE_DSN or TOAST_DB_*)")
    if not s.openrouter_api_key:
        problems.append("OPENROUTER_API_KEY is empty")
    if problems:
        print("PREFLIGHT FAILED:")
        for p in problems:
            print(f"  - {p}")
        return
    print(
        f"preflight OK · neo4j={s.neo4j_uri} db={s.neo4j_database} · "
        f"embed={s.embedding_model}/{s.embedding_dim} · chat={s.openrouter_model}"
    )

    # --- fast reachability probe for the external lore_core DB (no host printed) ---
    if s.toast_db_host:
        try:
            fut = asyncio.open_connection(s.toast_db_host, s.toast_db_port)
            _, w = await asyncio.wait_for(fut, timeout=6)
            w.close()
            print(f"lore_core DB reachable (port {s.toast_db_port})")
        except (TimeoutError, OSError):
            print(
                f"lore_core DB UNREACHABLE on port {s.toast_db_port} — this is a network "
                "problem, not the code.\n  Check: VPN up? (same as Neo4j) · host/port in "
                "TOAST_DB_* correct? · try `nc -vz <TOAST_DB_HOST> <TOAST_DB_PORT>`."
            )
            return

    # --- pull the real corpus ---
    chunks = await fetch_chunks(dsn, run_id=args.run, limit=args.limit)
    if not chunks:
        print("no chunks found in lore_core.chunks for the given filter — nothing to project")
        return
    runs = sorted({c.run_id for c in chunks})
    print(f"fetched {len(chunks)} chunks from {len(runs)} run(s)")

    emb = OllamaEmbeddingBackend(s.embedding_model, s.ollama_base_url, s.embedding_dim)
    driver = AsyncGraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))
    text_label, table_label = f"TextChunk_{VERSION}", f"TableChunk_{VERSION}"

    try:
        # --- project into Neo4j (idempotent MERGE) ---
        await ensure_indexes(driver, s.neo4j_database, VERSION, emb.dim)
        n = await project_batch(driver, s.neo4j_database, VERSION, chunks, emb)
        proj = build_structural_projection(chunks)
        await project_structure(driver, s.neo4j_database, VERSION, proj)
        async with driver.session(database=s.neo4j_database) as sess:
            await sess.run("CALL db.awaitIndexes(120)")
        print(f"projected {n} chunk nodes + {len(proj.sections)} sections into Neo4j")

        # --- assemble the live pipeline ---
        pipeline = RetrievalPipeline(
            chunk_search=Neo4jChunkSearchBackend(driver, s.neo4j_database, VERSION, emb),
            graph_expansion=Neo4jGraphExpansionBackend(driver, s.neo4j_database, VERSION),
            reranker=FakeReranker(),  # P0: no reranker (deferred to P2)
            resolver=PostgresEvidenceResolver(dsn),
            table_search=Neo4jTableSearchBackend(driver, s.neo4j_database, VERSION, emb),
            sql_runner=FakeSqlRunner({}),  # text-lane demo: no live TOAST needed
            chat_model=OpenRouterChatModel(
                api_key=s.openrouter_api_key,
                model=s.openrouter_model,
                base_url=s.openrouter_base_url,
                max_tokens=s.llm_max_tokens or 800,
            ),
            projection=proj,
            positions={c.chunk_id: c.position for c in chunks},
            text_by_id={c.chunk_id: c.fulltext for c in chunks},
            payload_by_chunk=_payload_by_chunk(chunks),
            file_key_resolver=PostgresFileKeyResolver(dsn),
            index_version=VERSION,
        )

        # --- run the full cycle ---
        print(f"\nQ: {args.question}\n")
        result = await pipeline.answer(args.question)

        print("=" * 72)
        print("ANSWER:\n")
        print(result.decision.answer)
        print("\n" + "=" * 72)
        print(f"CITATIONS ({len(result.citations)}):\n")
        for i, cit in enumerate(result.citations, 1):
            path = " › ".join(cit.heading_path) if cit.heading_path else "(no heading)"
            print(f"[{i}] {path}")
            print(f"    file={cit.logical_file_key} run={cit.run_id} chunk={cit.chunk_id}")
            print(f"    preview: {cit.preview_text}")
            print(f"    link: {cit.deep_link}\n")
        if not result.citations:
            print("(model produced no [n] markers, or no evidence resolved)")

        if result.degradations:
            print("degradations:", ", ".join(result.degradations))
        if result.rejected_evidence:
            print(f"rejected evidence: {len(result.rejected_evidence)}")
    finally:
        if not args.keep:
            async with driver.session(database=s.neo4j_database) as sess:
                for lbl in (text_label, table_label):
                    await sess.run(f"DROP INDEX vec_{lbl} IF EXISTS")
                    await sess.run(f"DROP INDEX ft_{lbl} IF EXISTS")
                    await sess.run(f"MATCH (n:{lbl}) DETACH DELETE n")
                await sess.run(f"MATCH (n:Section_{VERSION}) DETACH DELETE n")
            print("\ncleaned up demo projection (pass --keep to retain for re-runs)")
        await driver.close()


if __name__ == "__main__":
    asyncio.run(main())
