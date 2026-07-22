# Phase D — Table Citations, Inline `[n]` Superscripts, Deterministic Fallback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make tables that grounded an answer clickable FileViewer citations (`tab=payloads`), render the model's `[n]` markers as inline superscripts, and fall back to the top-3 shown evidence when the model cites nothing.

**Architecture:** Backend (pure, offline-testable) in `lore-core/packages/lore-retrieval`: arbitration enumerates SQL successes into the `[n]` sequence; `TableCandidate` carries the anchor's provenance (already loaded, currently discarded); the `cite` step resolves both text and table markers, with a deterministic top-N fallback. Frontend renders a table icon for `kind="table"` cards and turns `[n]` in the answer into superscripts that jump to the matching card.

**Tech Stack:** Python 3.13 (pydantic v2, pytest, ruff, mypy) via `lore-core/.venv`; React 18 + TypeScript + ReactMarkdown (remark/rehype) + vitest, built on Node 22 (nvm).

## Global Constraints

- Python **3.13**; run backend tools from `lore-core/.venv` (`source lore-core/.venv/bin/activate`).
- `lore-retrieval` core stays **pure** (no fastapi/airflow/chainlit imports); `test_purity.py` guards this.
- Backend verify (run in `lore-core/packages/lore-retrieval`): `python -m pytest -q` + `python -m ruff check src tests` + `python -m mypy src`.
- Frontend verify (run in `frontend`, Node 22 via `nvm use 22`): `npx vitest run` + `npx tsc -b`.
- **Backward-compatible metadata:** every new contract field is additive with a default so pre-Phase-D messages still map (`kind="text"`, `marker=None`, `sql_evidence_map={}`, `TableCandidate.run_id=""`, `heading_path=()`).
- Deep-links are built only from trusted identifiers (`logical_file_key`/`run_id`/`chunk_id`), never from model text.
- Commit after every task. Do NOT commit `test.txt` (untracked local VPN notes — leave it).

---

## File Structure

**Backend — `lore-core/packages/lore-retrieval/`**
- `src/lore_retrieval/contracts.py` — add fields to `Citation`, `AgentDecision`, `TableCandidate` (Task 1).
- `src/lore_retrieval/pipeline/citation.py` — `build_deep_link` gains `tab`; `build_citations` gains table + fallback support (Task 2).
- `src/lore_retrieval/pipeline/arbitration.py` — enumerate SQL into `[n]`, emit `sql_evidence_map` (Task 3).
- `src/lore_retrieval/pipeline/table_lane.py` — `select_table_candidates` accepts anchor provenance (Task 4).
- `src/lore_retrieval/pipeline/graph.py` — `_table_discover` passes provenance; `summarize`/`_cite` thread sql_results + table_candidates and build both citation kinds (Task 4, Task 5).
- Tests: `tests/test_citation.py`, `tests/test_arbitration.py`, `tests/test_table_lane.py`, `tests/test_pipeline.py` (extend existing; create if absent).

**lore-chat (single-line ripple)**
- `services/lore-chat/agents/grounded.py` — `summarize` node passes `table_candidates` (Task 5).

**Frontend — `frontend/src/`**
- `chat/citations.ts` — `Citation`/`RawCitation` gain `kind` + `marker` (Task 6).
- `components/Citations/Citations.tsx` + `Citations.module.css` — table icon + card `id` for jump target (Task 7).
- `chat/citationMarkers.ts` (new) — rehype plugin turning `[n]` into `<sup>` (Task 8).
- `components/AssistantMessage/AssistantMessage.tsx` — wire the plugin + `sup` renderer + jump/highlight (Task 8).
- Tests: `chat/citations.test.ts`, `chat/citationMarkers.test.ts` (new).

---

## Task 1: Contract fields (Citation.kind/marker, AgentDecision.sql_evidence_map, TableCandidate provenance)

**Files:**
- Modify: `lore-core/packages/lore-retrieval/src/lore_retrieval/contracts.py`
- Test: `lore-core/packages/lore-retrieval/tests/test_contracts_phase_d.py` (create)

**Interfaces:**
- Produces:
  - `Citation(..., kind: Literal["text","table"] = "text", marker: int | None = None)`
  - `AgentDecision(..., sql_evidence_map: dict[int, str] = {})`
  - `TableCandidate(..., run_id: str = "", heading_path: tuple[str, ...] = ())`

- [ ] **Step 1: Write the failing test**

Create `tests/test_contracts_phase_d.py`:

```python
from lore_retrieval.contracts import AgentDecision, Citation, TableCandidate


def test_citation_defaults_are_backward_compatible():
    c = Citation(
        chunk_id="c1", run_id="r1", logical_file_key="f", preview_text="p",
        heading_path=(), deep_link="/files?...",
    )
    assert c.kind == "text"
    assert c.marker is None


def test_citation_accepts_table_kind_and_marker():
    c = Citation(
        chunk_id="c1", run_id="r1", logical_file_key="f", preview_text="p",
        heading_path=(), deep_link="/files?...&tab=payloads", kind="table", marker=3,
    )
    assert c.kind == "table"
    assert c.marker == 3


def test_agent_decision_sql_evidence_map_defaults_empty():
    d = AgentDecision(
        answer="a", used_evidence_chunk_ids=[], used_sql_payload_ids=[], citations=[],
    )
    assert d.sql_evidence_map == {}


def test_table_candidate_carries_optional_provenance():
    tc = TableCandidate(chunk_id="c1", payload_id="p1", score=1.0)
    assert tc.run_id == "" and tc.heading_path == ()
    tc2 = TableCandidate(
        chunk_id="c1", payload_id="p1", score=1.0, run_id="r1", heading_path=("H",),
    )
    assert tc2.run_id == "r1" and tc2.heading_path == ("H",)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd lore-core/packages/lore-retrieval && source ../../.venv/bin/activate && python -m pytest tests/test_contracts_phase_d.py -q`
