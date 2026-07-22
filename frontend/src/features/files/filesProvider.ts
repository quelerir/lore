// Data seam for the FileViewer. The UI consumes files through a provider so
// FilesPage stays decoupled from the transport. The only source is the
// read-only audit backend at /api/v1/audit.
import type { FileChunk, FileRecord, FileRun, FileTablePayload } from "./types";
import { ApiFilesProvider } from "./apiFilesProvider";

export interface ListFilesParams {
  search?: string;
  statuses?: string[];
  cursor?: string;
}

export interface ListFilesResult {
  files: FileRecord[];
  nextCursor: string | null;
  truncated: boolean;
}

export interface FilesProvider {
  /** List files for the left panel. Params drive server-side search/paging. */
  listFiles(params?: ListFilesParams): Promise<ListFilesResult>;
  /** Load a file's runs on selection (metadata only; chunks hydrate later). */
  hydrateFileRuns(logicalFileKey: string): Promise<FileRun[]>;
  /** Load a run's chunks on selection — eagerly, with text and payload types. */
  hydrateRunChunks(runId: string): Promise<FileChunk[]>;
  /** Load table detail (columns + sampled rows) for the run's table payloads, so
   *  the payloads-tab inspector renders real tables. Best-effort. */
  hydrateRunTables(runId: string, tablePayloadIds: string[]): Promise<FileTablePayload[]>;
}

export const filesProvider: FilesProvider = new ApiFilesProvider();
