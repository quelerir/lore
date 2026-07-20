// Map real audit-read DTOs to the FileViewer's UI types (see types.ts).
import type { FileRecord, RunStatus } from "./types";

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