Expected: FAIL (`Citation` has no `kind`; unexpected keyword).

- [ ] **Step 3: Implement the field additions**

In `contracts.py`, ensure `Literal` is imported (`from typing import Literal`). Update the three models:

```python
class Citation(BaseModel):
    """A model-chosen source reference rendered as a clickable preview card that
    deep-links into the FileViewer. Built only from verified evidence."""

    chunk_id: str
    run_id: str
    logical_file_key: str
    preview_text: str
    heading_path: tuple[str, ...]
    deep_link: str
    kind: Literal["text", "table"] = "text"
    marker: int | None = None  # the [n] index; None for deterministic-fallback citations
```

```python
class TableCandidate(BaseModel):
    chunk_id: str
    payload_id: str
    score: float
    feasible: bool = True
    reason: str | None = None
    run_id: str = ""                      # anchor provenance (from the loaded SourceChunk)
    heading_path: tuple[str, ...] = ()
```

In `AgentDecision`, add after `evidence_map`:

```python
    # index -> the SQL success's anchor chunk_id, continuing the [n] sequence after
    # the text groups; disjoint index range from evidence_map.
    sql_evidence_map: dict[int, str] = {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_contracts_phase_d.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the full package gate**

Run: `python -m pytest -q && python -m ruff check src tests && python -m mypy src`
Expected: all existing tests still pass; ruff clean; mypy shows no NEW errors in `contracts.py`.

- [ ] **Step 6: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/contracts.py \
        lore-core/packages/lore-retrieval/tests/test_contracts_phase_d.py
git commit -m "feat(retrieval): Phase D contracts — Citation kind/marker, sql_evidence_map, TableCandidate provenance"
```

---

## Task 2: `build_deep_link` tab param + `build_citations` table & fallback support

**Files:**
- Modify: `lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/citation.py`
- Test: `lore-core/packages/lore-retrieval/tests/test_citation.py` (extend; create if absent)

**Interfaces:**
- Consumes: `Citation`, `EvidenceEnvelope`, `SQLResult`, `TableCandidate` from `contracts.py`.
- Produces:
  - `build_deep_link(logical_file_key, run_id, chunk_id, *, tab: str = "display") -> str`
  - `build_citations(answer, evidence_map, envelope_by_chunk, file_key_by_run, *, sql_evidence_map=None, sql_result_by_chunk=None, table_candidate_by_chunk=None, preview_chars=160, limit=8, fallback_limit=3) -> list[Citation]`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_citation.py` (create the file with these imports if it does not exist):

```python
from lore_retrieval.contracts import Citation, EvidenceEnvelope, SQLResult, SQLStatus, TableCandidate
from lore_retrieval.pipeline.citation import build_citations, build_deep_link


def _env(chunk_id, run_id="r1"):
    return EvidenceEnvelope(
        chunk_id=chunk_id, run_id=run_id, display_text=f"disp {chunk_id}",
        fulltext=f"full {chunk_id}", coordinates={"heading_path": ["H", chunk_id]},
        payload_refs=[], index_version="v1", fulltext_hash="fh",
    )


def _sql(chunk_id, payload_id, summary):
    return SQLResult(
        payload_id=payload_id, chunk_id=chunk_id, status=SQLStatus.success,
        rows=[{"n": 1}], answer_summary=summary,
    )


def test_deep_link_defaults_to_display_and_accepts_payloads_tab():
    assert build_deep_link("f", "r", "c").endswith("&tab=display")
    assert build_deep_link("f", "r", "c", tab="payloads").endswith("&tab=payloads")


def test_table_marker_builds_table_citation_with_payloads_tab():
    # text group [1] -> c1 ; SQL success [2] -> anchor a1 (payload p1)
    citations = build_citations(
        answer="Ответ [2].",
        evidence_map={1: ["c1"]},
        envelope_by_chunk={"c1": _env("c1"), "a1": _env("a1")},
        file_key_by_run={"r1": "docs/file.xlsx"},
        sql_evidence_map={2: "a1"},
        sql_result_by_chunk={"a1": _sql("a1", "p1", "Итог: 42")},
        table_candidate_by_chunk={"a1": TableCandidate(
            chunk_id="a1", payload_id="p1", score=1.0, run_id="r1", heading_path=("H", "a1"),
        )},
    )
    assert len(citations) == 1
    cit = citations[0]
    assert cit.kind == "table"
    assert cit.marker == 2
    assert cit.preview_text == "Итог: 42"           # preview from the SQL summary
    assert cit.logical_file_key == "docs/file.xlsx"
    assert cit.deep_link.endswith("&tab=payloads")
    assert "chunk=a1" in cit.deep_link


def test_mixed_markers_resolve_in_first_appearance_order():
    citations = build_citations(
        answer="Сначала [2], затем [1].",
        evidence_map={1: ["c1"]},
        envelope_by_chunk={"c1": _env("c1"), "a1": _env("a1")},
        file_key_by_run={"r1": "f"},
        sql_evidence_map={2: "a1"},
        sql_result_by_chunk={"a1": _sql("a1", "p1", "s")},
        table_candidate_by_chunk={"a1": TableCandidate(
            chunk_id="a1", payload_id="p1", score=1.0, run_id="r1")},
    )
    assert [c.kind for c in citations] == ["table", "text"]
    assert [c.marker for c in citations] == [2, 1]


