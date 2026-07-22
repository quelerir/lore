// Map real audit-read DTOs to the FileViewer's UI types (see types.ts).
import type {
  FileChunk,
  FileChunkPayloadRef,
  FileRecord,
  FileRun,
  FileTablePayload,
  RunStatus,
} from "./types";

export interface FileCardDto {
  schema_version: string;
  logical_file_key: string;
  display_name: string;
  latest_status: string;
  run_count: number;
  latest_run_id: string | null;
}

export interface PageDto<T> {
  schema_version: string;
  items: T[];
  order_key: string;
  next_cursor: string | null;
  truncated: boolean;
}

// The UI's RunStatus has no "stale" bucket; map it to the nearest display state.
// (stale = superseded, not a hard failure — shown as skipped.)
export function mapRunStatus(status: string): RunStatus {
  return status === "stale" ? "skipped" : (status as RunStatus);
}

export interface PayloadDetailDto {
  schema_version: string;
  run_id: string;
  payload_id: string;
  kind: string;
  registered: boolean;
  summary: Record<string, unknown>;
  reason_code: string | null;
}

// Resolve a chunk payload reference to its type so the inspector can route it to
// the table/image/transcript view. Detail views themselves are wired later.
export function mapPayloadRef(dto: PayloadDetailDto): FileChunkPayloadRef {
  const type: FileChunkPayloadRef["type"] =
    dto.kind === "image" || dto.kind === "transcript" ? dto.kind : "table";
  const label = typeof dto.summary?.label === "string" ? dto.summary.label : dto.payload_id;
  return { type, id: dto.payload_id, label };
}

export interface TableProfileDto {
  schema_version: string;
  payload_id: string;
  columns: string[];
  row_count: number;
  summary: Record<string, unknown>;
}

export interface TableRowPageDto {
  schema_version: string;
  payload_id: string;
  columns: string[];
  rows: Array<Record<string, unknown>>;
  next_cursor: string | null;
  truncated: boolean;
}

// Combine a table's profile (columns + row_count + summary) with a sampled page of
// rows into the UI's FileTablePayload (the payloads-tab inspector renders it). The
// backend profile carries column NAMES only (no dtype), so type is left blank.
export function mapTablePayload(
  profile: TableProfileDto,
  sample: TableRowPageDto,
): FileTablePayload {
  const label =
    typeof profile.summary?.label === "string" ? profile.summary.label : profile.payload_id;
  return {
    id: profile.payload_id,
    summary: label,
    coordinates: "",
    schema: profile.columns.map((name) => ({ name, type: "" })),
    rowCount: profile.row_count,
    columnCount: profile.columns.length,
    samples: sample.rows as Array<Record<string, string | number | null>>,
    contentId: profile.payload_id,
    usages: [],
    relatedChunkIds: [],
  };
}

export interface ChunkPreviewDto {
  schema_version: string;
  chunk_id: string;
  run_id: string;
  ordinal: number;
  pipeline_type: string;
  chunk_type: string;
  content_signature: string;
}

export interface TextWindowDto {
  text: string;
  truncated: boolean;
  returned_bytes: number;
  full_bytes: number;
}

export interface ChunkDetailDto {
  schema_version: string;
  preview: ChunkPreviewDto;
  display_text: TextWindowDto;
  full_text: TextWindowDto;
  vector_text: TextWindowDto;
  coordinates: Record<string, unknown>;
  payload_refs: string[];
}

function formatCoordinates(coordinates: Record<string, unknown>): string {
  if (!coordinates || Object.keys(coordinates).length === 0) return "";
  return Object.entries(coordinates)
    .map(([key, value]) => `${key}:${typeof value === "object" ? JSON.stringify(value) : value}`)
    .join(" ");
}

// Chunk list preview: metadata only (no text yet — filled by mapChunkDetail on
// selection). payloads/diagnostics are populated by later slices.
export function mapChunkPreview(dto: ChunkPreviewDto): FileChunk {
  return {
    id: dto.chunk_id,
    ordinal: dto.ordinal,
    type: dto.chunk_type,
    coordinates: "",
    section: "",
    displayText: "",
    fullText: "",
    vectorText: "",
    charCount: 0,
    tokenCount: 0,
    hash: dto.content_signature,
    contentSignature: dto.content_signature,
    warnings: [],
    findings: [],
    payloads: [],
    metadata: {},
    diagnostics: [],
  };
}

export function mapChunkDetail(dto: ChunkDetailDto): FileChunk {
  const preview = dto.preview;
  return {
    id: preview.chunk_id,
    ordinal: preview.ordinal,
    type: preview.chunk_type,
    coordinates: formatCoordinates(dto.coordinates),
    section: "",
    displayText: dto.display_text.text,
    fullText: dto.full_text.text,
    vectorText: dto.vector_text.text,
    charCount: dto.full_text.text.length,
    tokenCount: 0,
    hash: preview.content_signature,
    contentSignature: preview.content_signature,
    warnings: [],
    findings: [],
    payloads: [],
    metadata: {},
    diagnostics: [],
  };
}

export interface RunDetailDto {
  schema_version: string;
  run_id: string;
  logical_file_key: string;
  status: string;
  source_content_hash: string;
  config_hash: string;
  claimed_at: string;
  finished_at: string | null;
  chunk_count: number;
  payload_count: number;
  warning_count: number;
  error_count: number;
}

function formatRunLabel(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "Запуск";
  return `Запуск ${date.toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}`;
}

// Run metadata only; chunks/tables/images/transcripts are hydrated lazily in a
// later slice (empty here). Message-level warnings/errors come from diagnostics.
export function mapRun(dto: RunDetailDto): FileRun {
  return {
    id: dto.run_id,
    label: formatRunLabel(dto.claimed_at),
    processedAt: dto.claimed_at,
    status: mapRunStatus(dto.status),
    pipeline: "",
    autoAuditStatus: "missing",
    sourceUrl: "",
    warnings: [],
    errors: [],
    chunks: [],
    tables: [],
    images: [],
    transcripts: [],
  };
}

// A file list card carries no run/chunk detail. We synthesise a single
// placeholder run so the existing (eager) UI renders the real status and file
// without crashing; hydrateFile replaces it with real runs on selection.
export function mapFileCard(dto: FileCardDto): FileRecord {
  return {
    id: dto.logical_file_key,
    name: dto.display_name,
    type: "",
    pipeline: "",
    runs: [
      {
        id: dto.latest_run_id ?? `${dto.logical_file_key}:latest`,
        label: `Прогонов: ${dto.run_count}`,
        processedAt: "",
        status: mapRunStatus(dto.latest_status),
        pipeline: "",
        autoAuditStatus: "missing",
        sourceUrl: "",
        warnings: [],
        errors: [],
        chunks: [],
        tables: [],
        images: [],
        transcripts: [],
      },
    ],
  };
}
