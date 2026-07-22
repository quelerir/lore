import { auditGet, auditPost } from "./auditClient";
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

// Bound how much of a very large run we eagerly pull, to stay kind to the backend.
const MAX_CHUNKS = 500;
const CONCURRENCY = 8;
// Payload refs are resolved in one batched endpoint call per this many ids
// (matches the backend's max_length on POST /payloads/query).
const PAYLOAD_BATCH = 100;

// Map with a bounded number of in-flight requests (waves of `size`).
async function mapPooled<T, R>(
  items: T[],
  size: number,
  fn: (item: T) => Promise<R>,
): Promise<R[]> {
  const out: R[] = [];
  for (let i = 0; i < items.length; i += size) {
    out.push(...(await Promise.all(items.slice(i, i + size).map(fn))));
  }
  return out;
}

// Talks to the real read-only audit API.
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

  // Eagerly loads a run's chunks WITH text and payload types, so the user sees
  // everything at once (no per-chunk click). Text comes from the per-chunk detail
  // endpoint (fetched with bounded concurrency); payload refs are then resolved in
  // ONE batched pass across all chunks — see resolvePayloadRefs. Capped at
  // MAX_CHUNKS for huge runs; a failed chunk degrades to its preview rather than
  // dropping out of the list.
  async hydrateRunChunks(runId: string): Promise<FileChunk[]> {
    const encodedRun = encodeURIComponent(runId);

    const previews: ChunkPreviewDto[] = [];
    let cursor: string | undefined;
    do {
      const page = await auditGet<PageDto<ChunkPreviewDto>>(
        `/runs/${encodedRun}/chunks`,
        { cursor },
      );
      previews.push(...page.items);
      cursor = page.next_cursor ?? undefined;
    } while (cursor && previews.length < MAX_CHUNKS);

    // Fetch each chunk's detail (text + payload_refs); a failed chunk degrades to
    // its metadata-only preview (and carries no refs).
    const detailed = await mapPooled(
      previews.slice(0, MAX_CHUNKS),
      CONCURRENCY,
      async (preview): Promise<{ chunk: FileChunk; refs: string[] }> => {
        try {
          const dto = await auditGet<ChunkDetailDto>(
            `/runs/${encodedRun}/chunks/${encodeURIComponent(preview.chunk_id)}`,
          );
          return { chunk: mapChunkDetail(dto), refs: dto.payload_refs };
        } catch {
          return { chunk: mapChunkPreview(preview), refs: [] };
        }
      },
    );

    // Resolve every referenced payload in one batched pass (deduped across
    // chunks), replacing the per-ref N+1. A ref that fails to resolve is omitted.
    const refs = await this.resolvePayloadRefs(
      encodedRun,
      detailed.flatMap((entry) => entry.refs),
    );

    const chunks = detailed.map((entry) => {
      if (entry.refs.length === 0) return entry.chunk;
      const payloads = entry.refs
        .map((id) => refs.get(id))
        .filter((ref): ref is FileChunkPayloadRef => ref !== undefined);
      return { ...entry.chunk, payloads };
    });

    chunks.sort((a, b) => a.ordinal - b.ordinal);
    return chunks;
  }

  // Resolve payload refs to their type/label via the batch endpoint, deduping ids
  // and chunking into PAYLOAD_BATCH-sized POSTs. A failed batch degrades to empty
  // (those refs simply don't render), matching the old per-ref catch.
  private async resolvePayloadRefs(
    encodedRun: string,
    ids: string[],
  ): Promise<Map<string, FileChunkPayloadRef>> {
    const unique = [...new Set(ids)];
    const batches: string[][] = [];
    for (let i = 0; i < unique.length; i += PAYLOAD_BATCH) {
      batches.push(unique.slice(i, i + PAYLOAD_BATCH));
    }
    const resolved = new Map<string, FileChunkPayloadRef>();
    await mapPooled(batches, CONCURRENCY, async (batch) => {
      try {
        const dtos = await auditPost<PayloadDetailDto[]>(
          `/runs/${encodedRun}/payloads/query`,
          { payload_ids: batch },
        );
        for (const dto of dtos) resolved.set(dto.payload_id, mapPayloadRef(dto));
      } catch {
        // batch failed -> its refs stay unresolved (degrade, don't sink the run)
      }
    });
    return resolved;
  }
}