def test_fallback_top_n_when_no_markers_resolved():
    # Answer cites nothing; grounding exists (1 text + 1 SQL). Fallback -> shown order.
    citations = build_citations(
        answer="Ответ без маркеров.",
        evidence_map={1: ["c1"]},
        envelope_by_chunk={"c1": _env("c1"), "a1": _env("a1")},
        file_key_by_run={"r1": "f"},
        sql_evidence_map={2: "a1"},
        sql_result_by_chunk={"a1": _sql("a1", "p1", "s")},
        table_candidate_by_chunk={"a1": TableCandidate(
            chunk_id="a1", payload_id="p1", score=1.0, run_id="r1")},
        fallback_limit=3,
    )
    assert [c.kind for c in citations] == ["text", "table"]   # shown order: text then SQL
    assert all(c.marker is None for c in citations)           # fallback -> no inline markers


def test_no_grounding_yields_no_citations():
    assert build_citations(
        answer="ничего", evidence_map={}, envelope_by_chunk={}, file_key_by_run={},
    ) == []


def test_table_dedup_by_payload_id():
    citations = build_citations(
        answer="[2] и снова [2].",
        evidence_map={},
        envelope_by_chunk={"a1": _env("a1")},
        file_key_by_run={"r1": "f"},
        sql_evidence_map={2: "a1"},
        sql_result_by_chunk={"a1": _sql("a1", "p1", "s")},
        table_candidate_by_chunk={"a1": TableCandidate(
            chunk_id="a1", payload_id="p1", score=1.0, run_id="r1")},
    )
    assert len(citations) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_citation.py -q`
Expected: FAIL (`build_deep_link` has no `tab`; `build_citations` rejects new kwargs).

- [ ] **Step 3: Implement the new citation builder**

Replace the body of `citation.py` below the module docstring and `_MARKER` with:

```python
import re
from urllib.parse import quote

from lore_retrieval.contracts import Citation, EvidenceEnvelope, SQLResult, TableCandidate

_MARKER = re.compile(r"\[(\d+)\]")


def build_deep_link(
    logical_file_key: str, run_id: str, chunk_id: str, *, tab: str = "display"
) -> str:
    return (
        f"/files?file={quote(logical_file_key, safe='')}"
        f"&run={quote(run_id, safe='')}"
        f"&chunk={quote(chunk_id, safe='')}&tab={quote(tab, safe='')}"
    )


def _text_citation(
    chunk_id: str,
    envelope: EvidenceEnvelope,
    file_key_by_run: dict[str, str],
    preview_chars: int,
    marker: int | None,
) -> Citation:
    file_key = file_key_by_run.get(envelope.run_id, envelope.run_id)
    heading = tuple(envelope.coordinates.get("heading_path") or ())
    preview = (envelope.display_text or envelope.fulltext)[:preview_chars]
    return Citation(
        chunk_id=chunk_id,
        run_id=envelope.run_id,
        logical_file_key=file_key,
        preview_text=preview,
        heading_path=heading,
        deep_link=build_deep_link(file_key, envelope.run_id, chunk_id, tab="display"),
        kind="text",
        marker=marker,
    )


def _table_citation(
    chunk_id: str,
    sql_result: SQLResult,
    candidate: TableCandidate,
    file_key_by_run: dict[str, str],
    preview_chars: int,
    marker: int | None,
) -> Citation | None:
    run_id = candidate.run_id
    if not run_id:  # no provenance -> cannot build a valid deep-link; skip
        return None
    file_key = file_key_by_run.get(run_id, run_id)
    preview = (sql_result.answer_summary or "")[:preview_chars]
    return Citation(
        chunk_id=chunk_id,
        run_id=run_id,
        logical_file_key=file_key,
        preview_text=preview,
        heading_path=candidate.heading_path,
        deep_link=build_deep_link(file_key, run_id, chunk_id, tab="payloads"),
        kind="table",
        marker=marker,
    )


def build_citations(
    answer: str,
    evidence_map: dict[int, list[str]],
    envelope_by_chunk: dict[str, EvidenceEnvelope],
    file_key_by_run: dict[str, str],
    *,
    sql_evidence_map: dict[int, str] | None = None,
    sql_result_by_chunk: dict[str, SQLResult] | None = None,
    table_candidate_by_chunk: dict[str, TableCandidate] | None = None,
    preview_chars: int = 160,
    limit: int = 8,
    fallback_limit: int = 3,
) -> list[Citation]:
    sql_evidence_map = sql_evidence_map or {}
    sql_result_by_chunk = sql_result_by_chunk or {}
    table_candidate_by_chunk = table_candidate_by_chunk or {}

    citations: list[Citation] = []
    seen_chunks: set[str] = set()
    seen_payloads: set[str] = set()

    def add_text(chunk_id: str, marker: int | None) -> None:
        if chunk_id in seen_chunks or len(citations) >= limit:
            return
        envelope = envelope_by_chunk.get(chunk_id)
        if envelope is None:
            return
        seen_chunks.add(chunk_id)
        citations.append(
            _text_citation(chunk_id, envelope, file_key_by_run, preview_chars, marker)
        )

    def add_table(anchor: str, marker: int | None) -> None:
        if len(citations) >= limit:
            return
        sql_result = sql_result_by_chunk.get(anchor)
        candidate = table_candidate_by_chunk.get(anchor)
        if sql_result is None or candidate is None:
            return
        if candidate.payload_id in seen_payloads:
            return
        cit = _table_citation(
            anchor, sql_result, candidate, file_key_by_run, preview_chars, marker
        )
        if cit is None:
            return
        seen_payloads.add(candidate.payload_id)
        citations.append(cit)

    # 1) Resolve model markers in order of first appearance.
    ordered: list[int] = []
    seen_idx: set[int] = set()
    for m in _MARKER.finditer(answer):
        idx = int(m.group(1))
        if idx not in seen_idx:
            seen_idx.add(idx)
            ordered.append(idx)
    for idx in ordered:
        if idx in evidence_map:
            for chunk_id in evidence_map[idx]:
                add_text(chunk_id, idx)
        elif idx in sql_evidence_map:
            add_table(sql_evidence_map[idx], idx)

    if citations:
        return citations

    # 2) Deterministic fallback: no resolvable markers but grounding existed ->
    #    top-N in shown order (text groups first, then SQL successes), marker=None.
    if not evidence_map and not sql_evidence_map:
        return []
    for idx in sorted(set(evidence_map) | set(sql_evidence_map)):
        if len(citations) >= fallback_limit:
            break
        if idx in evidence_map:
            for chunk_id in evidence_map[idx]:
                add_text(chunk_id, None)
        else:
            add_table(sql_evidence_map[idx], None)
    return citations
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_citation.py -q`
Expected: PASS.

- [ ] **Step 5: Package gate**

Run: `python -m pytest -q && python -m ruff check src tests && python -m mypy src`
Expected: green; no new mypy errors in `citation.py`.

- [ ] **Step 6: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/citation.py \
        lore-core/packages/lore-retrieval/tests/test_citation.py
git commit -m "feat(retrieval): build_citations resolves table markers (tab=payloads) + top-N fallback"
```

