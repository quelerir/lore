import type { FilesProvider, ListFilesResult } from "./filesProvider";
import { mockFiles } from "./mockData";
import type { FileChunk, FileRun } from "./types";

// Serves the bundled demo data. Filtering/paging stay client-side in FilesPage,
// so listFiles just returns the whole fully-hydrated tree.
export class MockFilesProvider implements FilesProvider {
  async listFiles(): Promise<ListFilesResult> {
    return { files: mockFiles, nextCursor: null, truncated: false };
  }

  // Already fully hydrated — return the file's runs (with chunks) unchanged.
  async hydrateFileRuns(logicalFileKey: string): Promise<FileRun[]> {
    return mockFiles.find((file) => file.id === logicalFileKey)?.runs ?? [];
  }

  private findRun(runId: string): FileRun | undefined {
    for (const file of mockFiles) {
      const run = file.runs.find((r) => r.id === runId);
      if (run) return run;
    }
    return undefined;
  }

  async hydrateRunChunks(runId: string): Promise<FileChunk[]> {
    return this.findRun(runId)?.chunks ?? [];
  }
}
