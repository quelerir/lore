"""Full retrieval pipeline composition root.

Wires every stage against the Lore-owned interfaces, running the text lane and
the always-on table lane in parallel, then arbitrating a final answer. Backends
are injected: the in-memory fakes make the whole pipeline runnable and testable
offline; the real Neo4j / cross-encoder / lore_core / toast / OpenRouter
backends drop in behind the same interfaces.

Wrapping ``RetrievalPipeline.answer`` as a LangGraph node (with Langfuse spans
per stage) is the thin integration step into lore-chat; the orchestration logic
is identical whether called directly or from a graph node.
"""
import asyncio

from lore_retrieval.contracts import PipelineResult, SQLResult, TableCandidate
from lore_retrieval.interfaces import (
    ChatModel,
    ChunkSearchBackend,
    CanonicalEvidenceResolver,
    GraphExpansionBackend,
    Reranker,
    SqlRunner,
    TableSearchBackend,
)
from lore_retrieval.pipeline.arbitration import arbitrate_and_answer
from lore_retrieval.pipeline.citation import build_citations
from lore_retrieval.pipeline.expansion import expand_from_fanout
from lore_retrieval.pipeline.fanout import fan_out_and_fuse
from lore_retrieval.pipeline.grouping import build_context_groups
from lore_retrieval.pipeline.rerank import rerank_stage
from lore_retrieval.pipeline.resolve import resolve_evidence
from lore_retrieval.pipeline.table_lane import (
    discover_table_candidates,
    run_sql_fanout,
    select_table_candidates,
)
from lore_retrieval.observability import NullTracer
from lore_retrieval.projection_model import StructuralProjection


def _dedup(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


class RetrievalPipeline:
    def __init__(
        self,
        *,
        chunk_search: ChunkSearchBackend,
        graph_expansion: GraphExpansionBackend,
        reranker: Reranker,
        resolver: CanonicalEvidenceResolver,
        table_search: TableSearchBackend,
        sql_runner: SqlRunner,
        chat_model: ChatModel,
        projection: StructuralProjection,
        positions: dict[str, int],
        text_by_id: dict[str, str],
        payload_by_chunk: dict[str, str],
        file_key_resolver=None,  # optional: async .resolve(run_ids) -> {run_id: logical_file_key}
        tracer=None,  # optional observability seam; defaults to no-op
        index_version: str = "spike1",
        seed_count: int = 10,
        rerank_top_k: int = 12,
        table_floor: float = 0.0,
        max_sql: int = 5,
        citation_limit: int = 8,
        citation_preview_chars: int = 160,
    ) -> None:
        self._chunk_search = chunk_search
        self._graph_expansion = graph_expansion
        self._reranker = reranker
        self._resolver = resolver
        self._table_search = table_search
        self._sql_runner = sql_runner
        self._chat_model = chat_model
        self._projection = projection
        self._positions = positions
        self._text_by_id = text_by_id
        self._payload_by_chunk = payload_by_chunk
        self._file_key_resolver = file_key_resolver
        self._tracer = tracer or NullTracer()
        self._index_version = index_version
        self._seed_count = seed_count
        self._rerank_top_k = rerank_top_k
        self._table_floor = table_floor
        self._max_sql = max_sql
        self._citation_limit = citation_limit
        self._citation_preview_chars = citation_preview_chars

    async def answer(self, question: str) -> PipelineResult:
        degradations: list[str] = []
        (groups, resolution), (table_candidates, sql_results) = await asyncio.gather(
            self._text_lane(question, degradations),
            self._table_lane(question, degradations),
        )
        decision = await arbitrate_and_answer(self._chat_model, question, groups, sql_results)
        self._tracer.record(
            "arbitration",
            {"note": decision.note, "used_sql": len(decision.used_sql_payload_ids)},
        )
        citations = await self._cite(decision, resolution.resolved)
        return PipelineResult(
            decision=decision,
            groups=groups,
            sql_results=sql_results,
            table_candidates=table_candidates,
            citations=citations,
            rejected_evidence=resolution.rejected,
            degradations=degradations,
        )

    async def _cite(self, decision, envelopes):
        """Dedicated cite step: resolve the model's [n] markers into Citations."""
        if not decision.evidence_map:
            return []
        envelope_by_chunk = {e.chunk_id: e for e in envelopes}
        run_ids = list({e.run_id for e in envelopes})
        file_key_by_run = (
            await self._file_key_resolver.resolve(run_ids) if self._file_key_resolver else {}
        )
        citations = build_citations(
            decision.answer,
            decision.evidence_map,
            envelope_by_chunk,
            file_key_by_run,
            preview_chars=self._citation_preview_chars,
            limit=self._citation_limit,
        )
        self._tracer.record("cite", {"citations": len(citations)})
        return citations

    async def _text_lane(self, question: str, degradations: list[str]):
        fanout = await fan_out_and_fuse(self._chunk_search, question, index_version=self._index_version)
        self._tracer.record("text_fanout", {"fused": len(fanout.fused)})

        # Structural expansion is discovery — degrade gracefully if it fails.
        try:
            expanded = await expand_from_fanout(
                self._graph_expansion, fanout, seed_count=self._seed_count
            )
            self._tracer.record("text_expansion", {"expanded": len(expanded)})
        except Exception:
            expanded = []
            degradations.append("structural_expansion_failed")
            self._tracer.record("text_expansion", {"expanded": 0, "degraded": True})

        candidate_ids = _dedup(
            [cid for cid, _ in fanout.fused] + [c.chunk_id for c in expanded]
        )
        reranked = await rerank_stage(
            self._reranker, question, candidate_ids, self._text_by_id, top_k=self._rerank_top_k
        )
        self._tracer.record("text_rerank", {"candidates": len(reranked)})

        resolution = await resolve_evidence(
            self._resolver, [cid for cid, _ in reranked], index_version=self._index_version
        )
        self._tracer.record(
            "text_resolve",
            {"resolved": len(resolution.resolved), "rejected": len(resolution.rejected)},
        )
        valid = {e.chunk_id for e in resolution.resolved}
        reranked_valid = [(cid, score) for cid, score in reranked if cid in valid]

        groups = build_context_groups(
            reranked_valid, self._projection, self._positions, self._text_by_id
        )
        self._tracer.record("grouping", {"groups": len(groups)})
        return groups, resolution

    async def _table_lane(
        self, question: str, degradations: list[str]
    ) -> tuple[list[TableCandidate], list[SQLResult]]:
        # Table-lane failure must not sink the text answer.
        try:
            fused = await discover_table_candidates(self._table_search, question)
            reranked = await rerank_stage(
                self._reranker, question, [cid for cid, _ in fused], self._text_by_id,
                top_k=len(fused) or 1,
            )
            candidates = select_table_candidates(
                reranked, self._payload_by_chunk, floor=self._table_floor, max_k=self._max_sql
            )
            self._tracer.record("table_discover", {"candidates": len(candidates)})
            sql_results = await run_sql_fanout(self._sql_runner, candidates, question)
            self._tracer.record("table_sql", {"calls": len(sql_results)})
            return candidates, sql_results
        except Exception:
            degradations.append("table_lane_unavailable")
            self._tracer.record("table_sql", {"calls": 0, "degraded": True})
            return [], []