---

## Task 3: Arbitration enumerates SQL successes into the `[n]` sequence

**Files:**
- Modify: `lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/arbitration.py`
- Test: `lore-core/packages/lore-retrieval/tests/test_arbitration.py` (extend; create if absent)

**Interfaces:**
- Consumes: `AgentDecision.sql_evidence_map` (Task 1).
- Produces: `arbitrate_and_answer(...)` returns `AgentDecision` whose `sql_evidence_map` maps `G+k -> success.chunk_id` (G = len(groups)); prompt enumerates SQL with `[G+k]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_arbitration.py`:

```python
from lore_retrieval.contracts import ContextGroup, SQLResult, SQLStatus
from lore_retrieval.fakes import FakeChatModel
from lore_retrieval.pipeline.arbitration import arbitrate_and_answer


def _group(idx):
    return ContextGroup(
        document_id="d", section_id="s", section_path=("H",), scope="window",
        chunk_ids=[f"c{idx}"], start_position=0, end_position=0, text=f"group {idx}",
        group_score=1.0, citations=[f"c{idx}"],
    )


def _ok(chunk_id, payload_id, summary="s"):
    return SQLResult(payload_id=payload_id, chunk_id=chunk_id,
                     status=SQLStatus.success, rows=[{"n": 1}], answer_summary=summary)


async def test_sql_successes_continue_the_marker_sequence():
    captured = {}

    def capture(prompt):
        captured["prompt"] = prompt
        return "ответ [1] [2]"

    decision = await arbitrate_and_answer(
        FakeChatModel(capture),
        "вопрос",
        [_group(1)],                       # text -> [1]
        [_ok("a1", "p1", "итог")],         # SQL success -> [2]
    )
    assert decision.evidence_map == {1: ["c1"]}
    assert decision.sql_evidence_map == {2: "a1"}
    assert "[2] payload p1" in captured["prompt"]


async def test_sql_only_grounding_still_prompts_for_markers():
    captured = {}
    decision = await arbitrate_and_answer(
        FakeChatModel(lambda p: captured.setdefault("p", p) or "ответ [1]"),
        "вопрос", [], [_ok("a1", "p1")],
    )
    assert decision.sql_evidence_map == {1: "a1"}
    assert "[1] payload p1" in captured["p"]
    assert "маркер" in captured["p"].lower()
```

