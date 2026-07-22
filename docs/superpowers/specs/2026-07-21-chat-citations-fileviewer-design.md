# Chat Citations → FileViewer — Design

Date: 2026-07-21
Status: design (brainstormed & agreed). Bridges two things that already exist — the retrieval
pipeline's evidence and the `/files` FileViewer — with the missing middle: model-chosen citations
rendered as clickable preview cards that deep-link into the viewer.

## Purpose

After the AI answers, surface **which source chunk(s)** each claim came from as a clickable
"reference" showing a text preview; clicking opens the FileViewer at that document/chunk.

## Current state (research)

Both ends exist and are production-spec'd; the middle does not exist and is unspecified.

- **Exists:** FileViewer React route `/files` opened via deep-link
  `/files?file=<logical_file_key>&run=<run_id>&chunk=<chunk_id>&tab=display`
  (`frontend/src/features/files/FilesPage.tsx`; spec `docs/lore-file-viewer-frontend-spec.md`,
  `agent-lore .../24-VIEWER-SPEC.md` D-04). Read API `/api/v1/audit/*` (chunk detail with
  `display_text`/`coordinates`/`payload_refs`) mounted on the Chainlit app. The retrieval pipeline
  already produces `AgentDecision` + resolved `EvidenceEnvelope` (run_id, coordinates, display_text).
- **Chat is a native React SPA** on `@chainlit/react-client` with its own router (`AppRouter.tsx`,
  `navigateTo(path)` via `history.pushState`) — **not** an iframe. So a citation click is a direct
  `navigateTo("/files?...")`; no postMessage bridge.
- **Missing:** citation model, LLM citation markers, marker→citation resolution, `run_id →
  logical_file_key` resolution, deep-link builder, message-carried citations, SPA rendering.

## Agreed decisions

1. **Clean package + node wrapper.** Citations are an optional field on the pipeline's typed result
   (`PipelineResult.citations`), built by a dedicated `build_citations` step in `lore-retrieval` (no
   `langgraph` dependency, fully offline-testable). The lore-chat LangGraph state carries the same
   `citations` field 1:1 as an optional formatted field, produced by a `cite` node.
2. **LLM-chosen citations (markers).** The final prompt enumerates evidence as `[1..N]`; the model
   places `[n]` markers in its answer; the `cite` step maps used markers → citations. The model
   decides what to show; we only ever resolve markers to **provided** evidence.

## Design

### Citation contract (`lore_retrieval.contracts`)

```
Citation:
  chunk_id: str
  run_id: str
  logical_file_key: str
  preview_text: str            # truncated display_text (~160 chars)
  heading_path: tuple[str,...] # from coordinates, for label context
  deep_link: str               # /files?file=..&run=..&chunk=..&tab=display
```

`PipelineResult` gains `citations: list[Citation] = []` (empty when the answer is ungrounded).

### Evidence enumeration + prompting (arbitration node)

`arbitrate_and_answer` enumerates the evidence units it shows the model and returns the mapping so a
later node can resolve markers:

- Each shown evidence unit (a `ContextGroup`, and optionally an SQL result) gets a stable local index
  `[1], [2], …`.
- The prompt instructs: *"Cite each claim with the bracketed evidence numbers you used, e.g. `[2]`.
  Only cite evidence you actually used."*
- `AgentDecision` gains `evidence_map: dict[int, list[str]]` — index → contributing canonical
  `chunk_id`s (a group maps to its member chunks; an SQL result maps to its TableChunk anchor).

### Marker resolution (`cite` node → `build_citations`)

`build_citations(answer, evidence_map, envelope_by_chunk, file_key_by_run, *, preview_chars=160,
limit=8) -> list[Citation]`:

1. Parse `\[(\d+)\]` markers in order of first appearance.
2. For each marker index present in `evidence_map`, take its chunk_ids; **ignore indices not in the
   map** (guardrail: never cite non-provided evidence — no hallucinated sources).
3. For each chunk_id, build a `Citation` from its `EvidenceEnvelope` (preview = truncated
   `display_text`; `run_id`, `heading_path` from coordinates) and `logical_file_key` from
   `file_key_by_run[run_id]`; `deep_link` via the builder below.
