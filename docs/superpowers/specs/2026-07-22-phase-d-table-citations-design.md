# Phase D — table citations, inline `[n]` superscripts, deterministic fallback

Extends the grounded-citations feature (see
`2026-07-21-chat-citations-fileviewer-design.md` §D and
`2026-07-22-phase-b-knowledge-tool-citations-design.md`). Phases A–C shipped text
citations end-to-end: the model places `[n]` markers over enumerated text
evidence, the `cite` step resolves them to verified `Citation`s that deep-link
into the FileViewer (`tab=display`), and the SPA renders them as cards under the
answer. Phase D adds three extensions in one slice.

## Goals

1. **Table/SQL citations** — a table that grounded the answer becomes a citable,
   clickable source that opens the FileViewer payloads tab (`tab=payloads`) on
   the table's anchor chunk.
2. **Deterministic fallback** — when the model produces no resolvable `[n]`
   marker but grounding evidence existed, cite the top-N evidence units by shown
   order, so a grounded answer is not left source-less.
3. **Inline `[n]` superscripts** — render the markers inside the answer text as
   clickable superscripts that jump to / highlight the matching citation card.

## Grounding (verified against the code)

- `arbitrate_and_answer` (`pipeline/arbitration.py`) enumerates **only** text
  `ContextGroup`s as `[1..G]` and returns `evidence_map: dict[int, list[str]]`
  (index → contributing chunk_ids). SQL successes are shown as
  `- payload {id}: {summary}` with **no** `[n]` index, and are absent from
  `evidence_map`.
- `SQLResult` (`contracts.py`) carries both `payload_id` and the TableChunk
  anchor `chunk_id`. It does **not** carry `run_id`/`logical_file_key`.
- `TableCandidate` carries `chunk_id` + `payload_id` + `score` (no provenance).
- `_table_discover` (`pipeline/graph.py`) already loads the anchor rows via
  `context_loader.load(table_ids) -> list[SourceChunk]`; `SourceChunk` carries
  `run_id`, `heading_path`, `display_text`, `fulltext`, `payload_refs`. This
  provenance is currently built into `text_by_id`/`payload_by_chunk` and then
  discarded.
- `build_deep_link` (`pipeline/citation.py`) hardcodes `tab=display`.
- `Citation` (`contracts.py`) = `chunk_id`, `run_id`, `logical_file_key`,
  `preview_text`, `heading_path`, `deep_link`.
- FileViewer `urlState.ts` parses `file` / `run` / `chunk` / `tab` (incl.
  `tab=payloads`); there is **no** `payload` URL param — the payloads tab renders
  for the selected `chunk`. So a table citation is the existing deep-link with
  `tab=payloads` and the anchor `chunk_id`; no new URL contract is needed.

## Design

### A. Arbitration — enumerate SQL successes into the `[n]` sequence

`arbitrate_and_answer` numbers evidence continuously: text groups take `[1..G]`,
SQL successes take `[G+1 .. G+S]`. The prompt lists SQL results with their
bracket index and the citation instruction covers both lanes.

`AgentDecision` gains `sql_evidence_map: dict[int, str]` — index → the SQL
result's anchor `chunk_id`. The text `evidence_map` stays text-only (index →
chunk_ids). The two maps have disjoint index ranges.

Prompt shape (SQL block, when successes exist):

```
Результаты SQL (каждый отдельно, не объединять; ссылайся номером [n]):
[G+1] payload {payload_id}: {answer_summary}
```

The "поставь маркер `[n]`" instruction fires whenever there is any evidence
(text groups **or** SQL successes), not only text groups as today.

### B. Table anchor provenance

`TableCandidate` gains `run_id: str` and `heading_path: tuple[str, ...]`.
`_table_discover` populates them from the anchor `SourceChunk` it already loads
(map `chunk_id -> (run_id, heading_path)` from `tbl_chunks`, passed into
`select_table_candidates`). Non-table or unresolved anchors keep the existing
skip behaviour.

`table_candidates` is threaded into `summarize` → `_cite` (new parameter). The
cite step joins `SQLResult.chunk_id == TableCandidate.chunk_id` to recover
`run_id`/`heading_path`. `SQLResult` is left unchanged (SQL-execution contract
stays stable).

### C. Cite step + `build_citations`

`_cite` resolves both evidence maps against the answer's markers:

- **Text** (existing): index → `evidence_map` chunk_ids → `EvidenceEnvelope` →
  `Citation(kind="text")`, `deep_link` with `tab=display`, `marker=index`.
- **Table**: index → `sql_evidence_map` anchor chunk_id → the matching
  `SQLResult` (preview = `answer_summary`) + `TableCandidate` (run_id,
  heading_path) + `file_key_by_run[run_id]` → `Citation(kind="table")`,
  `deep_link` with `tab=payloads` on the anchor chunk_id, `marker=index`.

