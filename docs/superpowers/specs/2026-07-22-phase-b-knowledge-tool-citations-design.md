# Phase B — Knowledge-base Tool + Citations in lore-chat — Design

Date: 2026-07-22
Status: design (brainstormed & agreed). Implements Phase B of
`2026-07-21-chat-citations-fileviewer-design.md`: wire the retrieval pipeline into lore-chat so a
chat turn can produce a grounded answer whose **citations reach the assistant message metadata**
(which Phase C renders as FileViewer deep-link cards).

Builds on: the full request→answer→citation pipeline is DONE and verified live end-to-end via
`lore-core/packages/lore-retrieval/spikes/full_cycle_demo.py` (Neo4j + bge-m3 + Postgres + OpenRouter).

## Goal

After the user asks a question, the chat answers **grounded in the corpus** and carries the
pipeline's resolved `Citation`s on the outgoing `cl.Message` metadata, without breaking the existing
`fast`/`deep` chat behavior (calculator, plain chat) and without loading the whole corpus per query.

## Agreed decisions (from brainstorming)

1. **Retrieval as a tool.** Grounded retrieval is a LangChain tool `knowledge_base` that the existing
   agents (`fast`/`deep`) may call — not a new chat profile, not a replacement of the default path.
2. **Tool returns the full grounded answer + citations.** The tool runs the complete
   `RetrievalPipeline.answer` (including arbitration and the `_cite` step) and returns the grounded
   answer text to the agent; citations are captured out-of-band and attached to the message.
3. **Production corpus loading.** `RetrievalPipeline` is refactored so per-query maps
   (positions/text/section/payloads) are loaded **only for the retrieved candidate chunks**, via a new
   `ChunkContextLoader` seam — no whole-corpus maps in memory (Approach 1).

## Architecture & data flow

One chat turn:

```
on_message (parent task): capture = {}; _TURN.set(capture)   # set the CONTAINER in the parent
  └─ chat agent (fast/deep) decides to call knowledge_base(query)
        knowledge_base (possibly a child task):
          result = await pipeline.answer(query)   # full retrieval + arbitration + _cite
          _TURN.get()["result"] = result           # MUTATE the shared container (visible across tasks)
          return result.decision.answer            # grounded text (with [n]) → agent as ToolMessage
  └─ agent final node relays the grounded answer (streamed token-by-token)
on_message (after the turn, parent task):
  result = capture.get("result")
  out.metadata = to_message_metadata(result)       # {"citations": [...]}
  await out.update()                               # citations reach the frontend (Phase C renders them)
```

Key properties:
- **Capture via a mutable container held in a turn-scoped `contextvar`.** Critically, `on_message`
  (the parent task) creates the container and calls `_TURN.set(container)` *before* running the agent;
  the tool only **mutates** that shared object. This is deliberate: `contextvar.set()` inside a child
  task does NOT propagate back to the parent, but mutating a shared object bound in the parent's
  context IS visible everywhere (child tasks inherit a context copy pointing at the same object). This
  makes capture robust whether LangGraph runs the tool in the same task or a subtask, and works for
  both `fast` (our `StateGraph`) and `deep` (deepagents, a black box): the result bypasses graph state.
- Citations are already resolved inside the pipeline (`_cite`), so they do **not** depend on the agent
  preserving `[n]` markers when it relays.
- If retrieval is unconfigured (no Neo4j/DSN), the tool is not registered → chat is unchanged.
- Double LLM call (arbitration inside the tool + agent relay) is an accepted trade-off. The system
  prompt instructs: *when you called `knowledge_base`, relay its answer faithfully and add no
  unsourced claims.*

## Components

### A. Retrieval core — per-query context loader (`lore-retrieval`)

- `interfaces.py`: new `ChunkContextLoader` Protocol — `async load(chunk_ids: list[str]) -> list[SourceChunk]`.
- `adapters/context_postgres.py`: `PostgresChunkContextLoader(dsn)` —
  `SELECT … FROM lore_core.chunks WHERE chunk_id = ANY($1::text[])`, reusing `row_to_source_chunk`.
- `fakes.py`: `InMemoryChunkContextLoader(chunks)`.
- `pipeline/graph.py`: constructor **drops** `projection`, `positions`, `text_by_id`,
  `payload_by_chunk`; **gains** `context_loader`.
  - Text lane: after fanout+expansion → `chunks = await loader.load(candidate_ids)` → build
    `projection` (via existing `build_structural_projection`), `positions`, `text_by_id` locally from
    that bounded set. `rerank`/`grouping` code is unchanged (only the source of the maps changes).
  - Table lane: after `discover_table_candidates` → `load(table_ids)` → `payload_by_chunk`.
