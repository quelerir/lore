# Reliability/observability fixes: SQL-conflict signature + degraded-empty answer

Date: 2026-07-23
Branch: lore-agent-merge
Status: approved (design)

## Context

Two reliability/observability weaknesses in the grounded answer graph, both
surfaced while auditing the retrieval/answer pipeline:

1. **Fragile SQL-conflict detection.** `arbitrate_and_answer`
   (`lore-retrieval/.../pipeline/arbitration.py:67-69`) decides whether two
   successful SQL results "conflict" (and should be presented separately) by
   comparing a signature that prefers the LLM-generated free-text
   `answer_summary`, falling back to `repr(r.rows)`. Two sources with the same
   underlying value but differently-worded summaries are falsely flagged as
   conflicting; `repr(rows)` is sensitive to dict key order and float formatting.

2. **Degraded-empty looks like honest-empty.** When Neo4j / search is
   unavailable, both fan-out routes fail, no evidence is produced, arbitration
   returns `note="no_grounded_evidence"`, and the grounded `summarize` node shows
   the user **"В базе знаний нет ответа на этот вопрос."** — indistinguishable
   from a genuine "this fact isn't in the KB". Degradation warning chips exist,
   but the primary answer text still misleads.

Scope note: most lane failures already degrade visibly (`structural_expansion_failed`,
`reranker_failed`, `table_lane_unavailable`, etc.) and reach the UI as chips
(`lore-chat/app.py:339`). Only the two items above are in scope.

## Decisions

- **Conflict semantics (Q1): compare normalized row values**, not LLM text.
- **Degraded-empty (Q2): different answer text + an explicit flag.**

## Fix 1 — robust SQL-conflict detection

File: `lore-retrieval/src/lore_retrieval/pipeline/arbitration.py`

Add a pure helper that canonicalizes `SQLResult.rows` (ignoring `answer_summary`):

- `_canon_cell(v)`: `None` -> sentinel; `bool` preserved; numbers
  (`int`/`float`/`Decimal`) -> normalized `Decimal` string so `1 == 1.0 == 1.00`;
  anything else -> `str(v).strip()`.
- `_canon_row(row)`: dict with keys sorted, cells canonicalized.
- `_result_signature(r)`: rows canonicalized, the list sorted by each row's
  canonical JSON (row order irrelevant), then
  `json.dumps(..., sort_keys=True, default=str)`.

In `arbitrate_and_answer`, replace:

```python
signatures = {r.answer_summary if r.answer_summary is not None else repr(r.rows) for r in successes}
```

with:

```python
signatures = {_result_signature(r) for r in successes}
```

Conflict condition unchanged: `len(successes) > 1 and len(signatures) > 1`.
`answer_summary` no longer participates in the decision.

Signature/behaviour of `arbitrate_and_answer` is otherwise unchanged.

## Fix 2 — distinguish degraded-empty from honest-empty

New pure module: `lore-retrieval/src/lore_retrieval/pipeline/degradation.py`

```python
RETRIEVAL_BLOCKING_DEGRADATIONS = frozenset({
    "vector_search_failed",
    "fulltext_search_failed",
    "context_load_failed",
    "table_lane_unavailable",
})

def is_degraded_empty(note, degradations) -> bool:
    return note == "no_grounded_evidence" and bool(
        set(degradations) & RETRIEVAL_BLOCKING_DEGRADATIONS
    )
```

Quality-only codes (`structural_expansion_failed`, `reranker_failed`,
`auto_merging_failed`) are deliberately excluded — the lane still ran on the
remaining data, so an empty answer alongside only those is trustworthy.

Rationale for including single-route codes: an empty answer means *both* lanes
produced nothing. So even a lone `vector_search_failed` present at empty-time
means "fulltext ran and found nothing while vector — which might have found it —
was down" → the empty is genuinely untrustworthy. The empty-answer precondition
already excludes the "other route found something" case.

Consumer: `summarize` node in `lore-chat/agents/grounded.py`. When
`decision.answer` is empty:

- `is_degraded_empty(decision.note, state degradations)` true ->
  answer = "⚠️ Не удалось обратиться к базе знаний — попробуйте ещё раз позже."
  and append `"answer_unavailable_degraded"` to the returned `degradations`.
- otherwise -> prior "В базе знаний нет ответа на этот вопрос."

`pipeline.summarize` is not modified; the node already has `degradations` in its
state.

## Testing

- `tests/test_arbitration.py`: same data / different summaries -> no conflict;
  different values -> conflict; `1` vs `1.0` -> no conflict; row-order
  permutation -> no conflict.
- `tests/test_degradation.py`: `is_degraded_empty` truth table — empty + blocking
  code -> degraded; empty + only `reranker_failed` -> honest; non-empty -> honest.
- Grounded `summarize` node: degraded-empty path yields the warning text +
  `answer_unavailable_degraded`; honest-empty path yields the prior text.

## Out of scope

- Redefining conflict beyond value comparison; humanizing degradation chip labels;
  refactoring existing degradation-code producers to share constants; deep-mode
  empty-answer text (fast/grounded path only).
