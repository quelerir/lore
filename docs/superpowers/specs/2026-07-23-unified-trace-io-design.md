# Unified execution-trace {input, output} contract

Date: 2026-07-23
Branch: lore-agent-merge
Status: approved (design)

## Problem

The chat "ход выполнения" (execution trace) is inconsistent and thin:

- Pipeline stages record **output-only, count-based** payloads (e.g. `arbitration`
  = `{note, used_sql}`), so `summarize` shows no answer text and no citations.
- `toast_sql` shows per-attempt SQL but no clear input, and no preview of what it
  returned.
- No block shows its **input** — only `tool`-type steps get `.input`.
- Each block's payload is bespoke; adding a new tool means writing new display
  handling.

Goal: every block in the trace shows, uniformly, **what it received (input)** and
**what it produced (output)**, so a new tool needs no display rewrite. Outputs may
be large → show the first N characters.

## Current architecture (verified)

- `lore_retrieval/observability.py`: `Tracer.record(stage: str, payload: dict)`.
  `ContextTracer` appends `{"stage": stage, "data": dict(payload)}` to the
  per-turn `trace_sink` contextvar list. `CompositeTracer` fans out to
  ContextTracer + Langfuse. `NullTracer` no-op.
- `pipeline/graph.py` + `toast_binding.py` call `tracer.record(stage, {...})` with
  output summaries; `toast_binding.py` appends `{"stage": "sql", "data": {...}}`.
- Grounded nodes (`agents/grounded.py`) also return `*_detail` dicts into LangGraph
  state (a separate Studio channel).
- `app._render_run_steps`: per node (`iter_node_updates`) opens a `cl.Step`, nests
  tool-call events (with `.input`/`.output`) and the pipeline trace stages emitted
  while that node ran, setting **only** `stage_step.output = json(data)`.
- Frontend `ExecutionSteps.tsx` already renders both `step.input` and `step.output`
  as `<pre>` via `formatIo`. So the frontend needs little/no change.

## Approach (chosen: A — convention + generic renderer)

A uniform `{input, output}` convention emitted by every block, split onto the
Chainlit step generically, with truncation at the render layer. Rejected: (B) a
formal typed `StageTrace` dataclass everywhere — more churn/rigidity, YAGNI;
(C) frontend-only — impossible, the data isn't produced today.

### 1. Contract + helpers (`observability.py`)

```python
def stage_io(*, input=None, output=None) -> dict:
    """Uniform trace payload: what a block received and produced."""
    return {"input": input, "output": output}
```

Convention: a trace `data` dict (or a grounded node's `node_io`) MAY carry `input`
and/or `output` keys. When present, the renderer maps them to the step's
`.input`/`.output`. Payloads without these keys keep the legacy behaviour (whole
`data` dumped to `.output`) — back-compat, no forced rewrite of every stage at once.

### 2. Generic rendering (`app._render_run_steps`, `app.py`)

- Add `_preview(obj, cap)`: JSON-serialize (`ensure_ascii=False`), truncate to
  `cap` chars with a `…(+N chars)` marker. `cap` from env
  `TRACE_PREVIEW_CHARS` (default 2000).
- Stage step: if `data` has `input`/`output` →
  `step.input = _preview(data["input"], cap)` (omit if input is None),
  `step.output = _preview(data["output"], cap)`. Else → legacy
  `step.output = _preview(data, cap)`.
- Node step: read the node's returned `node_io` (if present) →
  set the node `cl.Step`'s `.input`/`.output` the same way.
- Truncation happens ONLY here. The tracer/Langfuse keep full-fidelity data.

### 3. Node-level `node_io` (`agents/grounded.py`)

Each grounded node returns `node_io={"input": ..., "output": ...}` alongside its
existing state. `*_detail` content folds into `output` (Studio still sees it via
the returned dict). Inputs added:

| Node | input | output |
|---|---|---|
| neo4j_retrieve | `{question}` | groups/resolved/rejected counts + table candidates (current `neo4j_detail`) |
| neo4j_only | `{context_groups}` | `{variant: pure_neo4j}` (current `variant1_detail`) |
| toast_sql | `{question, candidates:[payload_id,…]}` | per-table `{status, rows, answer_summary, error}` (current `sql_detail`) |
| summarize | `{groups: n, sql: [payload_id…]}` | `{answer: <full>, note, citations: [marker,file,chunk,kind,preview]}` |

`summarize` output carries the **full answer text + citation list** (rendered
truncated). On the failure branch, output = `{error, detail}` as today.

### 4. Enriched stage payloads (`pipeline/graph.py`, `toast_binding.py`)

Convert the named stages to `stage_io(...)`:

| Stage | input | output |
|---|---|---|
| arbitration | `{question, groups:[section_path, preview], sql:[payload_id, answer_summary]}` | `{answer: <full>, note}` |
| cite | `{markers: [...]}` | `{citations: [{marker, file, chunk, kind, preview}]}` |
| sql (toast) | `{table, question}` | `{sql, ok, rows, preview: answer_summary or rows first N}` |

Remaining count-only stages (`text_fanout`, `text_expansion`, `text_context`,
`text_rerank`, `text_resolve`, `grouping`, `table_discover`, `table_sql`) may be
migrated to `stage_io(input=…, output=…)` opportunistically; where an input is
cheap (e.g. the question), add it. Any not migrated keep rendering via the legacy
path, so nothing breaks.

## Data flow

`node/stage` → `stage_io/node_io {input, output}` → tracer (full) + Langfuse (full)
→ `_render_run_steps` → `cl.Step.input/.output` (truncated `_preview`) → react-client
→ `ExecutionSteps` `<pre>` blocks.

## Error handling

- Node/stage failures already degrade; the failure branch emits
  `output={error, detail}` (uniform — an error is just another output).
- `_preview` must never throw on non-serializable data → `json.dumps(..., default=str)`.

## Testing

- `stage_io` (pure) — shape.
- `_preview(obj, cap)` — truncation, `…(+N)` marker, non-serializable via `default=str`,
  None input omitted.
- `_render_run_steps` — a trace entry with `{input, output}` sets both on the step;
  a legacy entry sets only `.output`; oversized output is truncated.
- Enriched payloads: `arbitration` output carries `answer`; `cite` output carries
  citations; `summarize` `node_io.output` carries answer + citations; `sql` output
  carries `sql` + preview.
- Frontend: `ExecutionSteps` renders a step that has both input and output (both
  `<pre>` blocks appear).

## Out of scope

- Redesigning the frontend trace UI (collapsible "показать полностью", diffing).
- Removing the `*_detail` Studio channel (kept; folded into `node_io.output`).
- Migrating EVERY count-only stage in one pass (back-compat path covers stragglers).