(`FakeChatModel(responder)` takes a `Callable[[str], str]` — confirmed in `fakes.py`. The suite runs plain `async def` tests without a marker, matching `test_degradation.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_arbitration.py -q`
Expected: FAIL (`sql_evidence_map` empty; SQL block has no `[n]`).

- [ ] **Step 3: Implement enumeration**

In `arbitration.py`, replace `_build_prompt` and the tail of `arbitrate_and_answer`:

```python
def _build_prompt(
    question: str,
    groups: list[ContextGroup],
    successes: list[SQLResult],
    note: str | None,
) -> str:
    parts = [f"Вопрос: {question}", ""]
    if groups:
        parts.append("Текстовые свидетельства (ссылайся на источник номером [n]):")
        parts.extend(f"[{i}] {g.text}" for i, g in enumerate(groups, 1))
    if successes:
        base = len(groups)
        parts.append("Результаты SQL (каждый отдельно, не объединять; ссылайся номером [n]):")
        parts.extend(
            f"[{base + k}] payload {r.payload_id}: {r.answer_summary}"
            for k, r in enumerate(successes, 1)
        )
    if note == "conflicting_sql_results":
        parts.append("ВНИМАНИЕ: результаты SQL расходятся — представь их раздельно.")
    if groups or successes:
        parts.append("Ставь маркер [n] к каждому утверждению из свидетельства n.")
    return "\n".join(parts)
```

In `arbitrate_and_answer`, after computing `used_sql` and the text `evidence_map`, add the SQL map and pass it to `AgentDecision`:

```python
    evidence_map = {i: list(g.citations) for i, g in enumerate(groups, 1)}
    base = len(groups)
    sql_evidence_map = {base + k: r.chunk_id for k, r in enumerate(successes, 1)}

    answer = await model.generate(_build_prompt(question, groups, successes, note))
    return AgentDecision(
        answer=answer,
        used_evidence_chunk_ids=used_evidence,
        used_sql_payload_ids=used_sql,
        citations=citations,
        note=note,
        evidence_map=evidence_map,
        sql_evidence_map=sql_evidence_map,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_arbitration.py -q`
Expected: PASS.

- [ ] **Step 5: Package gate**

Run: `python -m pytest -q && python -m ruff check src tests && python -m mypy src`
Expected: green (existing arbitration tests still pass — the text-only path is unchanged when there are no successes).

- [ ] **Step 6: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/arbitration.py \
        lore-core/packages/lore-retrieval/tests/test_arbitration.py
git commit -m "feat(retrieval): arbitration enumerates SQL successes into [n] + sql_evidence_map"
```

---

## Task 4: Table anchor provenance on `TableCandidate`

**Files:**
- Modify: `lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/table_lane.py`
- Modify: `lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/graph.py` (`_table_discover` only)
- Test: `lore-core/packages/lore-retrieval/tests/test_table_lane.py` (extend)

**Interfaces:**
- Consumes: `TableCandidate.run_id`/`heading_path` (Task 1).
- Produces: `select_table_candidates(..., provenance_by_chunk: dict[str, tuple[str, tuple[str, ...]]] | None = None)` sets `run_id`/`heading_path` on each candidate; `_table_discover` passes the anchor provenance from the loaded rows.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_table_lane.py`:

```python
from lore_retrieval.pipeline.table_lane import select_table_candidates


def test_select_table_candidates_carries_anchor_provenance():
    out = select_table_candidates(
        [("a1", 0.9)],
        {"a1": "p1"},
        provenance_by_chunk={"a1": ("run-7", ("H", "Оклады"))},
    )
    assert len(out) == 1
    assert out[0].run_id == "run-7"
    assert out[0].heading_path == ("H", "Оклады")


def test_select_table_candidates_defaults_without_provenance():
    out = select_table_candidates([("a1", 0.9)], {"a1": "p1"})
    assert out[0].run_id == "" and out[0].heading_path == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_table_lane.py -q`
Expected: FAIL (`select_table_candidates` rejects `provenance_by_chunk`).

- [ ] **Step 3: Implement provenance passthrough**

In `table_lane.py`, extend the signature and the `TableCandidate(...)` construction:

```python
def select_table_candidates(
    reranked: list[tuple[str, float]],
    payload_by_chunk: dict[str, str],
    *,
    feasible: Callable[[str], bool] | None = None,
    floor: float = 0.0,
    max_k: int = 5,
    provenance_by_chunk: dict[str, tuple[str, tuple[str, ...]]] | None = None,
) -> list[TableCandidate]:
    """Recall-first: dedup to one physical payload per slot, drop below-floor and
    infeasible schemas, cap at max_k, never pad with irrelevant candidates."""
    is_feasible = feasible or (lambda _cid: True)
    provenance = provenance_by_chunk or {}
    seen_payloads: set[str] = set()
    out: list[TableCandidate] = []
    for chunk_id, score in reranked:
        if len(out) >= max_k:
            break
        if score < floor:
            continue
        payload_id = payload_by_chunk.get(chunk_id)
        if payload_id is None or payload_id in seen_payloads:
            continue
        if not is_feasible(chunk_id):
            continue
        seen_payloads.add(payload_id)
        run_id, heading_path = provenance.get(chunk_id, ("", ()))
        out.append(TableCandidate(
            chunk_id=chunk_id, payload_id=payload_id, score=score,
            run_id=run_id, heading_path=heading_path,
        ))
    return out
```

- [ ] **Step 4: Thread provenance in `_table_discover`**

In `graph.py` `_table_discover`, after loading `tbl_chunks`, build the provenance map and pass it to `select_table_candidates`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_table_lane.py -q`
Expected: PASS.

- [ ] **Step 6: Package gate**

Run: `python -m pytest -q && python -m ruff check src tests && python -m mypy src`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/table_lane.py \
        lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/graph.py \
        lore-core/packages/lore-retrieval/tests/test_table_lane.py
git commit -m "feat(retrieval): TableCandidate carries anchor run_id/heading from the loaded row"
```

---

## Task 5: Wire `_cite`/`summarize` to build text + table citations, thread through the graph

**Files:**
- Modify: `lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/graph.py` (`summarize`, `_cite`, `answer`)
- Modify: `lore-core/services/lore-chat/agents/grounded.py` (`summarize` node — one line)
- Test: `lore-core/packages/lore-retrieval/tests/test_pipeline.py` (extend)

**Interfaces:**
- Consumes: `build_citations(...)` (Task 2), `arbitrate_and_answer` (Task 3), enriched `TableCandidate` (Task 4).
- Produces: `summarize(question, groups, resolution, sql_results, table_candidates)`; `_cite(decision, envelopes, sql_results, table_candidates)`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline.py` an end-to-end table-citation test using the in-memory fakes (mirror the existing pipeline test's fixture; a table-typed chunk with a `payload_refs` entry must be in the corpus so the table lane surfaces it, and `FakeChatModel` must answer with the SQL marker). Concretely:

```python
async def test_answer_emits_table_citation_when_sql_grounds(table_pipeline):
    # table_pipeline: a RetrievalPipeline whose corpus has a table_payload chunk
    # with payload_refs=[{"payload_id": "p1"}], a FakeSqlRunner returning a success
    # for p1, and a FakeChatModel that answers "итог [1]" (single SQL evidence).
    result = await table_pipeline.answer("сколько окладов")
    table_cites = [c for c in result.citations if c.kind == "table"]
    assert table_cites, result.citations
    assert table_cites[0].deep_link.endswith("&tab=payloads")
    assert table_cites[0].run_id  # provenance resolved from the loaded anchor row
```

If the existing `test_pipeline.py` has no table fixture, add a `table_pipeline` fixture built from the same fakes used by `test_degradation.py`'s `_pipeline`, seeding a `SourceChunk(chunk_type="table_payload", payload_refs=[{"payload_id": "p1"}], run_id="r1", ...)` and a `FakeSqlRunner({"p1": <success>})`. Reuse `build_structural_projection` as that file does.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pipeline.py -q`
Expected: FAIL (citations contain no `kind="table"` entry — `_cite` ignores SQL evidence).

- [ ] **Step 3: Implement the wiring**

In `graph.py`, update `answer` to pass `table_candidates` into `summarize`:

```python
        decision, citations = await self.summarize(
            question, groups, resolution, sql_results, table_candidates
        )
```

Update `summarize` and `_cite`:

```python
    async def summarize(self, question, groups, resolution, sql_results, table_candidates):
        """Stage 3: top-level arbitration (final answer) + citation resolution."""
        decision = await arbitrate_and_answer(self._chat_model, question, groups, sql_results)
        self._tracer.record(
            "arbitration",
            {"note": decision.note, "used_sql": len(decision.used_sql_payload_ids)},
        )
        citations = await self._cite(
            decision, resolution.resolved, sql_results, table_candidates
        )
        return decision, citations

    async def _cite(self, decision, envelopes, sql_results, table_candidates):
        """Dedicated cite step: resolve the model's [n] markers (text + table) into
        Citations, with a deterministic top-N fallback when nothing resolved."""
        if not decision.evidence_map and not decision.sql_evidence_map:
            return []
        envelope_by_chunk = {e.chunk_id: e for e in envelopes}
        sql_result_by_chunk = {r.chunk_id: r for r in sql_results}
        table_candidate_by_chunk = {c.chunk_id: c for c in table_candidates}
        run_ids = {e.run_id for e in envelopes}
        run_ids |= {c.run_id for c in table_candidates if c.run_id}
        file_key_by_run = (
            await self._file_key_resolver.resolve(list(run_ids))
            if self._file_key_resolver
            else {}
        )
        citations = build_citations(
            decision.answer,
            decision.evidence_map,
            envelope_by_chunk,
            file_key_by_run,
            sql_evidence_map=decision.sql_evidence_map,
            sql_result_by_chunk=sql_result_by_chunk,
            table_candidate_by_chunk=table_candidate_by_chunk,
            preview_chars=self._citation_preview_chars,
            limit=self._citation_limit,
        )
        self._tracer.record("cite", {"citations": len(citations)})
        return citations
```

- [ ] **Step 4: Update the lore-chat grounded `summarize` node**

In `services/lore-chat/agents/grounded.py`, the `summarize` node calls `pipeline.summarize(...)`. Pass `table_candidates` from state:

```python
            decision, citations = await pipeline.summarize(
                _question(state["messages"]),
                state.get("groups", []),
                state["resolution"],
                state.get("sql_results", []),
                state.get("table_candidates", []),
            )
```

(Match the exact positional args already present in that node; the only change is appending `state.get("table_candidates", [])`.)

- [ ] **Step 5: Run tests to verify they pass**

Run (retrieval): `python -m pytest -q`
Expected: PASS incl. the new pipeline test; existing pipeline/degradation tests still pass (text-only answers unchanged).

- [ ] **Step 6: lore-chat gate**

Run: `cd lore-core && source .venv/bin/activate && python -m pytest services/lore-chat/tests -q`
Expected: PASS (grounded graph still wires; the extra positional arg is accepted).

- [ ] **Step 7: Full backend gate + commit**

```bash
cd lore-core/packages/lore-retrieval && python -m ruff check src tests && python -m mypy src
cd /Users/stamplevskiyd/development/lore
git add lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/graph.py \
        lore-core/packages/lore-retrieval/tests/test_pipeline.py \
        lore-core/services/lore-chat/agents/grounded.py
git commit -m "feat(retrieval): cite step resolves table citations + fallback; thread table_candidates through summarize"
```

---

## Task 6: Frontend contract — `kind` + `marker` on the TS Citation

**Files:**
- Modify: `frontend/src/chat/citations.ts`
- Test: `frontend/src/chat/citations.test.ts` (extend)

**Interfaces:**
- Produces: `Citation` gains `kind: "text" | "table"` and `marker: number | null`; `extractCitations` maps them (defaults `"text"`/`null`).

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/chat/citations.test.ts`:

```ts
it("maps kind and marker from metadata, defaulting to text/null", () => {
  const step = {
    metadata: {
      citations: [
        { chunk_id: "a1", deep_link: "/files?...&tab=payloads", kind: "table", marker: 2 },
        { chunk_id: "c1", deep_link: "/files?...&tab=display" }, // legacy shape
      ],
    },
  } as unknown as IStep;
  const out = extractCitations(step);
  expect(out[0].kind).toBe("table");
  expect(out[0].marker).toBe(2);
  expect(out[1].kind).toBe("text");
  expect(out[1].marker).toBeNull();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && nvm use 22 && npx vitest run src/chat/citations.test.ts`
Expected: FAIL (`kind`/`marker` undefined).

- [ ] **Step 3: Implement the mapping**

In `citations.ts`, extend the interface, the raw shape, and `toCitation`:

```ts
export interface Citation {
  chunkId: string;
  runId: string;
  logicalFileKey: string;
  previewText: string;
  headingPath: string[];
  deepLink: string;
  kind: "text" | "table";
  marker: number | null;
}

interface RawCitation {
  chunk_id?: unknown;
  run_id?: unknown;
  logical_file_key?: unknown;
  preview_text?: unknown;
  heading_path?: unknown;
  deep_link?: unknown;
  kind?: unknown;
  marker?: unknown;
}
```

In `toCitation`, before the `return`, derive the two fields and include them:

```ts
  const kind: Citation["kind"] = raw.kind === "table" ? "table" : "text";
  const marker = typeof raw.marker === "number" ? raw.marker : null;
  return {
    chunkId,
    runId: asString(raw.run_id),
    logicalFileKey: asString(raw.logical_file_key),
    previewText: asString(raw.preview_text),
    headingPath: Array.isArray(raw.heading_path) ? raw.heading_path.map(asString) : [],
    deepLink,
    kind,
    marker,
  };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/chat/citations.test.ts`
Expected: PASS.

- [ ] **Step 5: Typecheck + commit**

```bash
npx tsc -b
cd /Users/stamplevskiyd/development/lore
git add frontend/src/chat/citations.ts frontend/src/chat/citations.test.ts
git commit -m "feat(chat): Citation kind/marker in the frontend extractor"
```

---

## Task 7: Table-kind icon on the citation card + jump target id

**Files:**
- Modify: `frontend/src/components/Citations/Citations.tsx`
- Modify: `frontend/src/components/Citations/Citations.module.css` (only if a highlight class is added here; see Task 8)

**Interfaces:**
- Consumes: `Citation.kind`, `Citation.marker` (Task 6).
- Produces: table cards render a `Table` icon; each card gets `id={marker != null ? \`citation-${marker}\` : undefined}` as the superscript jump target.

- [ ] **Step 1: Update the component**

In `Citations.tsx`, import the table icon and branch by kind, and set the card id:

```tsx
import { FileText, Table } from "lucide-react";
```

In the `.map`, set the `<li>` id and choose the icon:

```tsx
        {items.map((c, i) => (
          <li key={`${c.chunkId}-${i}`} id={c.marker != null ? `citation-${c.marker}` : undefined}>
            <button
              type="button"
              className={styles.card}
              onClick={() => navigateTo(c.deepLink)}
              title={c.kind === "table" ? "Открыть таблицу в просмотрщике файлов" : "Открыть источник в просмотрщике файлов"}
            >
              <span className={styles.head}>
                {c.kind === "table" ? (
                  <Table size={14} className={styles.icon} aria-hidden />
                ) : (
                  <FileText size={14} className={styles.icon} aria-hidden />
                )}
                <span className={styles.heading}>{cardLabel(c)}</span>
              </span>
              {c.previewText ? <span className={styles.preview}>{c.previewText}</span> : null}
            </button>
          </li>
        ))}
```

- [ ] **Step 2: Typecheck + full frontend suite**

Run: `cd frontend && nvm use 22 && npx tsc -b && npx vitest run`
Expected: green (no test asserts the icon; this is a presentational change — the existing Citations usage still compiles and renders).

- [ ] **Step 3: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add frontend/src/components/Citations/Citations.tsx
git commit -m "feat(chat): table citation cards use a table icon + carry a marker jump-target id"
```

---

## Task 8: Inline `[n]` superscripts in the answer text

**Files:**
- Create: `frontend/src/chat/citationMarkers.ts`
- Test: `frontend/src/chat/citationMarkers.test.ts` (create)
- Modify: `frontend/src/components/AssistantMessage/AssistantMessage.tsx`
- Modify: `frontend/src/components/Citations/Citations.module.css` (highlight animation)

**Interfaces:**
- Consumes: `Citation.marker` (Task 6); card ids `citation-<marker>` (Task 7).
- Produces: `rehypeCitationMarkers(validMarkers: Set<number>)` — a rehype plugin turning `[n]` text (for n in `validMarkers`, outside `code`/`pre`) into `<sup class="citationMarker" data-marker="n">n</sup>`; `AssistantMessage` renders these as buttons that scroll to `#citation-<n>`.

- [ ] **Step 1: Write the failing test for the rehype transform**

Create `frontend/src/chat/citationMarkers.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import rehypeStringify from "rehype-stringify";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { unified } from "unified";
import { rehypeCitationMarkers } from "./citationMarkers";

const render = (md: string, markers: number[]) =>
  unified()
    .use(remarkParse)
    .use(remarkRehype)
    .use(rehypeCitationMarkers, new Set(markers))
    .use(rehypeStringify)
    .processSync(md)
    .toString();

describe("rehypeCitationMarkers", () => {
  it("wraps a known [n] in a sup with data-marker", () => {
    const html = render("Итог [2] верный.", [2]);
    expect(html).toContain('<sup class="citationMarker" data-marker="2">2</sup>');
  });

  it("leaves unknown markers as plain text", () => {
    const html = render("Ссылка [9].", [2]);
    expect(html).not.toContain("<sup");
    expect(html).toContain("[9]");
  });

  it("does not touch markers inside code", () => {
    const html = render("`arr[2]`", [2]);
    expect(html).not.toContain("<sup");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && nvm use 22 && npx vitest run src/chat/citationMarkers.test.ts`
Expected: FAIL (`citationMarkers` module not found). If `unified`/`remark-parse`/`rehype-stringify` are not already dev-deps, they ship transitively with react-markdown; if the import fails, add them: `npm i -D unified remark-parse remark-rehype rehype-stringify` (they are already in the react-markdown tree, so this is usually a no-op).

- [ ] **Step 3: Implement the rehype plugin**

Create `frontend/src/chat/citationMarkers.ts`:

```ts
import { visit } from "unist-util-visit";
import type { Root, Element, Text } from "hast";

const MARKER = /\[(\d+)\]/g;

/**
 * Rehype transform: turn `[n]` text into a clickable <sup> when n is a known
 * citation marker, skipping code/pre so `arr[2]` stays literal. A `[n]` with no
 * matching citation is left as plain text (never a dead link).
 */
export function rehypeCitationMarkers(validMarkers: Set<number>) {
  return (tree: Root) => {
    visit(tree, "text", (node: Text, index, parent) => {
      if (
        index === null ||
        !parent ||
        (parent.type === "element" &&
          ((parent as Element).tagName === "code" || (parent as Element).tagName === "pre"))
      ) {
        return;
      }
      const value = node.value;
      if (!MARKER.test(value)) return;
      MARKER.lastIndex = 0;

      const children: (Text | Element)[] = [];
      let last = 0;
      for (let m = MARKER.exec(value); m !== null; m = MARKER.exec(value)) {
        const n = Number(m[1]);
        if (!validMarkers.has(n)) continue;
        if (m.index > last) children.push({ type: "text", value: value.slice(last, m.index) });
        children.push({
          type: "element",
          tagName: "sup",
          properties: { className: ["citationMarker"], "data-marker": n },
          children: [{ type: "text", value: String(n) }],
        });
        last = m.index + m[0].length;
      }
      if (!children.length) return;
      if (last < value.length) children.push({ type: "text", value: value.slice(last) });
      (parent.children as unknown[]).splice(index, 1, ...children);
      return index + children.length;
    });
  };
}
```

- [ ] **Step 4: Run the transform tests**

Run: `npx vitest run src/chat/citationMarkers.test.ts`
Expected: PASS.

- [ ] **Step 5: Wire the plugin + `sup` renderer into `AssistantMessage`**

In `AssistantMessage.tsx`: build the valid-marker set from `citations`, pass the plugin to `ReactMarkdown` via `rehypePlugins`, and render `sup[data-marker]` as a button that scrolls to the card. Add near the existing `steps/citations/warnings` derivation:

```tsx
import { rehypeCitationMarkers } from "../../chat/citationMarkers";

// inside the component, after `const citations = ...`
const markerSet = new Set(
  citations.map((c) => c.marker).filter((m): m is number => m != null),
);
const jumpToCitation = (marker: number) => {
  const el = document.getElementById(`citation-${marker}`);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add(styles.flash);
  window.setTimeout(() => el.classList.remove(styles.flash), 1200);
};
```

Extend the `ReactMarkdown` usage (the element that renders the answer body) with the plugin and a `sup` component override:

```tsx
<ReactMarkdown
  remarkPlugins={REMARK_PLUGINS}
  rehypePlugins={markerSet.size ? [[rehypeCitationMarkers, markerSet]] : []}
  components={{
    sup: ({ node, ...props }) => {
      const marker = node?.properties?.dataMarker;
      if (marker == null) return <sup {...props} />;
      const n = Number(marker);
      return (
        <sup
          className={styles.citationMarker}
          role="button"
          tabIndex={0}
          onClick={() => jumpToCitation(n)}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && jumpToCitation(n)}
        >
          {n}
        </sup>
      );
    },
  }}
>
  {answerText}
</ReactMarkdown>
```

(Use the existing markdown-children variable name in this file for `{answerText}`, and keep any existing `components` entries — merge the `sup` key in. `styles.flash` and `styles.citationMarker` are added next.)

- [ ] **Step 6: Add the styles**

In `Citations.module.css` (or `AssistantMessage.module.css` if the flash target lives there — the card is in `Citations`, so put `.flash` where the `<li>` is styled; put `.citationMarker` wherever `AssistantMessage` styles live). Minimal:

```css
.citationMarker {
  cursor: pointer;
  color: var(--accent, #4c7dff);
  font-weight: 600;
  padding: 0 1px;
}
.flash {
  animation: citation-flash 1.2s ease-out;
}
@keyframes citation-flash {
  from { background: rgba(76, 125, 255, 0.25); }
  to { background: transparent; }
}
```

Import the correct module in each component (`Citations.module.css` already imported in `Citations.tsx`; `AssistantMessage` already imports its own `styles`). Reference `styles.citationMarker` from whichever module you place it in.

- [ ] **Step 7: Full frontend gate**

Run: `cd frontend && nvm use 22 && npx tsc -b && npx vitest run`
Expected: green (all suites incl. the new marker test; existing AssistantMessage/citations tests still pass).

- [ ] **Step 8: Commit**

```bash
cd /Users/stamplevskiyd/development/lore
git add frontend/src/chat/citationMarkers.ts frontend/src/chat/citationMarkers.test.ts \
        frontend/src/components/AssistantMessage/AssistantMessage.tsx \
        frontend/src/components/Citations/Citations.module.css
git commit -m "feat(chat): inline [n] superscripts jump to the matching citation card"
```

---

## Final verification (after all tasks)

- [ ] Backend: `cd lore-core/packages/lore-retrieval && source ../../.venv/bin/activate && python -m pytest -q && python -m ruff check src tests && python -m mypy src` — green / no new mypy vs baseline.
- [ ] lore-chat: `cd lore-core && python -m pytest services/lore-chat/tests -q` — green.
- [ ] Frontend: `cd frontend && nvm use 22 && npx vitest run && npx tsc -b` — green.
- [ ] `git status` — no stray files staged; `test.txt` still untracked and uncommitted.
- [ ] Update the memory backlog: mark grounded-graph-backlog #4 (table citations) and neo4j-milestone Phase D done, noting the live-verify-over-VPN follow-up.

## Notes / risks

- The retrieval read repo has no live DB test; the pipeline tasks are covered by fakes. A live smoke (`spikes/full_cycle_demo.py` or the `knowledge_base` tool over VPN) is recommended to confirm a real table answer produces a `tab=payloads` citation and the superscript jumps — do this once the two wg tunnels are up.
- If `FakeChatModel`/`ContextGroup`/fixture constructors differ from the snippets, match the versions in `fakes.py`/`test_degradation.py` — those files are the source of truth for the in-memory pipeline.
- Keep the text-only path byte-identical in behaviour: every new backend param defaults to empty, so existing arbitration/cite tests must stay green without edits.