Marker parsing stays "in order of first appearance"; text and table indices are
interleaved by that order. Dedup: text by `chunk_id`, table by `payload_id`
(so the same physical table cited twice collapses). Cap at `limit` across both
kinds combined.

`run_ids` passed to the file-key resolver now include table anchors' run_ids
(union of text-envelope run_ids and table-candidate run_ids).

**Deterministic fallback.** If, after resolving markers, the citation list is
empty **and** grounding existed (`groups` or SQL successes), cite the top-N
(N = 3) evidence units in *shown order* — text groups `[1..G]` first (as text
citations), then SQL successes (as table citations) — until N is reached. These
fallback citations carry `marker=None` (no inline superscript). If there was no
grounding at all, citations stay `[]` (unchanged; matches the
`no_grounded_evidence` path).

`build_citations` signature grows to accept the SQL evidence map, the
`sql_result_by_chunk` / `table_candidate_by_chunk` provenance, and a fallback
flag; it stays a pure function (offline-testable with fakes).

### D. Contracts

- `Citation` gains `kind: Literal["text", "table"] = "text"` and
  `marker: int | None = None` (the `[n]` index; `None` for fallback citations).
- `build_deep_link(logical_file_key, run_id, chunk_id, *, tab: str = "display")`.
- `TableCandidate` gains `run_id: str` and `heading_path: tuple[str, ...]`.
- `AgentDecision` gains `sql_evidence_map: dict[int, str] = {}`.

`Citation.model_dump()` now carries `kind` + `marker` into the message metadata;
existing text citations serialize with `kind="text"`, `marker` set.

### E. Frontend

- `frontend/src/chat/citations.ts`: `Citation` + `RawCitation` gain
  `kind: "text" | "table"` and `marker: number | null`; `toCitation` reads them
  (default `kind="text"`, `marker=null` when absent, so pre-Phase-D metadata
  still maps).
- `components/Citations/Citations.tsx`: pick the icon by `kind` — `FileText` for
  text, lucide `Table` for table — and keep the deep-link click
  (`navigateTo(deep_link)`); the table link already targets `tab=payloads`.
- **Inline superscripts** (`AssistantMessage`): build `marker → Citation` from
  the message's citations, then render `[n]` occurrences in the answer text as
  clickable superscripts. Clicking scrolls to and briefly highlights the card
  with `marker === n`. Implemented as a rehype transform over text nodes that
  skips `code`/`pre` nodes (so `[n]` inside code stays literal); a marker with no
  matching citation renders as plain text (never a dead link). Fallback citations
  (`marker === null`) render as cards only.

## Guardrails (unchanged, extended)

- Only markers matching **provided** evidence indices (text or SQL) become
  citations — no invented sources. `sql_evidence_map` only contains shown SQL
  successes.
- Table citations reuse the SQL success that actually ran + the trusted
  `payload_id`; the deep-link is built only from trusted identifiers
  (`logical_file_key`/`run_id`/`chunk_id`), never from model text. The viewer
  re-validates membership.
- Fallback stays within provided evidence (top-N of what was shown); it never
  invents or reaches beyond the shown set.
- Preview text stays bounded (`answer_summary` for tables is already a bounded
  summary; text preview truncated as today).

## YAGNI

- One `marker` per `Citation` (not a list): duplicate `[n]` references to the
  same source dedup to one card. Multi-marker linkage is not needed.
- No new `payload` URL param: `tab=payloads` on the anchor `chunk` is sufficient.
- `SQLResult` unchanged: provenance rides on `TableCandidate`, joined by
  `chunk_id`.

## Testing

- `build_citations`:
  - SQL marker → `Citation(kind="table")` with `tab=payloads`, preview =
    `answer_summary`, run_id/heading from the candidate.
  - Mixed text+table markers resolve in first-appearance order; combined cap.
  - Table dedup by `payload_id`; text dedup by `chunk_id`.
  - Fallback: no resolvable markers + grounding → top-3 in shown order,
    `marker=None`; no grounding → `[]`.
  - `marker` index set correctly on marker-resolved citations.
- `arbitrate_and_answer`: SQL successes enumerated continuing after text groups;
  `sql_evidence_map` maps each SQL index → anchor chunk_id; prompt lists SQL with
  `[n]` and the instruction fires on SQL-only grounding.
- `_table_discover` / `select_table_candidates`: `TableCandidate` carries the
  anchor's `run_id` + `heading_path`.
- Pipeline e2e (fakes): question that grounds on a table → non-empty citations
  incl. a `kind="table"` deep-link; text+table mix; fallback path.
- Frontend (vitest): table citation renders the table icon + `tab=payloads`
  link; `[n]` in answer text becomes a superscript linking to the matching card;
  a `[n]` with no citation stays plain text; fallback cards have no superscript.

## Out of scope

- Rendering the actual table rows inside the chat (the citation opens the viewer;
  no inline table preview).
- Image/transcript payload citations (only table/SQL here; images await the S3
  slice).
- Changing the SQL-execution or table-discovery ranking behaviour.
