# Unified execution-trace {input, output} Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every block of the chat "ход выполнения" show, uniformly, what it received (`input`) and what it produced (`output`) — including the arbitration answer text, citations, and the toast SQL input/preview — so a new tool needs no display rewrite.

**Architecture:** A `{input, output}` convention emitted by every block (tracer stages via `stage_io(...)`, grounded nodes via a returned `node_io`), split generically onto the Chainlit step by pure helpers in `run_trace.py`, truncated only at render. The frontend already renders `step.input`/`step.output`, so it needs no code change.

**Tech Stack:** Python 3 (pytest, LangGraph, Chainlit), TypeScript/React (Vitest 3 on Node 22), pydantic contracts.

## Global Constraints

- Run Python tests with `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest` from the package/service dir (system `python`/`python3` lacks pytest-asyncio).
- Run frontend tests with Node 22: `export PATH="/Users/stamplevskiyd/.nvm/versions/node/v22.23.1/bin:$PATH"` then `npx vitest run` from `frontend/`.
- Truncation happens ONLY at render (`run_trace.preview`); tracer/Langfuse keep full data.
- `preview` must never throw on non-serializable data → `json.dumps(..., default=str)`.
- Back-compat: trace entries WITHOUT `input`/`output` keys keep rendering their whole `data` as `.output`. Do not break un-migrated stages.
- Preview cap: env `TRACE_PREVIEW_CHARS`, default `2000`, marker `…(+N chars)`.

---

### Task 1: `stage_io` helper (lore-retrieval)

**Files:**
- Modify: `lore-core/packages/lore-retrieval/src/lore_retrieval/observability.py`
- Test: `lore-core/packages/lore-retrieval/tests/test_observability.py`

**Interfaces:**
- Produces: `stage_io(*, input=None, output=None) -> dict` returning `{"input": input, "output": output}`.

- [ ] **Step 1: Write the failing test**

Append to `lore-core/packages/lore-retrieval/tests/test_observability.py`:

```python
from lore_retrieval.observability import stage_io


def test_stage_io_shapes_input_and_output():
    assert stage_io(input={"q": "x"}, output={"n": 1}) == {
        "input": {"q": "x"},
        "output": {"n": 1},
    }


def test_stage_io_defaults_to_none():
    assert stage_io() == {"input": None, "output": None}
    assert stage_io(output={"a": 1}) == {"input": None, "output": {"a": 1}}
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `lore-core/packages/lore-retrieval`): `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest tests/test_observability.py -q`
Expected: FAIL with `ImportError: cannot import name 'stage_io'`.

- [ ] **Step 3: Implement**

In `observability.py`, add at the end of the file:

```python
def stage_io(*, input=None, output=None) -> dict:
    """Uniform trace payload: what a block received and produced. Emit this from
    every tracer.record() so the renderer can show input/output generically."""
    return {"input": input, "output": output}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest tests/test_observability.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/observability.py \
        lore-core/packages/lore-retrieval/tests/test_observability.py
git commit -m "feat(observability): add stage_io {input, output} trace helper

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Generic render helpers + node_io plumbing (lore-chat)

**Files:**
- Modify: `lore-core/services/lore-chat/run_trace.py`
- Modify: `lore-core/services/lore-chat/app.py:184-210` (`_render_run_steps`)
- Test: `lore-core/services/lore-chat/tests/test_run_trace.py`

**Interfaces:**
- Produces: `run_trace.preview(obj, cap=None) -> str`; `run_trace.step_io_fields(data, cap=None) -> tuple[str | None, str]`; `iter_node_updates(payload)` now yields `(node_name, messages, node_io)` (3-tuple, `node_io` is a `{"input","output"}` dict or `None`).

- [ ] **Step 1: Write the failing tests**

In `lore-core/services/lore-chat/tests/test_run_trace.py`, replace `test_iter_node_updates_yields_node_and_messages` and append new tests:

