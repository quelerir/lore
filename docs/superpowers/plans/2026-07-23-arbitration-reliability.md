# Arbitration Reliability Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make SQL-conflict detection robust to LLM phrasing/number formatting, and make an empty answer caused by an unreachable retrieval backend distinguishable from an honest "not in the knowledge base".

**Architecture:** Two independent, mostly-pure changes. (1) In `arbitration.py`, replace the free-text `answer_summary`/`repr(rows)` conflict signature with a canonical signature built from normalized row *values*. (2) Add a pure `degradation.py` classifier (`is_degraded_empty`) in `lore-retrieval`, consumed by the grounded graph's `summarize` node to pick a distinct user message + emit an `answer_unavailable_degraded` flag.

**Tech Stack:** Python 3, Pydantic contracts, LangGraph (grounded graph in `lore-chat`), pytest (async tests, `FakeChatModel` fakes).

## Global Constraints

- Do NOT change the public signatures of `arbitrate_and_answer` or `RetrievalPipeline.summarize`.
- User-facing strings are Russian; keep the existing tone (the codebase uses a `⚠️` prefix for visible degradations).
- Degradation codes are bare strings shared across producers — reference the exact literals, do not refactor existing producers to import shared constants.
- `bool` must be checked before `int` in cell normalization (`isinstance(True, int)` is `True`).
- Two packages: `lore-core/packages/lore-retrieval` (pipeline) and `lore-core/services/lore-chat` (grounded graph). Run each package's tests from its own directory.

---

### Task 1: Robust SQL-conflict signature (row values, not LLM text)

**Files:**
- Modify: `lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/arbitration.py`
- Test: `lore-core/packages/lore-retrieval/tests/test_arbitration.py`

**Interfaces:**
- Consumes: `SQLResult` (`.rows: list[dict]`, `.answer_summary`, `.status`) from `lore_retrieval.contracts`.
- Produces: `_result_signature(result: SQLResult) -> str` (module-private helper); `arbitrate_and_answer` behaviour where two successes conflict iff their normalized row values differ.

- [ ] **Step 1: Update the existing conflict test to carry the difference in rows, and add new signature tests**

The existing `test_conflicting_sql_successes_stay_explicit` distinguishes results only via `answer_summary` with empty `rows`; under value-based comparison both would sign as `"[]"`. Move the difference into `rows`. Then add four tests.

In `lore-core/packages/lore-retrieval/tests/test_arbitration.py`, replace the body of `test_conflicting_sql_successes_stay_explicit` and append the new tests:

```python
async def test_conflicting_sql_successes_stay_explicit():
    model = FakeChatModel()
    a = SQLResult(payload_id="pay1", chunk_id="t1", status=SQLStatus.success,
                  rows=[{"n": 42}], answer_summary="42")
    b = SQLResult(payload_id="pay2", chunk_id="t2", status=SQLStatus.success,
                  rows=[{"n": 99}], answer_summary="99")
    d = await arbitrate_and_answer(model, "сколько?", [], [a, b])
    assert d.note == "conflicting_sql_results"
    assert set(d.used_sql_payload_ids) == {"pay1", "pay2"}   # both kept, not merged
    assert "расходятся" in model.calls[0]


async def test_same_row_values_different_summaries_not_conflict():
    # Same underlying data, differently-worded LLM summaries -> NOT a conflict.
    model = FakeChatModel()
    a = SQLResult(payload_id="pay1", chunk_id="t1", status=SQLStatus.success,
                  rows=[{"n": 42}], answer_summary="сорок два")
    b = SQLResult(payload_id="pay2", chunk_id="t2", status=SQLStatus.success,
                  rows=[{"n": 42}], answer_summary="42 штуки")
    d = await arbitrate_and_answer(model, "сколько?", [], [a, b])
    assert d.note is None


async def test_numeric_formatting_equivalence_not_conflict():
    # 1 vs 1.0 are the same value -> no false conflict.
    model = FakeChatModel()
    a = SQLResult(payload_id="p1", chunk_id="t1", status=SQLStatus.success, rows=[{"n": 1}])
    b = SQLResult(payload_id="p2", chunk_id="t2", status=SQLStatus.success, rows=[{"n": 1.0}])
    d = await arbitrate_and_answer(model, "сколько?", [], [a, b])
    assert d.note is None


async def test_row_order_permutation_not_conflict():
    # Same rows in different order -> same signature -> no conflict.
    model = FakeChatModel()
    a = SQLResult(payload_id="p1", chunk_id="t1", status=SQLStatus.success,
                  rows=[{"n": 1}, {"n": 2}])
    b = SQLResult(payload_id="p2", chunk_id="t2", status=SQLStatus.success,
                  rows=[{"n": 2}, {"n": 1}])
    d = await arbitrate_and_answer(model, "?", [], [a, b])
    assert d.note is None


async def test_different_row_values_conflict():
    model = FakeChatModel()
    a = SQLResult(payload_id="p1", chunk_id="t1", status=SQLStatus.success, rows=[{"n": 1}])
    b = SQLResult(payload_id="p2", chunk_id="t2", status=SQLStatus.success, rows=[{"n": 2}])
    d = await arbitrate_and_answer(model, "?", [], [a, b])
    assert d.note == "conflicting_sql_results"
```

