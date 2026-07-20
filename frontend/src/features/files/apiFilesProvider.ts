import { auditGet } from "./auditClient";
import type { FilesProvider, ListFilesParams, ListFilesResult } from "./filesProvider";
import {
  mapFileCard,
  mapRun,
  type FileCardDto,
  type PageDto,
  type RunDetailDto,
} from "./mappers";
import type { FileRun } from "./types";

// Talks to the real read-only audit API. Chunk/payload hydration lands next.
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

  async hydrateFileRuns(logicalFileKey: string): Promise<FileRun[]> {
    const page = await auditGet<PageDto<RunDetailDto>>("/runs", {
      logical_file_key: logicalFileKey,
    });
    return page.items.map(mapRun);
  }
}