```python
def test_iter_node_updates_yields_node_messages_and_node_io():
    payload = {"summarize": {"messages": [HumanMessage(content="x")],
                             "node_io": {"input": {"q": 1}, "output": {"answer": "a"}}}}
    got = [(n, len(m), io) for n, m, io in iter_node_updates(payload)]
    assert got == [("summarize", 1, {"input": {"q": 1}, "output": {"answer": "a"}})]
    # node without node_io yields None; non-dict payload yields nothing
    assert [io for _, _, io in iter_node_updates({"tools": {"messages": []}})] == [None]
    assert list(iter_node_updates("not-a-dict")) == []


def test_preview_passes_through_small_and_truncates_large():
    from run_trace import preview
    assert '"n": 1' in preview({"n": 1}, cap=100)
    big = preview({"s": "x" * 500}, cap=50)
    assert len(big) <= 50 + len("\n…(+9999 chars)")
    assert "…(+" in big


def test_preview_survives_non_serializable():
    from run_trace import preview
    assert "object" in preview({"o": object()}, cap=500)  # default=str, no throw


def test_step_io_fields_splits_input_output_entries():
    from run_trace import step_io_fields
    inp, out = step_io_fields({"input": {"q": "x"}, "output": {"answer": "a"}}, cap=200)
    assert inp is not None and '"q": "x"' in inp
    assert '"answer": "a"' in out


def test_step_io_fields_omits_input_when_none():
    from run_trace import step_io_fields
    inp, out = step_io_fields({"input": None, "output": {"n": 1}}, cap=200)
    assert inp is None
    assert '"n": 1' in out


def test_step_io_fields_legacy_entry_renders_whole_data_as_output():
    from run_trace import step_io_fields
    inp, out = step_io_fields({"fused": 5, "degraded": []}, cap=200)
    assert inp is None
    assert '"fused": 5' in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `lore-core/services/lore-chat`): `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest tests/test_run_trace.py -q`
Expected: FAIL — `iter_node_updates` yields 2-tuples (unpack error) and `preview`/`step_io_fields` don't exist.

- [ ] **Step 3: Implement the pure helpers + 3-tuple in `run_trace.py`**

At the top of `run_trace.py`, replace `from typing import Any` with:

```python
import json
import os
from typing import Any
```

Add these helpers above `class ToolCallTracker`:

```python
def preview(obj: Any, cap: int | None = None) -> str:
    """JSON-serialize `obj` (Unicode kept) and truncate to `cap` chars with a
    `…(+N chars)` marker. Truncation is display-only; never throws."""
    if cap is None:
        cap = int(os.getenv("TRACE_PREVIEW_CHARS", "2000"))
    text = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n…(+{len(text) - cap} chars)"


def step_io_fields(data: Any, cap: int | None = None) -> tuple[str | None, str]:
    """(input_text_or_None, output_text) for a trace entry. Uniform {input, output}
    entries split onto the step's input/output; legacy count-only entries render
    the whole data as output (back-compat)."""
    if isinstance(data, dict) and ("input" in data or "output" in data):
        inp = data.get("input")
        out = data.get("output")
        input_text = preview(inp, cap) if inp is not None else None
        return input_text, preview(out, cap)
    return None, preview(data, cap)
```

Replace `iter_node_updates` with the 3-tuple version:

```python
def iter_node_updates(payload: Any):
    """Yield ``(node_name, messages, node_io)`` from one LangGraph ``updates`` payload.

    Shape is ``{node_name: {"messages": [...], "node_io": {...}, ...}}``. Non-dict
    payloads / nodes without those keys yield empty messages / ``None`` node_io."""
    if not isinstance(payload, dict):
        return
    for node_name, delta in payload.items():
        if isinstance(delta, dict):
            messages = delta.get("messages", [])
            node_io = delta.get("node_io")
        else:
            messages = []
            node_io = None
        yield node_name, messages, node_io
```

- [ ] **Step 4: Wire `_render_run_steps` in `app.py`**

Add to `app.py` imports (find the existing `from run_trace import ...` line and extend it):

```python
from run_trace import ToolCallTracker, iter_node_updates, step_io_fields
```

Replace the body of `_render_run_steps` (lines 194-210) with:

```python
    trace = (container or {}).get("trace") or []
    cursor = (container or {}).get("_trace_cursor", 0)
    for node_name, msgs, node_io in iter_node_updates(payload):
        events = tracker.observe(msgs)
        new_trace = trace[cursor:]
        cursor = len(trace)
        async with cl.Step(name=node_name, type="run") as node_step:
            if node_io:
                inp, out = step_io_fields(node_io)
                if inp is not None:
                    node_step.input = inp
                node_step.output = out
            for ev in events:
                async with cl.Step(name=ev["name"], type="tool") as tool_step:
                    tool_step.input = json.dumps(ev["args"], ensure_ascii=False, indent=2)
                    tool_step.output = ev["result"]
            for te in new_trace:
                name, step_type = _trace_step_meta(te)
                async with cl.Step(name=name, type=step_type) as stage_step:
                    inp, out = step_io_fields(te.get("data", {}))
                    if inp is not None:
                        stage_step.input = inp
                    stage_step.output = out
    if container is not None:
        container["_trace_cursor"] = cursor
