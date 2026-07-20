import { auditGet } from "./auditClient";
import type { FilesProvider, ListFilesParams, ListFilesResult } from "./filesProvider";
import { mapFileCard, type FileCardDto, type PageDto } from "./mappers";

// Talks to the real read-only audit API. This slice covers the file list; run and
// chunk hydration land in the next slice.
export class ApiFilesProvider implements FilesProvider {
  async listFiles(params: ListFilesParams = {}): Promise<ListFilesResult> {
    const page = await auditGet<PageDto<FileCardDto>>("/files", {
      search: params.search || undefined,
      statuses: params.statuses,
      cursor: params.cursor,
    });
    return {
      files: page.items.map(mapFileCard),
      nextCursor: page.next_cursor,
      truncated: page.truncated,
    };
  }
}
