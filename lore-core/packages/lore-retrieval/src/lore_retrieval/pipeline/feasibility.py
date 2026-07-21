"""Schema-feasibility assessment for the table lane.

Judges whether a table's schema can express the requested lookup/aggregation —
by mapping required filters/measures to columns, NOT by checking sample values.
A query value absent from samples never rejects an otherwise-expressible schema.
Recall-first: with no stated requirements, a table is feasible.
"""
from lore_retrieval.contracts import QueryRequirements, TableProfile
from lore_retrieval.text_utils import tokenize


def _tokens(text: str) -> set[str]:
    return set(tokenize(text))


def assess_feasibility(
    profile: TableProfile, requirements: QueryRequirements
) -> tuple[bool, str | None]:
    needed = requirements.filters + requirements.measures
    if not needed:
        return True, None  # recall-first: nothing to disqualify

    column_tokens: set[str] = set()
    for col in profile.columns:
        column_tokens |= _tokens(col)

    unmet = [n for n in needed if not (_tokens(n) & column_tokens)]
    if unmet:
        return False, "no column for: " + ", ".join(unmet)
    return True, None


def feasibility_predicate(
    profiles: dict[str, TableProfile],
    payload_by_chunk: dict[str, str],
    requirements: QueryRequirements,
):
    """Build the ``feasible(chunk_id) -> bool`` predicate that
    ``select_table_candidates`` expects. A chunk with no known profile is treated
    as feasible (recall-first — do not reject on missing metadata)."""

    def feasible(chunk_id: str) -> bool:
        payload_id = payload_by_chunk.get(chunk_id)
        profile = profiles.get(payload_id) if payload_id else None
        if profile is None:
            return True
        ok, _reason = assess_feasibility(profile, requirements)
        return ok

    return feasible
