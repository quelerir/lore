// Data seam for the FileViewer. The UI consumes files through a provider so the
// source (local mock vs the real /api/v1/audit backend) can be swapped without
// touching FilesPage. Selected at build time via VITE_FILES_PROVIDER=api|mock.
import type { FileRecord, FileRun } from "./types";
import { ApiFilesProvider } from "./apiFilesProvider";
import { MockFilesProvider } from "./mockFilesProvider";

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
}

const providerType = import.meta.env.VITE_FILES_PROVIDER ?? "mock";

export const filesProvider: FilesProvider =
  providerType === "api" ? new ApiFilesProvider() : new MockFilesProvider();

export const activeFilesProviderKind = providerType;