```

- [ ] **Step 5: Run tests + import check**

Run (from `lore-core/services/lore-chat`):
`/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest tests/test_run_trace.py tests/test_app_imports.py -q`
Expected: PASS (app still imports; run_trace tests green).

- [ ] **Step 6: Commit**

```bash
git add lore-core/services/lore-chat/run_trace.py lore-core/services/lore-chat/app.py \
        lore-core/services/lore-chat/tests/test_run_trace.py
git commit -m "feat(trace): generic input/output render + node_io plumbing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Enrich arbitration + cite stages (lore-retrieval)

**Files:**
- Modify: `lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/graph.py` (`summarize` ~142-152, `_cite` ~154-181)
- Test: `lore-core/packages/lore-retrieval/tests/test_trace_io.py` (create)

**Interfaces:**
- Consumes: `stage_io` (Task 1), `RecordingTracer` (existing).
- Produces: `arbitration` trace `output` carries the full `answer` + `note`; `cite` trace `output` carries a `citations` list of `{marker, file, chunk, kind, preview}`.

- [ ] **Step 1: Write the failing test**

Create `lore-core/packages/lore-retrieval/tests/test_trace_io.py`:

```python
from lore_retrieval.fakes import (
    FakeChatModel,
    FakeReranker,
    FakeSqlRunner,
    InMemoryChunkContextLoader,
    InMemoryChunkSearchBackend,
    InMemoryEvidenceResolver,
    InMemoryGraphExpansion,
)
from lore_retrieval.observability import RecordingTracer
from lore_retrieval.pipeline.graph import RetrievalPipeline
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import SourceChunk

CORPUS = [
    SourceChunk(chunk_id="c1", document_id="d", run_id="d", chunk_type="text", position=1,
                heading_path=("Root", "Премия"), vector_text="премия формула",
                fulltext="премия формула", display_text="премия формула",
                vector_text_hash="h", fulltext_hash="h"),
]


def _pipeline(tracer):
    projection = build_structural_projection(CORPUS)
    backend = InMemoryChunkSearchBackend(CORPUS)
    return RetrievalPipeline(
        chunk_search=backend, graph_expansion=InMemoryGraphExpansion(projection),
        reranker=FakeReranker(), resolver=InMemoryEvidenceResolver(CORPUS),
        table_search=backend, sql_runner=FakeSqlRunner({}),
        chat_model=FakeChatModel(lambda _p: "ответ по премии [1]"),
        context_loader=InMemoryChunkContextLoader(CORPUS),
        tracer=tracer,
    )


async def test_arbitration_trace_carries_answer_text():
    tracer = RecordingTracer()
    await _pipeline(tracer).answer("премия формула")
    arb = next(data for stage, data in tracer.events if stage == "arbitration")
    assert arb["output"]["answer"] == "ответ по премии [1]"
    assert "input" in arb and "question" in arb["input"]


async def test_cite_trace_carries_citation_list():
    tracer = RecordingTracer()
    await _pipeline(tracer).answer("премия формула")
    cite = next(data for stage, data in tracer.events if stage == "cite")
    cits = cite["output"]["citations"]
    assert isinstance(cits, list) and cits
    assert set(cits[0]) >= {"marker", "file", "chunk", "kind", "preview"}
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `lore-core/packages/lore-retrieval`): `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest tests/test_trace_io.py -q`
Expected: FAIL — arbitration `data` is `{note, used_sql}` (no `output.answer`); cite `data` is `{citations: <int>}`.

- [ ] **Step 3: Implement in `graph.py`**

Add `stage_io` to the observability import (find `from lore_retrieval.observability import NullTracer` and change to):

```python
from lore_retrieval.observability import NullTracer, stage_io
```

In `summarize`, replace the arbitration record:

```python
        self._tracer.record(
            "arbitration",
            {"note": decision.note, "used_sql": len(decision.used_sql_payload_ids)},
        )
