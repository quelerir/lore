"""Offline evaluation harness (P5, first slice).

Metrics are PURE functions over a ``PipelineResult`` + gold labels, so they're
trivially testable and later reusable against a LIVE pipeline (swap the offline
factory for the live one — the metrics don't change). This slice measures the
citation/retrieval behaviour that IS deterministic offline (with scripted models):

* ``retrieval_recall`` — the gold chunk was surfaced (text group or table anchor).
* ``citation_recall`` — the gold chunk ended up cited.
* ``grounding``       — every citation maps to real retrieved evidence (no invented).
* ``fallback_rate``   — share of cases answered by the deterministic top-N fallback.

Answer-quality metrics (faithfulness, helpfulness) need a live judge model and
come in a later slice; this harness is the structure they plug into.
"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from lore_retrieval.contracts import PipelineResult
from lore_retrieval.pipeline.factory import build_offline_pipeline
from lore_retrieval.source import SourceChunk


@dataclass(frozen=True)
class CaseMetrics:
    retrieval_hit: bool
    citation_hit: bool
    grounded: bool
    fell_back: bool


@dataclass(frozen=True)
class EvalCase:
    """One labelled eval case. ``responder`` scripts the (fake) model's answer so the
    run is deterministic offline; ``gold_chunk_ids`` are the sources that should be
    retrieved/cited."""

    name: str
    query: str
    corpus: list[SourceChunk]
    responder: Callable[[str], str]
    gold_chunk_ids: tuple[str, ...]
    file_keys: dict[str, str]


def _retrieved_ids(result: PipelineResult) -> set[str]:
    ids = {cid for group in result.groups for cid in group.chunk_ids}
    ids |= {candidate.chunk_id for candidate in result.table_candidates}
    return ids


def evaluate_case(result: PipelineResult, gold_chunk_ids: Sequence[str]) -> CaseMetrics:
    """Score one pipeline run against its gold sources (pure)."""
    retrieved = _retrieved_ids(result)
    cited = {citation.chunk_id for citation in result.citations}
    gold = set(gold_chunk_ids)
    return CaseMetrics(
        retrieval_hit=bool(gold & retrieved),
        citation_hit=bool(gold & cited),
        grounded=all(citation.chunk_id in retrieved for citation in result.citations),
        fell_back=bool(result.citations)
        and all(citation.marker is None for citation in result.citations),
    )


def aggregate(metrics: list[CaseMetrics]) -> dict:
    """Mean each boolean metric across cases; empty is safe (all zeros)."""
    n = len(metrics)
    if n == 0:
        return {
            "n": 0, "retrieval_recall": 0.0, "citation_recall": 0.0,
            "grounding": 0.0, "fallback_rate": 0.0,
        }

    def rate(pred: Callable[[CaseMetrics], bool]) -> float:
        return sum(1 for m in metrics if pred(m)) / n

    return {
        "n": n,
        "retrieval_recall": rate(lambda m: m.retrieval_hit),
        "citation_recall": rate(lambda m: m.citation_hit),
        "grounding": rate(lambda m: m.grounded),
        "fallback_rate": rate(lambda m: m.fell_back),
    }


async def run_eval(cases: Sequence[EvalCase]) -> dict:
    """Run each case through a fresh offline pipeline and aggregate the metrics."""
    metrics: list[CaseMetrics] = []
    for case in cases:
        pipeline = build_offline_pipeline(
            case.corpus, chat_responder=case.responder, file_keys=case.file_keys
        )
        result = await pipeline.answer(case.query)
        metrics.append(evaluate_case(result, case.gold_chunk_ids))
    return aggregate(metrics)


def format_report(report: dict) -> str:
    return (
        f"cases={report['n']} "
        f"retrieval_recall={report['retrieval_recall']:.2f} "
        f"citation_recall={report['citation_recall']:.2f} "
        f"grounding={report['grounding']:.2f} "
        f"fallback_rate={report['fallback_rate']:.2f}"
    )
