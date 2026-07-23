# FileViewer Progressive Chunk Loading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make FileViewer render a run's chunk list instantly and lazily load per-chunk detail, add loading indicators, highlight the chunk a chat citation points to, and add a back-to-chat button.

**Architecture:** Split the single blocking `hydrateRunChunks(runId)` into two provider methods — `listRunChunkPreviews` (streams cheap metadata-only pages) and `loadChunkDetail` (one chunk's text + payloads). `FilesPage` renders preview placeholders as pages arrive, then loads each chunk's detail lazily via an IntersectionObserver (plus an immediate priority load for the selected/deep-linked chunk). A tail skeleton row marks "list still growing"; a per-card title skeleton marks "detail pending". Citation navigation scrolls the target card into view and flashes it. Frontend-only — no backend changes.

**Tech Stack:** React 19 (hooks, no router lib — custom `navigateTo`), TypeScript, Vitest (+ happy-dom for component/DOM tests), CSS Modules, lucide-react icons.

## Global Constraints

- Frontend-only. Do NOT modify any backend/audit API or the preview DTO. Exact values from spec: `docs/superpowers/specs/2026-07-23-fileviewer-progressive-chunks-design.md`.
- Preview cap stays `MAX_CHUNKS = 500`.
- Work happens on branch `feat/fileviewer-progressive-chunks`. All commands run from `frontend/` (the Vite project root).
- Run the full frontend test suite with `npm run test` (alias for `vitest run`); typecheck/build with `npm run build`.
- A chunk "has detail loaded" iff `chunk.displayText.length > 0 || chunk.fullText.length > 0` (preview maps both to `""`). Use this predicate everywhere; do not add a parallel status enum in component state.
- Follow existing file conventions: provider logic in `apiFilesProvider.ts`, DTO/mappers in `mappers.ts`, provider tests mock `./auditClient`.

---

## File Structure

- `frontend/src/features/files/apiFilesProvider.ts` — add `loadChunkDetail`, add `listRunChunkPreviews`, remove `hydrateRunChunks`. Reuse existing `resolvePayloadRefs`, `mapChunkPreview`, `mapChunkDetail`, `mapPooled`, constants.
- `frontend/src/features/files/filesProvider.ts` — update `FilesProvider` interface: drop `hydrateRunChunks`, add the two new methods.
- `frontend/src/features/files/chunkState.ts` — **new** pure helpers: `isDetailLoaded`, `applyChunkDetail`, `mergeRunTables`, `firstUnloadedTableIds`. Keeps the nested-state merge logic out of the component and unit-testable.
- `frontend/src/features/files/chunkState.test.ts` — **new** unit tests for those helpers.
- `frontend/src/features/files/apiFilesProvider.test.ts` — replace the cross-chunk payload-batching test with per-chunk `loadChunkDetail` tests; add `listRunChunkPreviews` tests.
- `frontend/src/features/files/FilesPage.tsx` — swap the hydration effect for streaming previews + IntersectionObserver lazy detail; add title skeleton, tail loading row, scroll+flash, back-to-chat button, popstate re-sync.
- `frontend/src/features/files/FilesPage.module.css` — `chunkTitleSkeleton`, `chunkLoadingRow`, `chunkCardFlash`, shimmer/flash keyframes, back-to-chat button spacing.

---

## Task 1: Provider — `loadChunkDetail(runId, chunkId)`

Additive. Loads one chunk's detail and resolves that chunk's payload refs. Reuses the existing private `resolvePayloadRefs`.

**Files:**
- Modify: `frontend/src/features/files/apiFilesProvider.ts`
- Test: `frontend/src/features/files/apiFilesProvider.test.ts`

**Interfaces:**
- Consumes: `auditGet`, `mapChunkDetail`, private `resolvePayloadRefs(encodedRun, ids)` (already present, returns `Map<string, FileChunkPayloadRef>`).
- Produces: `loadChunkDetail(runId: string, chunkId: string): Promise<FileChunk>` — a fully-populated `FileChunk` (text + `payloads`).

- [ ] **Step 1: Write the failing test**

Add to `apiFilesProvider.test.ts` (the helpers `preview`, `detail`, `payload`, `window` already exist in the file):

```ts
describe("ApiFilesProvider.loadChunkDetail", () => {
  it("loads one chunk's detail and resolves its payload refs", async () => {
    auditGet.mockImplementation((path: string) => {
      expect(path).toBe("/runs/run-1/chunks/chunk-1");
      return Promise.resolve(detail("chunk-1", 1, ["p1", "p2"]));
    });
    auditPost.mockImplementation((_path: string, body: { payload_ids: string[] }) =>
      Promise.resolve(body.payload_ids.map(payload)),
    );

    const chunk = await new ApiFilesProvider().loadChunkDetail("run-1", "chunk-1");

    expect(chunk.id).toBe("chunk-1");
    expect(chunk.displayText).toBe("display chunk-1");
    expect(chunk.payloads.map((p) => p.id)).toEqual(["p1", "p2"]);
    // exactly one detail GET and one batched payload POST for this chunk
    expect(auditGet).toHaveBeenCalledTimes(1);
    expect(auditPost).toHaveBeenCalledTimes(1);
  });

  it("returns the chunk with no payloads when it has no refs", async () => {
    auditGet.mockResolvedValue(detail("chunk-9", 9, []));

    const chunk = await new ApiFilesProvider().loadChunkDetail("run-1", "chunk-9");

    expect(chunk.payloads).toEqual([]);
    expect(auditPost).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- apiFilesProvider`
Expected: FAIL — `loadChunkDetail is not a function`.

- [ ] **Step 3: Write minimal implementation**

In `apiFilesProvider.ts`, add this method to the `ApiFilesProvider` class (place it directly after `hydrateRunChunks`, before `resolvePayloadRefs`):

```ts
  // Load a single chunk's detail (text + coordinates) and resolve its payload
  // refs. Used for lazy, on-demand loading — the list shows previews and only
  // the visible/selected chunk pays for its detail. Payload refs for one chunk
  // go through the same batched endpoint (one POST here, deduped).
  async loadChunkDetail(runId: string, chunkId: string): Promise<FileChunk> {
    const encodedRun = encodeURIComponent(runId);
    const dto = await auditGet<ChunkDetailDto>(
      `/runs/${encodedRun}/chunks/${encodeURIComponent(chunkId)}`,
    );
    const chunk = mapChunkDetail(dto);
    if (dto.payload_refs.length === 0) return chunk;
    const resolved = await this.resolvePayloadRefs(encodedRun, dto.payload_refs);
    const payloads = dto.payload_refs
      .map((id) => resolved.get(id))
      .filter((ref): ref is FileChunkPayloadRef => ref !== undefined);
    return { ...chunk, payloads };
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- apiFilesProvider`
Expected: PASS (the two new `loadChunkDetail` tests green; existing tests still green).

- [ ] **Step 5: Commit**

```bash
git add src/features/files/apiFilesProvider.ts src/features/files/apiFilesProvider.test.ts
git commit -m "feat(fileviewer): add loadChunkDetail for lazy per-chunk loading"
```

---

## Task 2: Provider — `listRunChunkPreviews(runId, onPage)`

Additive. Streams metadata-only preview pages via a callback so the UI can render them as they arrive. Never touches the per-chunk detail endpoint.

**Files:**
- Modify: `frontend/src/features/files/apiFilesProvider.ts`
- Test: `frontend/src/features/files/apiFilesProvider.test.ts`

**Interfaces:**
- Consumes: `auditGet`, `mapChunkPreview`, `MAX_CHUNKS`, `PageDto`, `ChunkPreviewDto`.
- Produces: `listRunChunkPreviews(runId: string, onPage: (chunks: FileChunk[], meta: { done: boolean }) => void): Promise<void>` — resolves after all pages (or the `MAX_CHUNKS` cap) are delivered; calls `onPage` once per page with placeholder `FileChunk`s (empty text). The final page's `meta.done` is `true`.

- [ ] **Step 1: Write the failing test**

Add to `apiFilesProvider.test.ts`:

```ts
describe("ApiFilesProvider.listRunChunkPreviews", () => {
  it("streams preview pages without fetching per-chunk detail", async () => {
    auditGet.mockImplementation((path: string, params?: { cursor?: string }) => {
      expect(path).toBe("/runs/run-1/chunks");
      if (!params?.cursor) {
        return Promise.resolve({
          schema_version: "v1",
          items: [preview("chunk-1", 1)],
          order_key: "ordinal,chunk_id",
          next_cursor: "c2",
          truncated: false,
        });
      }
      return Promise.resolve({
        schema_version: "v1",
        items: [preview("chunk-2", 2)],
        order_key: "ordinal,chunk_id",
        next_cursor: null,
        truncated: false,
      });
    });

    const pages: Array<{ ids: string[]; done: boolean }> = [];
    await new ApiFilesProvider().listRunChunkPreviews("run-1", (chunks, meta) =>
      pages.push({ ids: chunks.map((c) => c.id), done: meta.done }),
    );

    expect(pages).toEqual([
      { ids: ["chunk-1"], done: false },
      { ids: ["chunk-2"], done: true },
    ]);
    // Placeholders carry no text (detail is loaded lazily elsewhere).
    // Only the two /chunks list calls were made — no /chunks/{id} detail GETs.
    expect(auditGet).toHaveBeenCalledTimes(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- apiFilesProvider`
Expected: FAIL — `listRunChunkPreviews is not a function`.

- [ ] **Step 3: Write minimal implementation**

In `apiFilesProvider.ts`, add this method to the class (place it directly before `hydrateRunChunks`):

```ts
  // Stream a run's chunk previews (metadata only — no text) page by page via
  // `onPage`, so the list can render placeholders as they arrive instead of
  // blocking on a full fan-out. Detail is loaded lazily via loadChunkDetail.
  // Capped at MAX_CHUNKS; the final delivered page carries meta.done = true.
  async listRunChunkPreviews(
    runId: string,
    onPage: (chunks: FileChunk[], meta: { done: boolean }) => void,
  ): Promise<void> {
    const encodedRun = encodeURIComponent(runId);
    let cursor: string | undefined;
    let count = 0;
    do {
      const page = await auditGet<PageDto<ChunkPreviewDto>>(
        `/runs/${encodedRun}/chunks`,
        { cursor },
      );
      const remaining = MAX_CHUNKS - count;
      const items = page.items.slice(0, Math.max(0, remaining));
      count += items.length;
      cursor = page.next_cursor ?? undefined;
      const done = !cursor || count >= MAX_CHUNKS;
      onPage(items.map(mapChunkPreview), { done });
      if (done) return;
    } while (cursor);
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- apiFilesProvider`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/features/files/apiFilesProvider.ts src/features/files/apiFilesProvider.test.ts
git commit -m "feat(fileviewer): add listRunChunkPreviews streaming previews"
```

---

## Task 3: Pure state helpers for chunk merging

The chunk state lives nested in `allFiles[].runs[].chunks`. Extract the merge logic into pure, unit-tested helpers so `FilesPage` stays thin and the bug-prone immutable updates are covered by tests.

**Files:**
- Create: `frontend/src/features/files/chunkState.ts`
- Test: `frontend/src/features/files/chunkState.test.ts`

**Interfaces:**
- Consumes: `FileRecord`, `FileChunk`, `FileTablePayload` from `./types`.
- Produces:
  - `isDetailLoaded(chunk: FileChunk): boolean`
  - `applyChunkDetail(files: FileRecord[], fileId: string, runId: string, chunk: FileChunk): FileRecord[]`
  - `appendRunChunks(files: FileRecord[], fileId: string, runId: string, chunks: FileChunk[]): FileRecord[]`
  - `mergeRunTables(files: FileRecord[], fileId: string, runId: string, tables: FileTablePayload[]): FileRecord[]`
  - `firstUnloadedTableIds(chunk: FileChunk, knownTableIds: Set<string>): string[]`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/files/chunkState.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  appendRunChunks,
  applyChunkDetail,
  firstUnloadedTableIds,
  isDetailLoaded,
  mergeRunTables,
} from "./chunkState";
import type { FileChunk, FileRecord, FileTablePayload } from "./types";

const chunk = (id: string, ordinal: number, over: Partial<FileChunk> = {}): FileChunk => ({
  id,
  ordinal,
  type: "text",
  coordinates: "",
  section: "",
  displayText: "",
  fullText: "",
  vectorText: "",
  charCount: 0,
  tokenCount: 0,
  hash: `sig-${id}`,
  contentSignature: `sig-${id}`,
  warnings: [],
  findings: [],
  payloads: [],
  metadata: {},
  diagnostics: [],
  ...over,
});

const file = (chunks: FileChunk[], tables: FileTablePayload[] = []): FileRecord =>
  ({ id: "f1", runs: [{ id: "r1", chunks, tables }] }) as unknown as FileRecord;

it("isDetailLoaded is false for previews and true once text arrives", () => {
  expect(isDetailLoaded(chunk("a", 1))).toBe(false);
  expect(isDetailLoaded(chunk("a", 1, { displayText: "x" }))).toBe(true);
  expect(isDetailLoaded(chunk("a", 1, { fullText: "y" }))).toBe(true);
});

it("appendRunChunks adds placeholders to the matching run only", () => {
  const files = [file([chunk("a", 1)])];
  const next = appendRunChunks(files, "f1", "r1", [chunk("b", 2)]);
  expect(next[0].runs[0].chunks.map((c) => c.id)).toEqual(["a", "b"]);
  // immutability: original untouched
  expect(files[0].runs[0].chunks).toHaveLength(1);
});

it("applyChunkDetail replaces one chunk in place, preserving order", () => {
  const files = [file([chunk("a", 1), chunk("b", 2)])];
  const loaded = chunk("b", 2, { displayText: "detail-b" });
  const next = applyChunkDetail(files, "f1", "r1", loaded);
  expect(next[0].runs[0].chunks.map((c) => c.id)).toEqual(["a", "b"]);
  expect(next[0].runs[0].chunks[1].displayText).toBe("detail-b");
  expect(files[0].runs[0].chunks[1].displayText).toBe("");
});

it("mergeRunTables dedups by id and keeps existing", () => {
  const t = (id: string): FileTablePayload => ({ id }) as unknown as FileTablePayload;
  const files = [file([chunk("a", 1)], [t("t1")])];
  const next = mergeRunTables(files, "f1", "r1", [t("t1"), t("t2")]);
  expect(next[0].runs[0].tables.map((x) => x.id).sort()).toEqual(["t1", "t2"]);
});

it("firstUnloadedTableIds returns table payload ids not yet known", () => {
  const c = chunk("a", 1, {
    payloads: [
      { type: "table", id: "t1", label: "" },
      { type: "image", id: "i1", label: "" },
      { type: "table", id: "t2", label: "" },
    ],
  });
  expect(firstUnloadedTableIds(c, new Set(["t1"]))).toEqual(["t2"]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- chunkState`
Expected: FAIL — cannot find module `./chunkState`.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/features/files/chunkState.ts`:

```ts
import type { FileChunk, FileRecord, FileTablePayload } from "./types";

// A chunk has its detail once any text window is populated (previews map text
// windows to ""). Single source of truth for "is this still a placeholder".
export function isDetailLoaded(chunk: FileChunk): boolean {
  return chunk.displayText.length > 0 || chunk.fullText.length > 0;
}

// Immutably map over one run inside the nested files -> runs structure.
function mapRun(
  files: FileRecord[],
  fileId: string,
  runId: string,
  update: (run: FileRecord["runs"][number]) => FileRecord["runs"][number],
): FileRecord[] {
  return files.map((file) =>
    file.id !== fileId
      ? file
      : { ...file, runs: file.runs.map((run) => (run.id === runId ? update(run) : run)) },
  );
}

export function appendRunChunks(
  files: FileRecord[],
  fileId: string,
  runId: string,
  chunks: FileChunk[],
): FileRecord[] {
  return mapRun(files, fileId, runId, (run) => ({ ...run, chunks: [...run.chunks, ...chunks] }));
}

export function applyChunkDetail(
  files: FileRecord[],
  fileId: string,
  runId: string,
  chunk: FileChunk,
): FileRecord[] {
  return mapRun(files, fileId, runId, (run) => ({
    ...run,
    chunks: run.chunks.map((c) => (c.id === chunk.id ? chunk : c)),
  }));
}

export function mergeRunTables(
  files: FileRecord[],
  fileId: string,
  runId: string,
  tables: FileTablePayload[],
): FileRecord[] {
  return mapRun(files, fileId, runId, (run) => {
    const byId = new Map(run.tables.map((t) => [t.id, t] as const));
    for (const t of tables) byId.set(t.id, t);
    return { ...run, tables: [...byId.values()] };
  });
}

// Table payload ids on this chunk we haven't hydrated yet (for the payloads tab).
export function firstUnloadedTableIds(chunk: FileChunk, knownTableIds: Set<string>): string[] {
  return chunk.payloads
    .filter((p) => p.type === "table" && !knownTableIds.has(p.id))
    .map((p) => p.id);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- chunkState`
Expected: PASS (all 5 tests green).

- [ ] **Step 5: Commit**

```bash
git add src/features/files/chunkState.ts src/features/files/chunkState.test.ts
git commit -m "feat(fileviewer): pure helpers for lazy chunk state merging"
```

---

## Task 4: FilesPage — streaming previews + lazy IntersectionObserver detail

Replace the blocking hydration effect with: (1) stream previews via `listRunChunkPreviews` into state as pages arrive, (2) lazily load each chunk's detail when its card enters the viewport, (3) merge each loaded chunk's table payloads. This is the core behavior change.

**Files:**
- Modify: `frontend/src/features/files/filesProvider.ts` (interface: add the two new methods; keep `hydrateRunChunks` for now so nothing else breaks — removed in Task 8)
- Modify: `frontend/src/features/files/FilesPage.tsx`

**Interfaces:**
- Consumes: `filesProvider.listRunChunkPreviews`, `filesProvider.loadChunkDetail`, `filesProvider.hydrateRunTables`, and `appendRunChunks`, `applyChunkDetail`, `mergeRunTables`, `firstUnloadedTableIds`, `isDetailLoaded` from `./chunkState`.
- Produces: a `registerCard(chunkId)` ref-callback used by Task 5/6 render; `previewsLoading` boolean state used by Task 6; `loadDetail(chunkId)` used by Task 7.

- [ ] **Step 1: Update the provider interface**

In `filesProvider.ts`, inside `interface FilesProvider`, add (keep the existing `hydrateRunChunks` line):

```ts
  /** Stream a run's chunk previews (metadata only) page by page. */
  listRunChunkPreviews(
    runId: string,
    onPage: (chunks: FileChunk[], meta: { done: boolean }) => void,
  ): Promise<void>;
  /** Load one chunk's detail (text + payloads) on demand. */
  loadChunkDetail(runId: string, chunkId: string): Promise<FileChunk>;
```

- [ ] **Step 2: Add imports and state in FilesPage**

In `FilesPage.tsx`, extend the `./chunkState` usage by adding this import near the other feature imports (after line 35):

```ts
import {
  appendRunChunks,
  applyChunkDetail,
  firstUnloadedTableIds,
  isDetailLoaded,
  mergeRunTables,
} from "./chunkState";
```

Add these near the other `useState`/`useRef` declarations (after line 289):

```ts
  const [previewsLoading, setPreviewsLoading] = useState(false);
  // chunkId -> card element, for IntersectionObserver + scroll-to.
  const cardRefs = useRef<Map<string, HTMLButtonElement>>(new Map());
  // chunkIds whose detail load is in-flight or done (dedup guard, not render state).
  const detailRequestedRef = useRef<Set<string>>(new Set());
  const observerRef = useRef<IntersectionObserver | null>(null);
```

- [ ] **Step 3: Add the loadDetail callback (above the return, after the existing hydration effect ~line 379)**

```ts
  // Load one chunk's detail on demand (viewport or selection), dedup by chunkId,
  // merge its text and any table payloads into the nested files state. On error
  // we drop the guard so a later intersection/click retries.
  const loadDetail = (chunkId: string) => {
    const fileId = selectedFileId;
    const runId = selectedRunId;
    if (!fileId || !runId) return;
    if (detailRequestedRef.current.has(chunkId)) return;
    detailRequestedRef.current.add(chunkId);
    void filesProvider
      .loadChunkDetail(runId, chunkId)
      .then((chunk) => {
        setAllFiles((prev) => applyChunkDetail(prev, fileId, runId, chunk));
        const run = allFiles.find((f) => f.id === fileId)?.runs.find((r) => r.id === runId);
        const known = new Set((run?.tables ?? []).map((t) => t.id));
        const tableIds = firstUnloadedTableIds(chunk, known);
        if (tableIds.length) {
          void filesProvider
            .hydrateRunTables(runId, tableIds)
            .then((tables) => {
              if (tables.length) {
                setAllFiles((prev) => mergeRunTables(prev, fileId, runId, tables));
              }
            })
            .catch(() => {});
        }
      })
      .catch(() => {
        detailRequestedRef.current.delete(chunkId);
      });
  };
```

- [ ] **Step 4: Replace the blocking hydration effect (lines 327–379) with streaming previews**

Replace the entire `useEffect` block that calls `filesProvider.hydrateRunChunks(runId)` with:

```ts
  useEffect(() => {
    const fileId = selectedFileId;
    const runId = selectedRunId;
    if (!fileId || !runId || hydratedRunsRef.current.has(runId)) return;
    const run = allFiles.find((f) => f.id === fileId)?.runs.find((r) => r.id === runId);
    if (!run || run.chunks.length > 0) return;
    hydratedRunsRef.current.add(runId);
    detailRequestedRef.current = new Set();
    setDetailLoading(true);
    setDetailError(false);
    setPreviewsLoading(true);
    let cancelled = false;
    void filesProvider
      .listRunChunkPreviews(runId, (chunks, meta) => {
        if (cancelled) return;
        setAllFiles((prev) => appendRunChunks(prev, fileId, runId, chunks));
        if (meta.done) setPreviewsLoading(false);
      })
      .catch(() => {
        if (cancelled) return;
        hydratedRunsRef.current.delete(runId);
        setDetailError(true);
        setPreviewsLoading(false);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [allFiles, selectedFileId, selectedRunId]);
```

- [ ] **Step 5: Add the IntersectionObserver effect**

**Placement:** this effect references `filteredChunks`, which is declared as a `useMemo` around line 486. It MUST be placed AFTER that declaration (not next to the Step 4 effect at ~379), or `filteredChunks` is in the temporal dead zone and render throws `ReferenceError`. Put it immediately after the `const filteredChunks = useMemo(...)` block. `loadDetail` (Step 3) and `registerCard` (Step 6) do not reference `filteredChunks`, so they may stay above the return anywhere after line 379.

```ts
  // Lazily load detail for chunks as their cards enter the viewport. Re-runs when
  // the visible chunk set changes (list grows / run switches); the callback ref
  // (Task 5 render) observes each card as it mounts.
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const chunkId = (entry.target as HTMLElement).dataset.chunkId;
          if (chunkId) loadDetail(chunkId);
        }
      },
      { rootMargin: "200px 0px" },
    );
    observerRef.current = observer;
    for (const el of cardRefs.current.values()) observer.observe(el);
    return () => {
      observer.disconnect();
      observerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRunId, filteredChunks.length]);
```

- [ ] **Step 6: Add the `registerCard` ref-callback (near other handlers, above the return)**

```ts
  // Ref callback for each chunk card: track the element for scroll-to and
  // register/unregister it with the live IntersectionObserver.
  const registerCard = (chunkId: string) => (el: HTMLButtonElement | null) => {
    const map = cardRefs.current;
    const existing = map.get(chunkId);
    if (existing && observerRef.current) observerRef.current.unobserve(existing);
    if (el) {
      map.set(chunkId, el);
      observerRef.current?.observe(el);
    } else {
      map.delete(chunkId);
    }
  };
```

- [ ] **Step 7: Wire the card element (in the `filteredChunks.map` render, ~line 1108)**

Change the chunk `<button>` opening tag to attach the ref and a data attribute:

```tsx
                    <button
                      key={chunk.id}
                      ref={registerCard(chunk.id)}
                      data-chunk-id={chunk.id}
                      className={`${styles.chunkCard} ${selectedChunk?.id === chunk.id ? styles.chunkCardActive : ""}`}
                      onClick={() => setSelectedChunkId(chunk.id)}
                      type="button"
                    >
```

- [ ] **Step 8: Typecheck + full test run**

Run: `npm run build`
Expected: PASS — no TypeScript errors. `hydrateRunChunks` is now unused in FilesPage but still defined (removed in Task 8); that is not a type error.

Run: `npm run test`
Expected: PASS — all existing + new provider/helper tests green.

- [ ] **Step 9: Manual verification**

Run: `npm run dev`, open a file with a large run.
Expected: the chunk list appears near-instantly with placeholder cards (no multi-second freeze); scrolling fills in card titles as cards come into view. (Automated component coverage for the observer wiring is impractical given FilesPage's dependency surface; the merge logic it relies on is covered by `chunkState.test.ts`.)

- [ ] **Step 10: Commit**

```bash
git add src/features/files/filesProvider.ts src/features/files/FilesPage.tsx
git commit -m "feat(fileviewer): stream chunk previews + lazy per-chunk detail"
```

---

## Task 5: FilesPage — title skeleton + tail loading row

Two visual loading states: a per-card title skeleton while a chunk's detail is pending, and a tail row while preview pages are still streaming.

**Files:**
- Modify: `frontend/src/features/files/FilesPage.tsx`
- Modify: `frontend/src/features/files/FilesPage.module.css`

**Interfaces:**
- Consumes: `isDetailLoaded` (Task 3), `previewsLoading` (Task 4).

- [ ] **Step 1: Add CSS**

Append to `FilesPage.module.css`:

```css
@keyframes chunkShimmer {
  0% { background-position: -320px 0; }
  100% { background-position: 320px 0; }
}

.chunkTitleSkeleton {
  height: 14px;
  margin-top: 7px;
  width: 72%;
  border-radius: 6px;
  background: linear-gradient(90deg, #eef1f4 25%, #f6f8fa 37%, #eef1f4 63%);
  background-size: 640px 100%;
  animation: chunkShimmer 1.4s infinite linear;
}

.chunkLoadingRow {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px;
  margin-bottom: 9px;
  border: 1px dashed rgba(178, 192, 208, 0.7);
  border-radius: 18px;
  color: #6b7280;
  font-size: 13px;
}

.chunkLoadingRow::before {
  content: "";
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid rgba(148, 163, 184, 0.35);
  border-top-color: rgba(100, 116, 139, 0.9);
  animation: chunkSpin 0.8s linear infinite;
}

@keyframes chunkSpin {
  to { transform: rotate(360deg); }
}
```

- [ ] **Step 2: Render the title skeleton (in the chunk card, replace the `chunkTitle` block ~line 1119)**

Replace:

```tsx
                      <strong className={styles.chunkTitle}>
                        {renderHighlightedText(isImageCard ? attachmentPreview.image.title : cardContent.title)}
                      </strong>
```

with:

```tsx
                      {isDetailLoaded(chunk) || isImageCard ? (
                        <strong className={styles.chunkTitle}>
                          {renderHighlightedText(isImageCard ? attachmentPreview.image.title : cardContent.title)}
                        </strong>
                      ) : (
                        <div className={styles.chunkTitleSkeleton} aria-hidden="true" />
                      )}
```

- [ ] **Step 3: Render the tail loading row (immediately after the `filteredChunks.map(...)` closes, inside `.chunkList`)**

Find the closing `)}` of the `{filteredChunks.map((chunk) => { ... })}` block within `<div className={styles.chunkList}>` and add right after it, before the `</div>` that closes `chunkList`:

```tsx
                {previewsLoading && !normalizedDocumentSearch ? (
                  <div className={styles.chunkLoadingRow}>Загрузка чанков…</div>
                ) : null}