- [ ] **Step 2: Run the tests to verify the new ones fail**

Run (from `lore-core/packages/lore-retrieval`): `python -m pytest tests/test_arbitration.py -v`
Expected: `test_same_row_values_different_summaries_not_conflict` FAILS (current code flags conflict on differing summaries); the numeric/order tests FAIL too (current code uses `repr(rows)`, so `1` vs `1.0` and row-order differ). `test_different_row_values_conflict` may already pass.

- [ ] **Step 3: Implement the value-based signature in `arbitration.py`**

At the top of `arbitration.py`, add imports below the existing module docstring:

```python
import json
from decimal import Decimal, InvalidOperation
```

Add these helpers above `_build_prompt`:

```python
def _canon_cell(value: object) -> object:
    """Normalize one cell so cosmetic differences don't read as data conflicts:
    numbers collapse across int/float/Decimal formatting (1 == 1.0 == 1.00),
    strings are stripped, None/bool are preserved. bool is checked before int
    because ``isinstance(True, int)`` is True."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        try:
            return str(Decimal(str(value)).normalize())
        except (InvalidOperation, ValueError):
            return str(value)
    return str(value).strip()


def _result_signature(result: SQLResult) -> str:
    """Canonical signature of a SQL success from its ROW VALUES (never the
    LLM-written ``answer_summary``): normalized cells, key-sorted rows, and an
    order-independent row list. Two successes conflict when signatures differ."""
    rows = [{key: _canon_cell(row[key]) for key in sorted(row)} for row in result.rows]
    rows.sort(key=lambda r: json.dumps(r, sort_keys=True, default=str))
    return json.dumps(rows, sort_keys=True, default=str)
```

In `arbitrate_and_answer`, replace the signature block:

```python
    # Judge conflict on real content: use the summary when present, else the rows,
    # so two successes with distinct rows but no summary aren't collapsed to {None}.
    signatures = {
        r.answer_summary if r.answer_summary is not None else repr(r.rows) for r in successes
    }
```

with:

```python
    # Judge conflict on the actual row VALUES (normalized), never the LLM-written
    # answer_summary: same data phrased differently must not read as a conflict,
    # and 1 vs 1.0 / row-order differences must not either.
    signatures = {_result_signature(r) for r in successes}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `lore-core/packages/lore-retrieval`): `python -m pytest tests/test_arbitration.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/arbitration.py \
        lore-core/packages/lore-retrieval/tests/test_arbitration.py
git commit -m "fix(arbitration): detect SQL conflict by normalized row values, not LLM text

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: `is_degraded_empty` classifier module

