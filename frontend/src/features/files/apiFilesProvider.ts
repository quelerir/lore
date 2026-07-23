import { auditGet, auditPost } from "./auditClient";
import type { FilesProvider, ListFilesParams, ListFilesResult } from "./filesProvider";
import {
  mapChunkDetail,
  mapChunkPreview,
  mapFileCard,
  mapPayloadRef,
  mapRun,
  mapTablePayload,
  type ChunkDetailDto,
  type ChunkPreviewDto,
  type FileCardDto,
  type PageDto,
  type PayloadDetailDto,
  type RunDetailDto,
  type TableProfileDto,
  type TableRowPageDto,
} from "./mappers";
import type { FileChunk, FileChunkPayloadRef, FileRun, FileTablePayload } from "./types";

// Bound how much of a very large run we eagerly pull, to stay kind to the backend.
const MAX_CHUNKS = 500;
const CONCURRENCY = 8;
// Payload refs are resolved in one batched endpoint call per this many ids
// (matches the backend's max_length on POST /payloads/query).
const PAYLOAD_BATCH = 100;
// Rows sampled per table for the payloads-tab preview (kept small; server clamps).
const TABLE_SAMPLE_LIMIT = 10;

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
  async listRunChunkPreviews(
    runId: string,
    onPage: (chunks: FileChunk[], meta: { done: boolean }) => void,
  ): Promise<void> {
    const encodedRun = encodeURIComponent(runId);
    let cursor: string | undefined;
    let count = 0;
    do {
      const page = await auditGet<PageDto<ChunkPreviewDto>>(
        `/runs/${encodedRun}/chunks`,
        { cursor },
      );
      const remaining = MAX_CHUNKS - count;
      const items = page.items.slice(0, Math.max(0, remaining));
      count += items.length;
      cursor = page.next_cursor ?? undefined;
      const done = !cursor || count >= MAX_CHUNKS;
      onPage(items.map(mapChunkPreview), { done });
      if (done) return;
    } while (cursor);
  }

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

  // Load a single chunk's detail (text + coordinates) and resolve its payload
  // refs. Used for lazy, on-demand loading — the list shows previews and only
  // the visible/selected chunk pays for its detail. Payload refs for one chunk
  // go through the same batched endpoint (one POST here, deduped).
  async loadChunkDetail(runId: string, chunkId: string): Promise<FileChunk> {
    const encodedRun = encodeURIComponent(runId);
    const dto = await auditGet<ChunkDetailDto>(
      `/runs/${encodedRun}/chunks/${encodeURIComponent(chunkId)}`,
    );
    const chunk = mapChunkDetail(dto);
    if (dto.payload_refs.length === 0) return chunk;
    const resolved = await this.resolvePayloadRefs(encodedRun, dto.payload_refs);
    const payloads = dto.payload_refs
      .map((id) => resolved.get(id))
      .filter((ref): ref is FileChunkPayloadRef => ref !== undefined);
    return { ...chunk, payloads };
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

  // Table detail for the payloads-tab inspector: per table payload, fetch its
  // profile (columns + row count) then a small sample page, and combine into a
  // FileTablePayload. Best-effort per table (a failure drops just that one) and
  // bounded concurrency. Deduped by payload id.
  async hydrateRunTables(
    runId: string,
    tablePayloadIds: string[],
  ): Promise<FileTablePayload[]> {
    const encodedRun = encodeURIComponent(runId);
    const unique = [...new Set(tablePayloadIds)];
    const tables = await mapPooled(unique, CONCURRENCY, async (id) => {
      const encId = encodeURIComponent(id);
      try {
        const profile = await auditGet<TableProfileDto>(
          `/runs/${encodedRun}/payloads/${encId}/table/profile`,
        );
        const sample = await auditPost<TableRowPageDto>(
          `/runs/${encodedRun}/payloads/${encId}/table/sample`,
          { columns: profile.columns, limit: TABLE_SAMPLE_LIMIT },
        );
        return mapTablePayload(profile, sample);
      } catch {
        return null; // table detail is best-effort; skip on any failure
      }
    });
    return tables.filter((table): table is FileTablePayload => table !== null);
  }
}