- `pipeline/factory.py`: `build_offline_pipeline` uses `InMemoryChunkContextLoader` (derived from its
  `chunks` argument), so the whole offline test suite keeps working with a one-line wiring change.

Note (scope): section-aware auto-merging now operates within the retrieved candidate set
(window-scope). That is sufficient here — parent promotion (`promote_parents`) is off by default until
P5 calibration.

### B. Live pipeline assembly (`lore-retrieval`)

- `pipeline/factory.py`: `build_live_pipeline(*, driver, database, dsn, embedder, chat_model,
  index_version)` — assembles Neo4j chunk/table/expansion backends + `PostgresEvidenceResolver` +
  `PostgresFileKeyResolver` + `PostgresChunkContextLoader` + the injected `chat_model`. **No**
  projection (that is a separate indexing step) and **no** cleanup. Keeps `lore-retrieval` free of any
  lore-chat config — the caller passes constructed backends.

### C. lore-chat integration

- `pyproject.toml`: add the `lore-retrieval` workspace dependency.
- New `retrieval.py` in the lore-chat service:
  - A lazy singleton live pipeline: Neo4j `AsyncDriver` + `OllamaEmbeddingBackend` +
    `OpenRouterChatModel`, built from `lore_retrieval.get_settings()` (Neo4j/Ollama/DSN) with
    `index_version` from config; assembled via `build_live_pipeline`.
  - A turn-scoped `contextvar` `_TURN: ContextVar[dict]` holding a **mutable capture container** for
    the turn's `PipelineResult`.
  - The `knowledge_base` tool (see D).
- `agents/tools.py`: `make_tools()` appends `knowledge_base` **only when** retrieval is configured
  (Neo4j URI + a lore_core DSN present); otherwise tools are exactly as today.
- `app.py` `on_message`: create a fresh container and `_TURN.set(container)` **before** running the
  agent; after `handle_message`, read `container.get("result")` (if any) and set
  `out.metadata = to_message_metadata(result)` before `out.update()`.

### D. The tool

```python
@tool
async def knowledge_base(query: str) -> str:
    """Найти ответ в базе знаний datacraft (регламенты, документы) с цитатами."""
    container = _TURN.get(None)  # set by on_message in the parent task
    try:
        result = await get_pipeline().answer(query)
    except Exception:
        return "Не удалось найти ответ в базе знаний по этому запросу."
    if container is not None:
        container["result"] = result  # mutate the shared object → visible in on_message
    return result.decision.answer
```

### E. Indexing prerequisite (out of chat runtime)

- A CLI `spikes/index_corpus.py` (or `scripts/`) that projects the corpus into Neo4j under a
  **persistent** `index_version` (reusing `project_batch`/`project_structure`), **without** cleanup.
  Without it the tool returns "nothing found". This is a prerequisite job, not part of the chat
  request path.

## Error handling

- The tool never propagates: on any pipeline error it clears `_TURN` and returns a soft message; the
  agent then answers as a plain model. The turn never fails.
- The pipeline already degrades internally (fanout/expansion/table/reranker failures).
- The live-pipeline singleton is built lazily; if Neo4j/Ollama is unreachable on first use, the tool
  catches it and returns the soft fallback — chat stays alive.
- No `_TURN` captured (tool not called) → metadata carries no `citations`; ordinary answer.

## Testing

- Core refactor: existing offline tests move to `InMemoryChunkContextLoader`; the pipeline stays green
  (preserve/adapt the 100 tests, do not drop coverage).
- `ChunkContextLoader`: unit on the fake; the Postgres adapter is live-verified (DB access confirmed).
- `knowledge_base`: fake pipeline → returns the answer and sets `_TURN`; error branch → soft fallback,
  `_TURN` cleared.
- Metadata attach: a simulated captured `PipelineResult` → `to_message_metadata` → `cl.Message.metadata`
  (unit, no live DB).
- e2e live: `full_cycle_demo.py` already proves the pipeline; chat integration is verified against a
  running stack separately.

## Out of scope (explicit)

- **Phase C** — frontend rendering of citation cards + `navigateTo("/files?…")`.
- **Phase D** — table citations (`tab=payloads`), inline `[n]` superscripts, deterministic fallback.
- `index_version` activation/lifecycle (which version is "live", reindexing) — a single configured
  `index_version` is assumed.
- Token-by-token streaming of the grounded answer itself (the tool returns it whole; the agent's relay
  streams).

## Testing checklist → definition of done

- [ ] `RetrievalPipeline` runs from a `ChunkContextLoader`; offline suite green.
- [ ] `knowledge_base` tool returns grounded answer, captures `PipelineResult`, soft-fails safely.
- [ ] `on_message` attaches `citations` metadata; unconfigured retrieval leaves chat unchanged.
- [ ] `index_corpus` projects a persistent version; live chat turn yields an answer + non-empty
      citations against the real corpus.
