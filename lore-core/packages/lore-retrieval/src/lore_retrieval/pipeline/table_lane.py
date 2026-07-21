"""Always-on table lane + bounded parallel SQL fan-out.

Runs on every query in parallel with the text lane: table vector + fulltext ->
RRF, then recall-first selection deduplicated to one physical payload per slot,
capped at K<=5, then up to five INDEPENDENT read-only SQL calls in parallel.

Table discovery does not imply SQL execution: the caller may answer from a
table's profile without running SQL. Physical table names come only from the
trusted registry inside the SqlRunner — never from Neo4j text or an LLM.
"""
import asyncio
from collections.abc import Callable

from lore_retrieval.contracts import SqlRequest, SQLResult, TableCandidate
from lore_retrieval.interfaces import SqlRunner, TableSearchBackend
from lore_retrieval.neo4j_spike import rrf_fuse


async def discover_table_candidates(
    backend: TableSearchBackend,
    query: str,
    *,
    vector_k: int = 20,
    fulltext_k: int = 20,
    rrf_k: int = 60,
) -> list[tuple[str, float]]:
    vec, ft = await asyncio.gather(
        backend.table_vector_search(query, vector_k),
        backend.table_fulltext_search(query, fulltext_k),
    )
    return rrf_fuse([vec, ft], rrf_k=rrf_k)


def select_table_candidates(
    reranked: list[tuple[str, float]],
    payload_by_chunk: dict[str, str],
    *,
    feasible: Callable[[str], bool] | None = None,
    floor: float = 0.0,
    max_k: int = 5,
) -> list[TableCandidate]:
    """Recall-first: dedup to one physical payload per slot, drop below-floor and
    infeasible schemas, cap at max_k, never pad with irrelevant candidates."""
    is_feasible = feasible or (lambda _cid: True)
    seen_payloads: set[str] = set()
    out: list[TableCandidate] = []
    for chunk_id, score in reranked:
        if len(out) >= max_k:
            break
        if score < floor:
            continue
        payload_id = payload_by_chunk.get(chunk_id)
        if payload_id is None or payload_id in seen_payloads:
            continue  # repeated physical payload consumes one slot
        if not is_feasible(chunk_id):
            continue
        seen_payloads.add(payload_id)
        out.append(TableCandidate(chunk_id=chunk_id, payload_id=payload_id, score=score))
    return out


async def run_sql_fanout(
    runner: SqlRunner, candidates: list[TableCandidate], question: str
) -> list[SQLResult]:
    requests = [
        SqlRequest(question=question, payload_id=c.payload_id, chunk_id=c.chunk_id)
        for c in candidates
    ]
    results = await asyncio.gather(*(runner.run(r) for r in requests))
    return list(results)