```

(The `!normalizedDocumentSearch` guard hides the tail row while a document search is filtering the list, where "still streaming" would be misleading.)

- [ ] **Step 4: Typecheck**

Run: `npm run build`
Expected: PASS.

- [ ] **Step 5: Manual verification**

Run: `npm run dev`, open a large run.
Expected: a dashed "Загрузка чанков…" row sits at the end of the growing list and disappears once previews finish; cards show a shimmer bar where the title will be until their detail loads.

- [ ] **Step 6: Commit**

```bash
git add src/features/files/FilesPage.tsx src/features/files/FilesPage.module.css
git commit -m "feat(fileviewer): title skeleton + tail loading row"
```

---

## Task 6: FilesPage — scroll-to + flash on citation navigation

When the selected chunk comes from a deep link (citation), load its detail first, scroll its card into view, and flash it. Also re-sync file/run/chunk from the URL when a citation navigates while FilesPage is already open (popstate).

**Files:**
- Modify: `frontend/src/features/files/FilesPage.tsx`
- Modify: `frontend/src/features/files/FilesPage.module.css`

**Interfaces:**
- Consumes: `readFilesUrlState` (already imported), `cardRefs`, `loadDetail` (Task 4), `initialUrlState`.
- Produces: `flashChunkId` state driving the flash class in render.

- [ ] **Step 1: Add CSS flash**

Append to `FilesPage.module.css`:

```css
@keyframes chunkFlash {
  0% { background: #fde68a; box-shadow: 0 0 0 2px #f59e0b; }
  100% { background: rgba(255, 255, 255, 0.92); box-shadow: none; }
}

.chunkCardFlash {
  animation: chunkFlash 1.8s ease-out;
}
```

- [ ] **Step 2: Add flash + pending-focus state (near other state, after line 289)**

```ts
  // Chunk id that arrived via deep link / citation and still needs scroll+flash.
  const [pendingFocusChunkId, setPendingFocusChunkId] = useState<string | null>(
    initialUrlState.chunkId,
  );
  const [flashChunkId, setFlashChunkId] = useState<string | null>(null);
```

- [ ] **Step 3: Re-sync from URL on popstate (add effect above the return)**

```ts
  // A citation click uses navigateTo, which fires popstate. When we're already on
  // /files, re-read the URL so file/run/chunk follow the citation, and mark the
  // target chunk for scroll+flash.
  useEffect(() => {
    const onPopState = () => {
      if (window.location.pathname !== "/files") return;
      const next = readFilesUrlState();
      if (next.fileId) setSelectedFileId(next.fileId);
      if (next.runId) setSelectedRunId(next.runId);
      if (next.chunkId) {
        setSelectedChunkId(next.chunkId);
        setPendingFocusChunkId(next.chunkId);
      }
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
```

- [ ] **Step 4: Add the scroll + flash effect**

**Placement:** like the observer effect, this references `filteredChunks` and MUST be placed AFTER the `const filteredChunks = useMemo(...)` declaration (~line 486) — put it right after the Task 4 Step 5 observer effect. The popstate effect (Step 3) does not reference `filteredChunks` and may stay above the return anywhere.

```ts
  // Once the pending (deep-linked) chunk's card is mounted, prioritize its detail,
  // scroll it into view, and flash it so the user sees exactly which chunk the
  // citation pointed to. Clears the pending marker after firing once.
  useEffect(() => {
    if (!pendingFocusChunkId) return;
    const el = cardRefs.current.get(pendingFocusChunkId);
    if (!el) return; // card not rendered yet; effect re-runs when list grows
    loadDetail(pendingFocusChunkId);
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    setFlashChunkId(pendingFocusChunkId);
    setPendingFocusChunkId(null);
    const timer = window.setTimeout(() => setFlashChunkId(null), 1800);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingFocusChunkId, filteredChunks.length]);
```

- [ ] **Step 5: Apply the flash class in the chunk card (update className from Task 4 Step 7)**

```tsx
                      className={`${styles.chunkCard} ${selectedChunk?.id === chunk.id ? styles.chunkCardActive : ""} ${flashChunkId === chunk.id ? styles.chunkCardFlash : ""}`}
```

- [ ] **Step 6: Typecheck**

Run: `npm run build`
Expected: PASS.

- [ ] **Step 7: Manual verification**

Run: `npm run dev`. From chat, click a citation that points into a large file.
Expected: FileViewer opens, the referenced chunk's card scrolls to center and briefly flashes amber; its detail is loaded even if it was off-screen. Clicking the same citation again is a known no-op (navigateTo dedups identical paths) — documented in the spec as minor.

- [ ] **Step 8: Commit**

```bash
git add src/features/files/FilesPage.tsx src/features/files/FilesPage.module.css
git commit -m "feat(fileviewer): scroll-to + flash the cited chunk on navigation"
```

---

## Task 7: FilesPage — back-to-chat button

Render a visible back-to-chat button wired to the already-provided `onNavigateHome` prop (currently ignored via the `_` rename).

**Files:**
- Modify: `frontend/src/features/files/FilesPage.tsx`

- [ ] **Step 1: Un-ignore the prop**

Change the component signature (line 255) from:

```tsx
export default function FilesPage({ onNavigateHome: _onNavigateHome }: FilesPageProps) {
```

to:

```tsx
export default function FilesPage({ onNavigateHome }: FilesPageProps) {
```

- [ ] **Step 2: Import the icon**

Add `ArrowLeft` to the existing `lucide-react` import in `FilesPage.tsx` (the import that already includes `Search`, `ChevronLeft`, etc.).

- [ ] **Step 3: Render the button in the topbar (replace lines 873–877)**

```tsx
        <div className={styles.topbarLeft}>
          <button className={styles.secondaryButton} type="button" onClick={onNavigateHome}>
            <ArrowLeft size={15} /> В чат
          </button>
          <div>
            <h1 className={styles.title}>Lore File Viewer</h1>
          </div>
        </div>
```

- [ ] **Step 4: Typecheck**

Run: `npm run build`
Expected: PASS — no "unused variable" or "unused prop" complaints.

- [ ] **Step 5: Manual verification**

Run: `npm run dev`, open `/files`.
Expected: a "← В чат" button in the top-left; clicking it returns to the chat screen (`/`).

- [ ] **Step 6: Commit**

```bash
git add src/features/files/FilesPage.tsx
git commit -m "feat(fileviewer): add back-to-chat button"
```

---

## Task 8: Remove the obsolete `hydrateRunChunks`

Now that FilesPage uses the streaming + lazy path, delete the dead method, its interface entry, and the cross-chunk payload-batching test (its behavior is superseded by the per-chunk `loadChunkDetail` tests from Task 1).

**Files:**
- Modify: `frontend/src/features/files/apiFilesProvider.ts`
- Modify: `frontend/src/features/files/filesProvider.ts`
- Modify: `frontend/src/features/files/apiFilesProvider.test.ts`

- [ ] **Step 1: Remove the method**

In `apiFilesProvider.ts`, delete the entire `hydrateRunChunks(runId: string): Promise<FileChunk[]>` method (its leading doc comment through its closing brace). Keep `resolvePayloadRefs`, `listRunChunkPreviews`, `loadChunkDetail`, and `hydrateRunTables`.

- [ ] **Step 2: Remove the interface entry**

In `filesProvider.ts`, delete the `hydrateRunChunks(runId: string): Promise<FileChunk[]>;` line and its doc comment from `interface FilesProvider`.

- [ ] **Step 3: Remove the obsolete test**

In `apiFilesProvider.test.ts`, delete the `describe("ApiFilesProvider.hydrateRunChunks payload batching", ...)` block (both `it(...)` cases). Leave the `loadChunkDetail`, `listRunChunkPreviews`, and `hydrateRunTables` describes intact.

- [ ] **Step 4: Typecheck + full test run**

Run: `npm run build`
Expected: PASS — no references to `hydrateRunChunks` remain (grep to confirm: `grep -rn "hydrateRunChunks" src` returns nothing).

Run: `npm run test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/features/files/apiFilesProvider.ts src/features/files/filesProvider.ts src/features/files/apiFilesProvider.test.ts
git commit -m "refactor(fileviewer): drop obsolete blocking hydrateRunChunks"
```

---

## Self-Review Notes

- **Spec coverage:** split loader (Tasks 1–2, 8); lazy IntersectionObserver detail + selected/deep-link priority (Task 4 + Task 6 Step 4); tail skeleton + card title skeleton (Task 5); scroll + flash with `chunkCardActive` vs `chunkCardFlash` semantics (Task 6); back-to-chat button (Task 7); per-chunk table hydration preserving the payloads tab (Task 4 Step 3). Error degradation and stale-run guards covered in Task 4 (`cancelled` flag, `detailRequestedRef` reset/retry).
- **Out of scope (per spec):** backend `preview_text`, lifting `MAX_CHUNKS`, react-window virtualization, background prefetch of all off-screen detail.
- **Type consistency:** helper names (`appendRunChunks`, `applyChunkDetail`, `mergeRunTables`, `firstUnloadedTableIds`, `isDetailLoaded`) are used identically in Tasks 3–6. `loadChunkDetail(runId, chunkId)` and `listRunChunkPreviews(runId, onPage)` signatures match between provider (Tasks 1–2), interface (Task 4 Step 1), and call sites (Task 4).
- **Known limitation (documented, not a defect):** re-clicking an identical citation is a no-op because `navigateTo` dedups identical paths; noted in spec.
```
