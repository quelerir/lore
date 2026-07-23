import { describe, expect, it } from "vitest";
import {
  appendRunChunks,
  applyChunkDetail,
  firstUnloadedTableIds,
  isDetailLoaded,
  mergeRunTables,
  resolveSelection,
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

describe("chunkState helpers", () => {
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
});

describe("resolveSelection", () => {
  const files = [file([chunk("a", 1), chunk("b", 2), chunk("c", 3)])];

  it("defaults to first file/run/chunk when nothing is selected", () => {
    const sel = resolveSelection({
      files,
      selectedFileId: null,
      selectedRunId: null,
      selectedChunkId: null,
      pendingFocusChunkId: null,
    });
    expect(sel).toEqual({ fileId: "f1", runId: "r1", chunkId: "a" });
  });

  it("keeps a selected chunk that exists in the run", () => {
    const sel = resolveSelection({
      files,
      selectedFileId: "f1",
      selectedRunId: "r1",
      selectedChunkId: "b",
      pendingFocusChunkId: null,
    });
    expect(sel.chunkId).toBe("b");
  });

  it("falls back to the first chunk when the selected chunk is absent and no deep-link is pending", () => {
    const sel = resolveSelection({
      files,
      selectedFileId: "f1",
      selectedRunId: "r1",
      selectedChunkId: "missing",
      pendingFocusChunkId: null,
    });
    expect(sel.chunkId).toBe("a");
  });

  it("KEEPS the deep-linked chunk target while it is still loading (does NOT clobber to first)", () => {
    // The citation target "c" is set but the run hasn't loaded it yet (only "a"
    // is present). Must keep "c", not fall back to "a" — that overwrite is sticky.
    const partiallyLoaded = [file([chunk("a", 1)])];
    const sel = resolveSelection({
      files: partiallyLoaded,
      selectedFileId: "f1",
      selectedRunId: "r1",
      selectedChunkId: "c",
      pendingFocusChunkId: "c",
    });
    expect(sel.chunkId).toBe("c");
  });

  it("selects the deep-linked chunk once it has loaded", () => {
    const sel = resolveSelection({
      files,
      selectedFileId: "f1",
      selectedRunId: "r1",
      selectedChunkId: "c",
      pendingFocusChunkId: "c",
    });
    expect(sel.chunkId).toBe("c");
  });
});