**Files:**
- Create: `lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/degradation.py`
- Test: `lore-core/packages/lore-retrieval/tests/test_degradation.py`

**Interfaces:**
- Produces: `RETRIEVAL_BLOCKING_DEGRADATIONS: frozenset[str]`; `is_degraded_empty(note: str | None, degradations: Iterable[str]) -> bool` in `lore_retrieval.pipeline.degradation`.

- [ ] **Step 1: Write the failing tests**

Append to `lore-core/packages/lore-retrieval/tests/test_degradation.py`:

```python
from lore_retrieval.pipeline.degradation import (  # noqa: E402
    RETRIEVAL_BLOCKING_DEGRADATIONS,
    is_degraded_empty,
)


def test_is_degraded_empty_blocking_code_at_empty_time():
    # A backend that should have produced evidence was unreachable -> untrustworthy empty.
    assert is_degraded_empty("no_grounded_evidence", ["vector_search_failed"]) is True


def test_is_degraded_empty_quality_only_is_honest():
    # Rerank fell back but the lane still ran -> the empty is trustworthy.
    assert is_degraded_empty("no_grounded_evidence", ["reranker_failed"]) is False


def test_is_degraded_empty_non_empty_note_is_honest():
    assert is_degraded_empty(None, ["vector_search_failed"]) is False


def test_is_degraded_empty_no_degradations_is_honest():
    assert is_degraded_empty("no_grounded_evidence", []) is False


def test_blocking_set_excludes_quality_only_codes():
    assert "reranker_failed" not in RETRIEVAL_BLOCKING_DEGRADATIONS
    assert "structural_expansion_failed" not in RETRIEVAL_BLOCKING_DEGRADATIONS
    assert "auto_merging_failed" not in RETRIEVAL_BLOCKING_DEGRADATIONS
    assert "vector_search_failed" in RETRIEVAL_BLOCKING_DEGRADATIONS
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `lore-core/packages/lore-retrieval`): `python -m pytest tests/test_degradation.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lore_retrieval.pipeline.degradation'`.

- [ ] **Step 3: Create the module**

Create `lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/degradation.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run (from `lore-core/packages/lore-retrieval`): `python -m pytest tests/test_degradation.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/degradation.py \
        lore-core/packages/lore-retrieval/tests/test_degradation.py
git commit -m "feat(retrieval): add is_degraded_empty classifier for empty answers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Wire degraded-empty message + flag into the grounded summarize node

**Files:**
- Modify: `lore-core/services/lore-chat/agents/grounded.py:129-161` (`summarize` node)
- Test: `lore-core/services/lore-chat/tests/test_grounded.py`

**Interfaces:**
- Consumes: `is_degraded_empty` from `lore_retrieval.pipeline.degradation`; `state["degradations"]`; `decision.answer`, `decision.note`, `decision.used_sql_payload_ids`.
- Produces: grounded `summarize` node that, on empty answer, emits either the honest "нет ответа" text or the degraded "⚠️ Не удалось обратиться к базе знаний …" text plus `answer_unavailable_degraded` in the returned `degradations`.

- [ ] **Step 1: Write the failing test**

Append to `lore-core/services/lore-chat/tests/test_grounded.py`:

