"""Classifying an empty answer: honest "not in the KB" vs degraded "couldn't reach it".

An empty grounded answer (arbitration note ``no_grounded_evidence``) is only
trustworthy when retrieval actually ran. These codes mark a backend that SHOULD
have produced evidence being unreachable; when one is present at empty-time the
empty is not trustworthy. Quality-only degradations (expansion / rerank /
grouping fell back but the lane still ran on the remaining data) are excluded.

Note on single-route codes: an empty answer means BOTH lanes produced nothing, so
even a lone ``vector_search_failed`` at empty-time means "fulltext ran and found
nothing while vector — which might have found it — was down". The empty-answer
precondition already excludes the "other route found something" case.
"""
from collections.abc import Iterable

RETRIEVAL_BLOCKING_DEGRADATIONS = frozenset(
    {
        "vector_search_failed",
        "fulltext_search_failed",
        "context_load_failed",
        "table_lane_unavailable",
    }
)


def is_degraded_empty(note: str | None, degradations: Iterable[str]) -> bool:
    """True when an empty answer is due to a retrieval backend being unreachable,
    as opposed to the fact genuinely not being in the knowledge base."""
    if note != "no_grounded_evidence":
        return False
    return bool(set(degradations) & RETRIEVAL_BLOCKING_DEGRADATIONS)
