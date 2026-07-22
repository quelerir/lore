import { beforeEach, describe, expect, it, vi } from "vitest";

// Stub the low-level audit client so the provider logic is tested in isolation.
const auditGet = vi.fn();
const auditPost = vi.fn();
vi.mock("./auditClient", () => ({
  auditGet: (...args: unknown[]) => auditGet(...args),
  auditPost: (...args: unknown[]) => auditPost(...args),
}));

import { ApiFilesProvider } from "./apiFilesProvider";
import type { ChunkDetailDto, ChunkPreviewDto, PayloadDetailDto } from "./mappers";

const preview = (chunkId: string, ordinal: number): ChunkPreviewDto => ({
  schema_version: "v1",
  chunk_id: chunkId,
  run_id: "run-1",
  ordinal,
  pipeline_type: "documents",
  chunk_type: "text",
  content_signature: `sig-${chunkId}`,
});

const window = (text: string) => ({
  text,
  truncated: false,
  returned_bytes: text.length,
  full_bytes: text.length,
});

const detail = (chunkId: string, ordinal: number, refs: string[]): ChunkDetailDto => ({
  schema_version: "v1",
  preview: preview(chunkId, ordinal),
  display_text: window(`display ${chunkId}`),
  full_text: window(`full ${chunkId}`),
  vector_text: window(`vector ${chunkId}`),
  coordinates: {},
  payload_refs: refs,
});

const payload = (id: string): PayloadDetailDto => ({
  schema_version: "v1",
  run_id: "run-1",
  payload_id: id,
  kind: "table",
  registered: true,
  summary: { label: `label-${id}` },
  reason_code: null,
});

beforeEach(() => {
  auditGet.mockReset();
  auditPost.mockReset();
});

describe("ApiFilesProvider.hydrateRunChunks payload batching", () => {
  it("resolves all payload refs in one deduped batch, not one call per ref", async () => {
    // chunk-1 refs [p1, p2]; chunk-2 refs [p1, p3] — p1 is shared across chunks.
    const details: Record<string, ChunkDetailDto> = {
      "chunk-1": detail("chunk-1", 1, ["p1", "p2"]),
      "chunk-2": detail("chunk-2", 2, ["p1", "p3"]),
    };

    auditGet.mockImplementation((path: string) => {
      if (path.endsWith("/chunks")) {
        return Promise.resolve({
          schema_version: "v1",
          items: [preview("chunk-1", 1), preview("chunk-2", 2)],
          order_key: "ordinal,chunk_id",
          next_cursor: null,
          truncated: false,
        });
      }
      const id = path.split("/chunks/")[1];
      return Promise.resolve(details[id]);
    });

    auditPost.mockImplementation((_path: string, body: { payload_ids: string[] }) =>
      Promise.resolve(body.payload_ids.map(payload)),
    );

    const chunks = await new ApiFilesProvider().hydrateRunChunks("run-1");

    // Exactly ONE batch POST (3 unique ids <= PAYLOAD_BATCH), deduped across chunks.
    expect(auditPost).toHaveBeenCalledTimes(1);
    const [postPath, postBody] = auditPost.mock.calls[0];
    expect(postPath).toBe("/runs/run-1/payloads/query");
    expect([...(postBody as { payload_ids: string[] }).payload_ids].sort()).toEqual([
      "p1",
      "p2",
      "p3",
    ]);

    // Payloads assembled back onto the right chunks (order preserved per chunk).
    expect(chunks.map((c) => c.id)).toEqual(["chunk-1", "chunk-2"]);
    expect(chunks[0].payloads.map((p) => p.id)).toEqual(["p1", "p2"]);
    expect(chunks[1].payloads.map((p) => p.id)).toEqual(["p1", "p3"]);
    expect(chunks[0].payloads[0]).toEqual({ type: "table", id: "p1", label: "label-p1" });
  });

  it("omits refs the batch fails to resolve, keeping the chunk", async () => {
    auditGet.mockImplementation((path: string) => {
      if (path.endsWith("/chunks")) {
        return Promise.resolve({
          schema_version: "v1",
          items: [preview("chunk-1", 1)],
          order_key: "ordinal,chunk_id",
          next_cursor: null,
          truncated: false,
        });
      }
      return Promise.resolve(detail("chunk-1", 1, ["p1", "p2"]));
    });
    // Batch resolves only p1; p2 is missing from the response -> omitted.
    auditPost.mockResolvedValue([payload("p1")]);

    const chunks = await new ApiFilesProvider().hydrateRunChunks("run-1");

    expect(chunks).toHaveLength(1);
    expect(chunks[0].payloads.map((p) => p.id)).toEqual(["p1"]);
  });
});