```python
def test_degraded_empty_shows_infra_message_and_flag():
    """Empty answer caused by a retrieval backend being down surfaces a distinct
    'couldn't reach the base' message + an explicit degradation flag — not the
    honest 'not in KB' text."""
    pipe = _FakePipe()

    async def _retrieve(q):
        pipe.calls.append(("retrieve", q))
        return ([], SimpleNamespace(resolved=[], rejected=[]), [], ["vector_search_failed"])

    async def _summarize(q, g, r, s, tc):
        return (
            SimpleNamespace(answer="", note="no_grounded_evidence", used_sql_payload_ids=[]),
            [],
        )

    pipe.retrieve = _retrieve
    pipe.summarize = _summarize
    agent = build_grounded_agent(pipe)
    state = asyncio.run(agent.ainvoke({"messages": [HumanMessage(content="q")]}))
    assert "Не удалось обратиться" in state["messages"][-1].content
    assert "answer_unavailable_degraded" in state["degradations"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `lore-core/services/lore-chat`): `python -m pytest tests/test_grounded.py::test_degraded_empty_shows_infra_message_and_flag -v`
Expected: FAIL — current node emits "В базе знаний нет ответа на этот вопрос." and does not set `answer_unavailable_degraded`.

- [ ] **Step 3: Implement the node change**

In `lore-core/services/lore-chat/agents/grounded.py`, add the import near the other imports at the top of the file:

```python
from lore_retrieval.pipeline.degradation import is_degraded_empty
```

In the `summarize` node, replace the success-return block (currently):

```python
        answer = decision.answer or "В базе знаний нет ответа на этот вопрос."
        return {
            "messages": [AIMessage(content=answer)],
            "citations": citations,
            "answer_detail": {
                "note": decision.note,
                "used_sql_payloads": list(decision.used_sql_payload_ids),
                "citations": len(citations),
            },
        }
```

with:

```python
        degradations = state.get("degradations", [])
        extra_degr: list = []
        if decision.answer:
            answer = decision.answer
        elif is_degraded_empty(decision.note, degradations):
            # Empty because a retrieval backend was unreachable — say so, don't
            # pass it off as an honest "not in the KB".
            answer = "⚠️ Не удалось обратиться к базе знаний — попробуйте ещё раз позже."
            extra_degr = ["answer_unavailable_degraded"]
        else:
            answer = "В базе знаний нет ответа на этот вопрос."
        result = {
            "messages": [AIMessage(content=answer)],
            "citations": citations,
            "answer_detail": {
                "note": decision.note,
                "used_sql_payloads": list(decision.used_sql_payload_ids),
                "citations": len(citations),
            },
        }
        if extra_degr:
            result["degradations"] = degradations + extra_degr
        return result
```

- [ ] **Step 4: Run the test to verify it passes (and the honest-empty test still passes)**

Run (from `lore-core/services/lore-chat`): `python -m pytest tests/test_grounded.py -v`
Expected: `test_degraded_empty_shows_infra_message_and_flag` PASSES and `test_empty_answer_falls_back_to_message` still PASSES (its `note=""` is not `no_grounded_evidence`, so it stays the honest text).

- [ ] **Step 5: Commit**

```bash
git add lore-core/services/lore-chat/agents/grounded.py \
        lore-core/services/lore-chat/tests/test_grounded.py
git commit -m "fix(grounded): distinct message + flag when empty answer is a degradation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Full-suite regression check

**Files:** none (verification only).

- [ ] **Step 1: Run the lore-retrieval suite**

Run (from `lore-core/packages/lore-retrieval`): `python -m pytest -q`
Expected: all pass (no regression in `test_arbitration.py`, `test_degradation.py`, `test_pipeline_e2e.py`, etc.).

- [ ] **Step 2: Run the lore-chat suite**

Run (from `lore-core/services/lore-chat`): `python -m pytest -q`
Expected: all pass (no regression in `test_grounded.py`, `test_graph_flow.py`, etc.).

- [ ] **Step 3: If any unrelated test fails, stop and report** — do not "fix" by loosening assertions; investigate whether the change caused it.

---

## Notes for the implementer

- `answer_summary` is intentionally dropped from the conflict decision — that is the whole point of Task 1. Do not reintroduce it as a tiebreaker.
- The degraded-empty message only fires when the answer is *empty*. A non-empty answer is never overridden, regardless of degradations.
- `GroundedState.degradations` has no LangGraph reducer (plain key = last-write-wins). `toast_sql` already returns `degradations = prior + degr`; Task 3 preserves that by returning `degradations + extra_degr` only on the degraded path.
