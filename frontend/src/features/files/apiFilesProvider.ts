import { auditGet } from "./auditClient";
import type { FilesProvider, ListFilesParams, ListFilesResult } from "./filesProvider";
import {
  mapChunkDetail,
  mapChunkPreview,
  mapFileCard,
  mapPayloadRef,
  mapRun,
  type ChunkDetailDto,
  type ChunkPreviewDto,
  type FileCardDto,
  type PageDto,
  type PayloadDetailDto,
  type RunDetailDto,
} from "./mappers";
import type { FileChunk, FileChunkPayloadRef, FileRun } from "./types";

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

  async hydrateRunChunks(runId: string): Promise<FileChunk[]> {
    const page = await auditGet<PageDto<ChunkPreviewDto>>(
      `/runs/${encodeURIComponent(runId)}/chunks`,
    );
    return page.items.map(mapChunkPreview);
  }

  async hydrateChunkDetail(runId: string, chunkId: string): Promise<FileChunk> {
    const dto = await auditGet<ChunkDetailDto>(
      `/runs/${encodeURIComponent(runId)}/chunks/${encodeURIComponent(chunkId)}`,
    );
    const chunk = mapChunkDetail(dto);
    const payloads = await Promise.all(
      dto.payload_refs.map((id) =>
        auditGet<PayloadDetailDto>(
          `/runs/${encodeURIComponent(runId)}/payloads/${encodeURIComponent(id)}`,
        )
          .then(mapPayloadRef)
          .catch((): FileChunkPayloadRef | null => null),
      ),
    );
    return { ...chunk, payloads: payloads.filter((ref): ref is FileChunkPayloadRef => ref !== null) };
  }
}