```

with:

```python
        self._tracer.record(
            "arbitration",
            stage_io(
                input={
                    "question": question,
                    "groups": [
                        {"section_path": list(g.section_path), "preview": g.text[:200]}
                        for g in groups
                    ],
                    "sql": [
                        {"payload_id": r.payload_id, "answer_summary": r.answer_summary}
                        for r in sql_results
                    ],
                },
                output={"answer": decision.answer, "note": decision.note},
            ),
        )
```

In `_cite`, replace the cite record:

```python
        self._tracer.record("cite", {"citations": len(citations)})
```

with:

```python
        self._tracer.record(
            "cite",
            stage_io(
                input={
                    "has_evidence_map": bool(decision.evidence_map),
                    "has_sql_map": bool(decision.sql_evidence_map),
                },
                output={
                    "citations": [
                        {
                            "marker": c.marker,
                            "file": c.logical_file_key,
                            "chunk": c.chunk_id,
                            "kind": c.kind,
                            "preview": c.preview_text,
                        }
                        for c in citations
                    ]
                },
            ),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest tests/test_trace_io.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lore-core/packages/lore-retrieval/src/lore_retrieval/pipeline/graph.py \
        lore-core/packages/lore-retrieval/tests/test_trace_io.py
git commit -m "feat(trace): arbitration + cite carry answer text and citation list

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Enrich toast SQL trace entry (lore-chat)

**Files:**
- Modify: `lore-core/services/lore-chat/toast_binding.py:93-103`
- Test: `lore-core/services/lore-chat/tests/test_toast_binding.py`

**Interfaces:**
- Consumes: `stage_io` (Task 1).
- Produces: `_sql_trace_entry(table, question, attempt) -> {"stage": "sql", "data": {"input": {...}, "output": {...}}}`.

- [ ] **Step 1: Write the failing test**

Append to `lore-core/services/lore-chat/tests/test_toast_binding.py`:

```python
def test_sql_trace_entry_carries_input_and_output():
    from toast_binding import _sql_trace_entry

    entry = _sql_trace_entry(
        "toast_tbl_x", "сколько юристов?",
        {"sql": "SELECT count(*)", "ok": True, "row_count": 3, "error": None},
    )
    assert entry["stage"] == "sql"
    assert entry["data"]["input"] == {"table": "toast_tbl_x", "question": "сколько юристов?"}
    out = entry["data"]["output"]
    assert out["sql"] == "SELECT count(*)"
    assert out["ok"] is True and out["rows"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `lore-core/services/lore-chat`): `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest tests/test_toast_binding.py -q`
Expected: FAIL — `_sql_trace_entry` does not exist.

- [ ] **Step 3: Implement in `toast_binding.py`**

Add `stage_io` to imports (near the top, with the other `lore_retrieval` imports):

```python
from lore_retrieval.observability import stage_io
```

Add the helper above `def _run(`:

```python
def _sql_trace_entry(table: str, question: str, attempt: dict) -> dict:
    """Uniform trace entry for one SQL attempt: input (table + question) and output
    (generated SQL + execution result)."""
    return {
        "stage": "sql",
        "data": stage_io(
            input={"table": table, "question": question},
            output={
                "sql": attempt.get("sql", ""),
                "ok": attempt.get("ok"),
                "rows": attempt.get("row_count", 0),
                "error": attempt.get("error"),
            },
        ),
    }
```

Replace the sink-append loop:

```python
    sink = trace_sink.get()
    if sink is not None:
        for a in state.get("attempts", []):
            sink.append({"stage": "sql", "data": {
                "table": request.payload_id,
                "sql": a.get("sql", ""),
                "ok": a.get("ok"),
                "rows": a.get("row_count", 0),
                "error": a.get("error"),
            }})
```

with:

```python
    sink = trace_sink.get()
    if sink is not None:
        for a in state.get("attempts", []):
            sink.append(_sql_trace_entry(request.payload_id, request.question, a))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest tests/test_toast_binding.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add lore-core/services/lore-chat/toast_binding.py \
        lore-core/services/lore-chat/tests/test_toast_binding.py
git commit -m "feat(trace): toast SQL entry carries input (table+question) and output

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Grounded nodes emit `node_io` (lore-chat)

**Files:**
- Modify: `lore-core/services/lore-chat/agents/grounded.py`
- Test: `lore-core/services/lore-chat/tests/test_grounded.py`

**Interfaces:**
- Consumes: `stage_io` (Task 1).
- Produces: each grounded node returns a `node_io={"input":..., "output":...}` key in its state delta. `*_detail` keys are retained (Studio); `node_io.output` reuses/echoes them. `summarize`'s `node_io.output` carries `{answer, note, citations:[...]}`.

- [ ] **Step 1: Write the failing test**

Append to `lore-core/services/lore-chat/tests/test_grounded.py`:

```python
def test_nodes_emit_node_io_input_and_output():
    """Each node yields a uniform node_io (input+output) in its update, so the
    chat trace can render input/output for every block."""
    pipe = _FakePipe()
    agent = build_grounded_agent(pipe)

    async def _collect():
        seen = {}
        async for delta in agent.astream(
            {"messages": [HumanMessage(content="ФИО юристов?")]}, stream_mode="updates"
        ):
            for node, d in delta.items():
                if isinstance(d, dict) and "node_io" in d:
                    seen[node] = d["node_io"]
        return seen

    seen = asyncio.run(_collect())
    # every executed node produced a node_io with both keys
    assert {"neo4j_retrieve", "toast_sql", "summarize"} <= set(seen)
    for io in seen.values():
        assert set(io) == {"input", "output"}
    # summarize output carries the actual answer text + a citations list
    assert seen["summarize"]["output"]["answer"] == "Каневский — Помощник Юриста"
    assert isinstance(seen["summarize"]["output"]["citations"], list)
    # neo4j_retrieve input carries the question
    assert seen["neo4j_retrieve"]["input"]["question"] == "ФИО юристов?"
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `lore-core/services/lore-chat`): `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest tests/test_grounded.py::test_nodes_emit_node_io_input_and_output -q`
Expected: FAIL — nodes don't return `node_io`.

- [ ] **Step 3: Implement in `grounded.py`**

Add the import at the top (with the other imports):

```python
from lore_retrieval.observability import stage_io
```

Add `node_io: dict` to the `GroundedState` TypedDict (with the other fields):

```python
    node_io: dict
```

In `neo4j_retrieve`, add `node_io` to the returned dict (keep everything else):

```python
        detail = {
            "context_groups": len(groups),
            "resolved_evidence": len(resolution.resolved),
            "rejected_evidence": len(resolution.rejected),
            "table_candidates": [
                {"table": tc.payload_id, "chunk": tc.chunk_id, "score": round(tc.score, 4)}
                for tc in table_candidates
            ],
            "degradations": degradations,
        }
        return {
            "groups": groups,
            "resolution": resolution,
            "table_candidates": table_candidates,
            "degradations": degradations,
            "neo4j_detail": detail,
            "node_io": stage_io(
                input={"question": _question(state["messages"])}, output=detail
            ),
        }
```

In `neo4j_only`, return `node_io` too:

```python
        groups = state.get("groups", [])
        detail = {"variant": "pure_neo4j", "context_groups": len(groups)}
        return {
            "variant1_detail": detail,
            "node_io": stage_io(input={"context_groups": len(groups)}, output=detail),
        }
```

In `toast_sql`, both branches return `node_io`. Replace the no-candidate return:

```python
        if not candidates:
            detail = [
                {
                    "status": "no_candidate",
                    "note": "таблица-кандидат в neo4j не найдена — SQL не запускался",
                }
            ]
            return {
                "sql_results": [],
                "sql_detail": detail,
                "node_io": stage_io(input={"candidates": []}, output=detail),
            }
```

and the candidate return:

```python
        detail = [
            {
                "table": r.payload_id,
                "chunk": r.chunk_id,
                "status": _status(r.status),
                "rows": len(r.rows),
                "answer": r.answer_summary,
                "error": r.error,
            }
            for r in results
        ]
        return {
            "sql_results": results,
            "degradations": state.get("degradations", []) + degr,
            "sql_detail": detail,
            "node_io": stage_io(
                input={
                    "question": _question(state["messages"]),
                    "candidates": [tc.payload_id for tc in candidates],
                },
                output=detail,
            ),
        }
```

In `summarize`, build a citation view and add `node_io` on the success return. Add this helper inside `build_grounded_agent` (near `_question`), tolerant of test doubles:

```python
    def _cit_view(c: Any) -> dict:
        return {
            "marker": getattr(c, "marker", None),
            "file": getattr(c, "logical_file_key", None),
            "chunk": getattr(c, "chunk_id", None),
            "kind": getattr(c, "kind", None),
            "preview": getattr(c, "preview_text", None),
        }
```

Replace the success return's dict with (keep `answer_detail`):

```python
        return {
            "messages": [AIMessage(content=answer)],
            "citations": citations,
            "answer_detail": {
                "note": decision.note,
                "used_sql_payloads": list(decision.used_sql_payload_ids),
                "citations": len(citations),
            },
            "node_io": stage_io(
                input={
                    "groups": len(state.get("groups", [])),
                    "sql": list(decision.used_sql_payload_ids),
                },
                output={
                    "answer": answer,
                    "note": decision.note,
                    "citations": [_cit_view(c) for c in citations],
                },
            ),
        }
```

Note: the degraded/error branches of `summarize` may keep their current returns (no `node_io` required); the test only asserts the success path.

- [ ] **Step 4: Run tests to verify they pass (incl. existing grounded tests)**

Run: `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest tests/test_grounded.py -q`
Expected: PASS — the new test and all existing `test_grounded.py` tests (they still assert `neo4j_detail`/`sql_detail`, which are retained).

- [ ] **Step 5: Commit**

```bash
git add lore-core/services/lore-chat/agents/grounded.py \
        lore-core/services/lore-chat/tests/test_grounded.py
git commit -m "feat(trace): grounded nodes emit uniform node_io (answer text + citations)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Frontend guard test — a block renders input AND output

**Files:**
- Test: `frontend/src/components/ExecutionSteps/ExecutionSteps.test.tsx`

No component change: `ExecutionSteps.tsx:33-38` already renders `step.input` and `step.output`. This test locks the end-to-end contract (a uniform block shows both).

**Interfaces:**
- Consumes: `ExecutionSteps` (existing).

- [ ] **Step 1: Write the test**

Append inside the `describe("ExecutionSteps", ...)` block in `ExecutionSteps.test.tsx`:

```typescript
  it("рендерит и input, и output блока (единый контракт)", async () => {
    const s = step({
      id: "io1",
      type: "run",
      name: "summarize",
      input: '{\n  "groups": 2\n}',
      output: '{\n  "answer": "текст ответа",\n  "citations": []\n}',
    });
    const host = await render([s]);
    const pres = host.querySelectorAll("pre");
    expect(pres.length).toBe(2); // input + output
    expect(host.textContent).toContain("groups");
    expect(host.textContent).toContain("текст ответа");
  });
```

- [ ] **Step 2: Run the test**

Run (from `frontend`, Node 22):
`export PATH="/Users/stamplevskiyd/.nvm/versions/node/v22.23.1/bin:$PATH" && npx vitest run src/components/ExecutionSteps/ExecutionSteps.test.tsx`
Expected: PASS (component already renders both; if it fails, the contract is broken).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/ExecutionSteps/ExecutionSteps.test.tsx
git commit -m "test(fileviewer): lock that a trace block renders both input and output

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Full-suite regression

- [ ] **Step 1: lore-retrieval**

Run (from `lore-core/packages/lore-retrieval`): `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 2: lore-chat**

Run (from `lore-core/services/lore-chat`): `/Users/stamplevskiyd/development/lore/lore-core/.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 3: frontend**

Run (from `frontend`, Node 22): `export PATH="/Users/stamplevskiyd/.nvm/versions/node/v22.23.1/bin:$PATH" && npx vitest run && npx tsc --noEmit`
Expected: all tests pass, `tsc` clean.

- [ ] **Step 4:** If any unrelated test fails, stop and investigate — do not loosen assertions.

---

## Notes for the implementer

- The whole point is the CONVENTION: a block emits `{input, output}` and the renderer shows it. Do not add per-stage rendering code in `app.py`.
- `preview` truncates for display ONLY; the tracer (and Langfuse) keep full data — never truncate at the record site.
- `*_detail` state keys are retained for the LangGraph Studio inspector; `node_io.output` reuses those same dicts, so there is no divergent second copy to maintain.
- `_cit_view` uses `getattr` defaults because `test_grounded.py`'s fake returns plain citation values; real citations are `Citation` objects with these attributes.
