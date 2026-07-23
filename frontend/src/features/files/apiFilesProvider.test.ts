import { beforeEach, describe, expect, it, vi } from "vitest";

// Stub the low-level audit client so the provider logic is tested in isolation.
const auditGet = vi.fn();
const auditPost = vi.fn();
vi.mock("./auditClient", () => ({
  auditGet: (...args: unknown[]) => auditGet(...args),
  auditPost: (...args: unknown[]) => auditPost(...args),
}));

import { ApiFilesProvider } from "./apiFilesProvider";
import type {
  ChunkDetailDto,
  ChunkPreviewDto,
  PayloadDetailDto,
  TableProfileDto,
  TableRowPageDto,
} from "./mappers";

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

describe("ApiFilesProvider.loadChunkDetail", () => {
  it("loads one chunk's detail and resolves its payload refs", async () => {
    auditGet.mockImplementation((path: string) => {
      expect(path).toBe("/runs/run-1/chunks/chunk-1");
      return Promise.resolve(detail("chunk-1", 1, ["p1", "p2"]));
    });
    auditPost.mockImplementation((_path: string, body: { payload_ids: string[] }) =>
      Promise.resolve(body.payload_ids.map(payload)),
    );

    const chunk = await new ApiFilesProvider().loadChunkDetail("run-1", "chunk-1");

    expect(chunk.id).toBe("chunk-1");
    expect(chunk.displayText).toBe("display chunk-1");
    expect(chunk.payloads.map((p) => p.id)).toEqual(["p1", "p2"]);
    // exactly one detail GET and one batched payload POST for this chunk
    expect(auditGet).toHaveBeenCalledTimes(1);
    expect(auditPost).toHaveBeenCalledTimes(1);
  });

  it("returns the chunk with no payloads when it has no refs", async () => {
    auditGet.mockResolvedValue(detail("chunk-9", 9, []));

    const chunk = await new ApiFilesProvider().loadChunkDetail("run-1", "chunk-9");

    expect(chunk.payloads).toEqual([]);
    expect(auditPost).not.toHaveBeenCalled();
  });
});

describe("ApiFilesProvider.listRunChunkPreviews", () => {
  it("streams preview pages without fetching per-chunk detail", async () => {
    auditGet.mockImplementation((path: string, params?: { cursor?: string }) => {
      expect(path).toBe("/runs/run-1/chunks");
      if (!params?.cursor) {
        return Promise.resolve({
          schema_version: "v1",
          items: [preview("chunk-1", 1)],
          order_key: "ordinal,chunk_id",
          next_cursor: "c2",
          truncated: false,
        });
      }
      return Promise.resolve({
        schema_version: "v1",
        items: [preview("chunk-2", 2)],
        order_key: "ordinal,chunk_id",
        next_cursor: null,
        truncated: false,
      });
    });

    const pages: Array<{ ids: string[]; done: boolean }> = [];
    await new ApiFilesProvider().listRunChunkPreviews("run-1", (chunks, meta) =>
      pages.push({ ids: chunks.map((c) => c.id), done: meta.done }),
    );

    expect(pages).toEqual([
      { ids: ["chunk-1"], done: false },
      { ids: ["chunk-2"], done: true },
    ]);
    // Only the two /chunks list calls were made — no /chunks/{id} detail GETs.
    expect(auditGet).toHaveBeenCalledTimes(2);
  });
});

const profile = (id: string): TableProfileDto => ({
  schema_version: "v1",
  payload_id: id,
  columns: ["ФИО", "Оклад"],
  row_count: 42,
  summary: { label: `Таблица ${id}` },
});

const rowPage = (id: string): TableRowPageDto => ({
  schema_version: "v1",
  payload_id: id,
  columns: ["ФИО", "Оклад"],
  rows: [{ ФИО: "Каневский", Оклад: 100 }],
  next_cursor: null,
  truncated: false,
});

describe("ApiFilesProvider.hydrateRunTables", () => {
  it("combines profile + sample into a FileTablePayload per table", async () => {
    auditGet.mockImplementation((path: string) => {
      const id = path.split("/payloads/")[1].split("/")[0];
      return Promise.resolve(profile(id));
    });
    auditPost.mockImplementation((path: string) => {
      const id = path.split("/payloads/")[1].split("/")[0];
      return Promise.resolve(rowPage(id));
    });

    const tables = await new ApiFilesProvider().hydrateRunTables("run-1", ["t1", "t1", "t2"]);

    // Deduped: t1 requested twice -> one table.
    expect(tables.map((t) => t.id).sort()).toEqual(["t1", "t2"]);
    const t1 = tables.find((t) => t.id === "t1")!;
    expect(t1.summary).toBe("Таблица t1");
    expect(t1.schema).toEqual([
      { name: "ФИО", type: "" },
      { name: "Оклад", type: "" },
    ]);
    expect(t1.rowCount).toBe(42);
    expect(t1.columnCount).toBe(2);
    expect(t1.samples).toEqual([{ ФИО: "Каневский", Оклад: 100 }]);
    // The sample request carries the profile columns + a bounded limit.
    const sampleCall = auditPost.mock.calls.find(([p]) => p.includes("/table/sample"));
    expect(sampleCall?.[1]).toEqual({ columns: ["ФИО", "Оклад"], limit: 10 });
  });

  it("skips a table whose detail fetch fails, keeping the rest", async () => {
    auditGet.mockImplementation((path: string) => {
      const id = path.split("/payloads/")[1].split("/")[0];
      if (id === "bad") return Promise.reject(new Error("profile 404"));
      return Promise.resolve(profile(id));
    });
    auditPost.mockImplementation((path: string) => {
      const id = path.split("/payloads/")[1].split("/")[0];
      return Promise.resolve(rowPage(id));
    });

    const tables = await new ApiFilesProvider().hydrateRunTables("run-1", ["ok", "bad"]);
    expect(tables.map((t) => t.id)).toEqual(["ok"]);
  });
});
