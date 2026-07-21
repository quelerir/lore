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
    promote_parents: bool = False,  # opt-in refinement; thresholds calibrated in P5
    parent_char_budget: int = 4000,
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

    if promote_parents:
        groups = _promote_parents(
            groups, projection, positions, text_by_id, parent_char_budget
        )
    groups.sort(key=lambda g: g.group_score, reverse=True)
    return groups


def _promote_parents(
    groups: list[ContextGroup],
    projection: StructuralProjection,
    positions: dict[str, int],
    text_by_id: dict[str, str],
    parent_char_budget: int,
) -> list[ContextGroup]:
    """When several hits occupy different child sections of the same parent,
    promote them to one coherent parent-section group — but only when the
    combined window fits the parent budget. Otherwise the child groups stay."""
    section_by_id = {s.section_id: s for s in projection.sections}
    section_chunks = {s.section_id: list(s.chunk_ids) for s in projection.sections}

    by_parent: dict[str | None, list[ContextGroup]] = defaultdict(list)
    for g in groups:
        by_parent[section_by_id[g.section_id].parent_section_id].append(g)

    consumed: set[int] = set()
    promoted: list[ContextGroup] = []
    for parent_id, child_groups in by_parent.items():
        if parent_id is None or len({g.section_id for g in child_groups}) < 2:
            continue
        parent = section_by_id[parent_id]

        member_set = set(section_chunks.get(parent_id, []))
        for g in child_groups:
            member_set.update(g.chunk_ids)
        members = sorted(member_set, key=lambda c: positions.get(c, 0))
        text = " ".join(text_by_id.get(c, "") for c in members)
        if len(text) > parent_char_budget:
            continue  # doesn't fit — leave the smaller child windows

        scores = sorted((g.group_score for g in child_groups), reverse=True)
        promoted.append(
            ContextGroup(
                document_id=parent.document_id,
                section_id=parent_id,
                section_path=parent.heading_path,
                scope="parent_section",
                chunk_ids=members,
                start_position=positions.get(members[0], 0),
                end_position=positions.get(members[-1], 0),
                text=text,
                group_score=scores[0] + 0.1 * sum(scores[1:]),
                citations=[cid for g in child_groups for cid in g.citations],
                truncation_reason=None,
            )
        )
        consumed.update(id(g) for g in child_groups)

    return promoted + [g for g in groups if id(g) not in consumed]
