"""Section-aware auto-merging (small-to-big / parent-child) stage.

Groups reranked seeds into coherent local windows: within each leaf section,
adjacent (or bounded-gap) hits merge into one connected window; a window that
covers its whole section is promoted to section scope. Distant hits and
different sections stay separate — a whole document is never loaded just
because two far-apart chunks matched. Every canonical member is retained and
cited.

Scope covered here: leaf-section windows + whole-section promotion + budget
truncation + capped group scoring. Parent-section promotion across sibling
child sections (spec step 4-5) and cross-scope overlap merge (step 7) are a
documented follow-up; the ContextGroup contract already carries `parent_section`.
"""
from collections import defaultdict

from lore_retrieval.contracts import ContextGroup
from lore_retrieval.projection_model import StructuralProjection


def build_context_groups(
    reranked: list[tuple[str, float]],
    projection: StructuralProjection,
    positions: dict[str, int],
    text_by_id: dict[str, str],
    *,
    max_gap: int = 1,
    group_char_budget: int = 2000,
) -> list[ContextGroup]:
    score_by_id = dict(reranked)
    section_of = projection.chunk_section
    section_by_id = {s.section_id: s for s in projection.sections}
    section_chunks = {s.section_id: list(s.chunk_ids) for s in projection.sections}

    seeds_by_section: dict[str, list[str]] = defaultdict(list)
    for chunk_id, _ in reranked:
        sec = section_of.get(chunk_id)
        if sec is not None:
            seeds_by_section[sec].append(chunk_id)

    groups: list[ContextGroup] = []
    for sec, seeds in seeds_by_section.items():
        seeds_sorted = sorted(seeds, key=lambda c: positions[c])

        # Split into runs; a run continues while the position gap is small
        # enough to stay one coherent window (bounded by max_gap intervening).
        runs: list[list[str]] = [[seeds_sorted[0]]]
        for prev, nxt in zip(seeds_sorted, seeds_sorted[1:]):
            if positions[nxt] - positions[prev] <= max_gap + 1:
                runs[-1].append(nxt)
            else:
                runs.append([nxt])

        section = section_by_id[sec]
        all_chunks = section_chunks[sec]
        for run in runs:
            start_pos, end_pos = positions[run[0]], positions[run[-1]]
            members = [c for c in all_chunks if start_pos <= positions.get(c, -1) <= end_pos]
            scope = "section" if members == all_chunks else "window"

            text = " ".join(text_by_id.get(c, "") for c in members)
            truncation = None
            if len(text) > group_char_budget:
                text = text[:group_char_budget]
                truncation = "char_budget"

            run_scores = sorted((score_by_id.get(c, 0.0) for c in run), reverse=True)
            group_score = run_scores[0] + 0.1 * sum(run_scores[1:])  # best + capped diminishing

            groups.append(
                ContextGroup(
                    document_id=section.document_id,
                    section_id=sec,
                    section_path=section.heading_path,
                    scope=scope,
                    chunk_ids=members,
                    start_position=start_pos,
                    end_position=end_pos,
                    text=text,
                    group_score=group_score,
                    citations=list(run),
                    truncation_reason=truncation,
                )
            )

    groups.sort(key=lambda g: g.group_score, reverse=True)
    return groups
