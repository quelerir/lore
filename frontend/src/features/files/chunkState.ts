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
