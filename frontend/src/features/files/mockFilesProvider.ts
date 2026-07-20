import type { FilesProvider, ListFilesResult } from "./filesProvider";
import { mockFiles } from "./mockData";

// Serves the bundled demo data. Filtering/paging stay client-side in FilesPage,
// so listFiles just returns the whole fully-hydrated tree.
export class MockFilesProvider implements FilesProvider {
  async listFiles(): Promise<ListFilesResult> {
    return { files: mockFiles, nextCursor: null, truncated: false };
  }
}
