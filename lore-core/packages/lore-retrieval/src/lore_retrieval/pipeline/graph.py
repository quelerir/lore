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

from lore_retrieval.contracts import ContextGroup, PipelineResult, SQLResult, TableCandidate
from lore_retrieval.interfaces import (
    ChatModel,
    ChunkContextLoader,
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
from lore_retrieval.projection_model import StructuralProjection, build_structural_projection


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
        context_loader: ChunkContextLoader,
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
        self._context_loader = context_loader
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
        """Full turn = the three stages in sequence. The lore-chat grounded graph
        drives the SAME three methods as explicit LangGraph nodes."""
        groups, resolution, table_candidates, degradations = await self.retrieve(question)
        sql_results, sql_degr = await self.run_table_sql(question, table_candidates)
        decision, citations = await self.summarize(question, groups, resolution, sql_results)
        return PipelineResult(
            decision=decision,
            groups=groups,
            sql_results=sql_results,
            table_candidates=table_candidates,
            citations=citations,
            rejected_evidence=resolution.rejected,
            degradations=degradations + sql_degr,
        )

    # --- The three stages, exposed so a LangGraph can call them as nodes ---

    async def retrieve(self, question: str):
        """Stage 1 (neo4j): text lane ∥ table discovery. Returns
        (groups, resolution, table_candidates, degradations)."""
        degradations: list[str] = []
        (groups, resolution), table_candidates = await asyncio.gather(
            self._text_lane(question, degradations),
            self._table_discover(question, degradations),
        )
        return groups, resolution, table_candidates, degradations

    async def run_table_sql(
        self, question: str, table_candidates: list[TableCandidate]
    ) -> tuple[list[SQLResult], list[str]]:
        """Stage 2: bounded parallel SQL over the discovered table candidates."""
        degradations: list[str] = []
        try:
            sql_results = await run_sql_fanout(self._sql_runner, table_candidates, question)
        except Exception as exc:
            degradations.append("table_lane_unavailable")
            self._tracer.record(
                "table_sql",
                {"calls": 0, "degraded": True,
                 "error": type(exc).__name__, "detail": repr(exc)},
            )
            return [], degradations
        self._tracer.record("table_sql", {"calls": len(sql_results)})
        return sql_results, degradations

    async def summarize(self, question, groups, resolution, sql_results):
        """Stage 3: top-level arbitration (final answer) + citation resolution."""
        decision = await arbitrate_and_answer(self._chat_model, question, groups, sql_results)
        self._tracer.record(
            "arbitration",
            {"note": decision.note, "used_sql": len(decision.used_sql_payload_ids)},
        )
        citations = await self._cite(decision, resolution.resolved)
        return decision, citations

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
        fanout, fan_degraded, fan_failures = await fan_out_and_fuse(
            self._chunk_search, question, index_version=self._index_version
        )
        degradations.extend(fan_degraded)
        fanout_trace: dict = {"fused": len(fanout.fused), "degraded": fan_degraded}
        # Surface the real exception(s) so a failed route isn't silent in the trace.
        if fan_failures:
            fanout_trace["failures"] = fan_failures
        self._tracer.record("text_fanout", fanout_trace)

        # Structural expansion is discovery — degrade gracefully if it fails.
        try:
            expanded = await expand_from_fanout(
                self._graph_expansion, fanout, seed_count=self._seed_count
            )
            self._tracer.record("text_expansion", {"expanded": len(expanded)})
        except Exception as exc:
            expanded = []
            degradations.append("structural_expansion_failed")
            # Record the error type so a logic bug isn't fully silent behind degradation.
            self._tracer.record(
                "text_expansion",
                {"expanded": 0, "degraded": True,
                 "error": type(exc).__name__, "detail": repr(exc)},
            )

        candidate_ids = _dedup(
            [cid for cid, _ in fanout.fused] + [c.chunk_id for c in expanded]
        )
        # Per-query context: load ONLY the candidate rows, then derive the maps
        # (positions / text / candidate-scoped projection) locally — never the
        # whole corpus. Loader failure degrades to empty maps (turn survives).
        projection, positions, text_by_id = await self._load_context(candidate_ids, degradations)

        try:
            reranked = await rerank_stage(
                self._reranker, question, candidate_ids, text_by_id, top_k=self._rerank_top_k
            )
        except Exception:
            # Reranker down: fall back to the bounded fused order (spec degradation).
            reranked = [
                (cid, 1.0 / (i + 1)) for i, cid in enumerate(candidate_ids[: self._rerank_top_k])
            ]
            degradations.append("reranker_failed")
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

        try:
            groups = build_context_groups(reranked_valid, projection, positions, text_by_id)
        except Exception:
            # Auto-merging failed: pass bounded individual chunks rather than lose evidence.
            groups = [
                self._singleton_group(cid, score, projection, positions, text_by_id)
                for cid, score in reranked_valid
            ]
            degradations.append("auto_merging_failed")
        self._tracer.record("grouping", {"groups": len(groups)})
        return groups, resolution

    async def _load_context(
        self, chunk_ids: list[str], degradations: list[str]
    ) -> tuple[StructuralProjection, dict[str, int], dict[str, str]]:
        try:
            chunks = await self._context_loader.load(chunk_ids)
        except Exception as exc:
            degradations.append("context_load_failed")
            self._tracer.record(
                "text_context",
                {"loaded": 0, "error": type(exc).__name__, "detail": repr(exc)},
            )
            chunks = []
        self._tracer.record("text_context", {"loaded": len(chunks)})
        projection = build_structural_projection(chunks)
        positions = {c.chunk_id: c.position for c in chunks}
        text_by_id = {c.chunk_id: c.fulltext for c in chunks}
        return projection, positions, text_by_id

    @staticmethod
    def _singleton_group(
        chunk_id: str,
        score: float,
        projection: StructuralProjection,
        positions: dict[str, int],
        text_by_id: dict[str, str],
    ) -> ContextGroup:
        pos = positions.get(chunk_id, 0)
        return ContextGroup(
            document_id="",
            section_id=projection.chunk_section.get(chunk_id, ""),
            section_path=(),
            scope="window",
            chunk_ids=[chunk_id],
            start_position=pos,
            end_position=pos,
            text=text_by_id.get(chunk_id, ""),
            group_score=score,
            citations=[chunk_id],
        )

    async def _table_discover(
        self, question: str, degradations: list[str]
    ) -> list[TableCandidate]:
        # Table discovery (neo4j). SQL execution is a separate stage (run_table_sql).
        try:
            fused = await discover_table_candidates(self._table_search, question)
            table_ids = [cid for cid, _ in fused]
            # Per-query: load the discovered table rows for their text + payload ids.
            tbl_chunks = await self._context_loader.load(table_ids)
            text_by_id = {c.chunk_id: c.fulltext for c in tbl_chunks}
            provenance_by_chunk = {
                c.chunk_id: (c.run_id, c.heading_path) for c in tbl_chunks
            }
            payload_by_chunk = {
                c.chunk_id: c.payload_refs[0]["payload_id"]
                for c in tbl_chunks
                if c.is_table
                and c.payload_refs
                and isinstance(c.payload_refs[0], dict)
                and "payload_id" in c.payload_refs[0]
            }
            reranked = await rerank_stage(
                self._reranker, question, table_ids, text_by_id, top_k=len(fused) or 1,
            )
            candidates = select_table_candidates(
                reranked, payload_by_chunk, floor=self._table_floor, max_k=self._max_sql,
                provenance_by_chunk=provenance_by_chunk,
            )
            self._tracer.record("table_discover", {"candidates": len(candidates)})
            return candidates
        except Exception as exc:
            degradations.append("table_lane_unavailable")
            self._tracer.record(
                "table_discover",
                {"candidates": 0, "degraded": True,
                 "error": type(exc).__name__, "detail": repr(exc)},
            )
            return []
