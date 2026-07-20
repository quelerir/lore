// Map real audit-read DTOs to the FileViewer's UI types (see types.ts).
import type { FileRecord, FileRun, RunStatus } from "./types";

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
