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

export interface SelectionInput {
  files: FileRecord[];
  selectedFileId: string | null;
  selectedRunId: string | null;
  selectedChunkId: string | null;
  pendingFocusChunkId: string | null;
}

export interface Selection {
  fileId: string | null;
  runId: string | null;
  chunkId: string | null;
}

// Reconcile the file/run/chunk selection against the (progressively loaded) file
// list. Key rule: while a deep-linked chunk is pending (a citation was clicked but
// its chunk hasn't loaded into the run yet), DO NOT fall back to the first chunk —
// that overwrite is sticky (the first-chunk id then "matches" on every re-run) and
// leaves the citation pointing at the wrong chunk. Keep the target; it becomes the
// active selection once its page loads.
export function resolveSelection(input: SelectionInput): Selection {
  const { files, selectedFileId, selectedRunId, selectedChunkId, pendingFocusChunkId } = input;
  if (!files.length) {
    return { fileId: selectedFileId, runId: selectedRunId, chunkId: selectedChunkId };
  }

  const file = files.find((f) => f.id === selectedFileId) ?? files[0];
  const run = file.runs.find((r) => r.id === selectedRunId) ?? file.runs[0] ?? null;
  const runId = run ? run.id : selectedRunId;

  const chunkLoaded = run?.chunks.some((c) => c.id === selectedChunkId) ?? false;
  let chunkId: string | null;
  if (chunkLoaded) {
    chunkId = selectedChunkId;
  } else if (pendingFocusChunkId) {
    // Deep-linked target not loaded yet — preserve it, don't clobber to first.
    chunkId = selectedChunkId;
  } else {
    chunkId = run?.chunks[0]?.id ?? null;
  }

  return { fileId: file.id, runId, chunkId };
}

// Table payload ids on this chunk we haven't hydrated yet (for the payloads tab).
export function firstUnloadedTableIds(chunk: FileChunk, knownTableIds: Set<string>): string[] {
  return chunk.payloads
    .filter((p) => p.type === "table" && !knownTableIds.has(p.id))
    .map((p) => p.id);
}