4. Deduplicate by `chunk_id` preserving order; cap at `limit`.
5. No markers → `[]` (answer stands without sources).

### `run_id → logical_file_key`

`lore_core.chunks` carries `run_id` but not `logical_file_key` (it lives on `processing_runs`).
Resolve it in a small adapter — a batched `SELECT logical_file_key FROM lore_core.processing_runs
WHERE run_id = ANY(...)` (or the audit `/runs/{run_id}` endpoint). Pure builder takes the resolved
`file_key_by_run: dict[str,str]` so it stays offline-testable.

### Deep-link builder

```
deep_link(c) = f"/files?file={quote(logical_file_key)}&run={quote(run_id)}&chunk={quote(chunk_id)}&tab=display"
```
Matches the viewer's D-04 URL contract; the viewer validates file→run→chunk membership and highlights
the chunk (or shows `VS-BROKEN-LINK` if stale).

### lore-chat integration (LangGraph node)

- The node wrapping `RetrievalPipeline.answer` puts `citations` into the graph state (optional field)
  and attaches them to the assistant message — as Chainlit message **metadata** (`cl.Message(...,
  metadata={"citations": [...]})`) so the native SPA renderer can pick them up. A dedicated `cite`
  node keeps this a discrete, observable Langfuse span.

### SPA rendering

- Extend `frontend/src/chat/convertMessage.ts` (and the message renderer) to detect
  `metadata.citations` and render citation cards below the answer: preview snippet + heading label.
- `onClick → navigateTo(citation.deep_link)` opens FileViewer at the chunk. Inline `[n]` markers in
  the answer text can render as superscripts linking to the same card (progressive enhancement).

## Guardrails

- Only markers matching **provided** evidence indices become citations (no invented sources).
- Citations reuse the pipeline's already-verified `EvidenceEnvelope` (post canonical resolution), so a
  stale/superseded/hash-mismatched chunk is never cited.
- `deep_link` is built only from trusted identifiers (`logical_file_key`/`run_id`/`chunk_id`), never
  from model text; the viewer independently re-validates membership.
- Preview text is bounded; no full canonical content leaks into the chat transcript beyond the window.

## Phasing

- **A — pipeline (offline) — DONE (2026-07-21):** `Citation` contract, `build_citations` +
  `build_deep_link` (`pipeline/citation.py`), `evidence_map` + `[n]` enumeration in arbitration,
  `run_id→logical_file_key` adapter (`adapters/file_keys.py`, pure core + asyncpg), `_cite` step in
  `RetrievalPipeline`, `PipelineResult.citations`. TDD with fakes; 76 tests green.
- **B — lore-chat node:** `cite` node in the LangGraph wrapper; attach citations to the message
  metadata. (Needs the chat integration; logic demoable on fakes.)
- **C — SPA rendering — DONE (2026-07-22):** `collectCitationsByMessage` (id→citations, mirrors
  `traceByMessage`), threaded via `sessionUi.citationsByMessage` in `ChainlitRuntimeProvider`;
  `Citations` component (preview cards, `onClick → navigateTo(deep_link)`) rendered under the answer
  in `AssistantMessage`. Unit test for the collector. Frontend build/visual verify needs Node 20.
- **D — extensions:** table citations (deep-link the TableChunk anchor, `tab=payloads`); inline
  superscript markers; deterministic fallback when the model cites nothing.

## Testing

- `build_citations`: markers resolved in order; non-provided indices ignored; dedup + cap; empty on no
  markers; preview truncation; deep-link shape.
- arbitration `evidence_map`: indices map to the right chunk_ids; prompt enumerates evidence.
- adapter `run_id→logical_file_key`: pure mapping + missing-run handling.
- e2e: pipeline answer with markers → non-empty citations with valid deep-links.

## Open questions / follow-ups

- Citation granularity: group-representative vs every member chunk (v1: every member of a cited
  group, deduped).
- Should an SQL/table citation open the table view (`tab=payloads`) — deferred to phase D.
- Model marker discipline across providers (OpenRouter models) — validate in eval; deterministic
  fallback available if marker recall is poor.
