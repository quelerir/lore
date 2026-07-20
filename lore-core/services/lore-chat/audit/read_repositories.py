"""Canonical bounded PostgreSQL reads for Splitter inspection."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar
from uuid import UUID

from audit.read_contracts import (
    AuditReadError,
    Availability,
    ChunkBatchRequest,
    ChunkDetail,
    ChunkDetailRequest,
    ChunkListRequest,
    ChunkNeighborsRequest,
    ChunkPreview,
    DiagnosticDetail,
    DiagnosticListRequest,
    FileCard,
    FileCardRequest,
    FileListRequest,
    OccurrenceListRequest,
    PayloadDetail,
    PayloadOccurrenceDetail,
    PayloadRequest,
    ReadPage,
    ReadRunDetail,
    ReferenceBatchRequest,
    ReferenceResolution,
    RunCompareRequest,
    RunComparison,
    RunDetailRequest,
    RunListRequest,
    SemanticPreflightCounts,
    SourceContextRequest,
)
from audit.postgres_connections import acquire_postgres_connection
from audit.read_cursor import CursorCodec, TextWindowBuilder
from audit.registration import parse_payload_registration
from audit.validation import safe_json_to_dict
from audit._vendor.run_status import RunStatus


T = TypeVar("T")
_RUN_COLUMNS = (
    "run_id::text, logical_file_key, status, source_content_hash, config_hash, "
    "claimed_at, finished_at, chunk_count, payload_count, warning_count, error_count"
)
_QUALIFIED_RUN_COLUMNS = (
    "pr.run_id::text, pr.logical_file_key, pr.status, pr.source_content_hash, "
    "pr.config_hash, pr.claimed_at, pr.finished_at, pr.chunk_count, pr.payload_count, "
    "pr.warning_count, pr.error_count"
)
_CHUNK_COLUMNS = (
    "chunk_id, run_id::text, ordinal, pipeline_type, chunk_type, vector_text, fulltext, "
    "display_text, coordinates, payload_refs, content_signature, vector_text_hash, fulltext_hash"
)
_DIAGNOSTIC_SORT = "origin,coalesce(diagnostic_key,''),diagnostic_id"


@dataclass(frozen=True)
class RegisteredPayloadToken:
    """Internal physical registration; never serialized through the public DTO."""

    storage_kind: str
    identity: Any = field(repr=False)
    checksum_sha256: str | None = field(default=None, repr=False)
    byte_size: int | None = field(default=None, repr=False)
    content_type: str | None = field(default=None, repr=False)
    registration: Any = field(default=None, repr=False)


@dataclass(frozen=True)
class PayloadReadResult:
    detail: PayloadDetail
    token: RegisteredPayloadToken | None = field(default=None, repr=False)


@dataclass(frozen=True)
class RegisteredSourceToken:
    """Internal current-source locator authorized by an exact persisted run."""

    run_id: str
    expected_hash: str
    identity: Any = field(repr=False)

    def __post_init__(self) -> None:
        if not self.run_id or not self.expected_hash or self.identity is None:
            raise ValueError("invalid registered source token")


@dataclass(frozen=True)
class SourceReadResult:
    run: ReadRunDetail
    token: RegisteredSourceToken | None = field(default=None, repr=False)


class AuditCoreReadRepository(Protocol):
    def list_files(self, request: FileListRequest) -> ReadPage: ...

    def get_file(self, request: FileCardRequest) -> FileCard: ...

    def list_runs(self, request: RunListRequest) -> ReadPage: ...

    def get_run(self, request: RunDetailRequest) -> ReadRunDetail: ...

    def get_semantic_preflight_counts(self, run_id: str) -> SemanticPreflightCounts: ...

    def get_source(self, request: SourceContextRequest) -> SourceReadResult: ...

    def list_chunks(self, request: ChunkListRequest) -> ReadPage: ...

    def get_chunk(self, request: ChunkDetailRequest) -> ChunkDetail: ...

    def get_chunk_neighbors(
        self, request: ChunkNeighborsRequest
    ) -> tuple[ChunkPreview, ...]: ...

    def get_chunks(self, request: ChunkBatchRequest) -> tuple[ChunkPreview, ...]: ...

    def get_payload(self, request: PayloadRequest) -> PayloadReadResult: ...

    def list_occurrences(self, request: OccurrenceListRequest) -> ReadPage: ...

    def list_diagnostics(self, request: DiagnosticListRequest) -> ReadPage: ...

    def resolve_references(
        self, request: ReferenceBatchRequest
    ) -> tuple[ReferenceResolution, ...]: ...

    def compare_runs(self, request: RunCompareRequest) -> RunComparison: ...


class PostgresAuditReadRepository:
    """Execute one read-only repeatable-read transaction per logical operation."""

    def __init__(
        self,
        connection: Any,
        cursor_codec: CursorCodec,
        *,
        statement_timeout_ms: int = 5_000,
    ) -> None:
        if type(statement_timeout_ms) is not int or not 0 < statement_timeout_ms <= 10_000:
            raise ValueError("invalid audit statement timeout")
        self.connection = connection
        self.cursor_codec = cursor_codec
        self.text_windows = TextWindowBuilder(cursor_codec)
        self.statement_timeout_ms = statement_timeout_ms

    def _timeout(self, request: Any) -> int:
        bounds = getattr(request, "bounds", None)
        timeout_ms = getattr(bounds, "timeout_ms", None)
        if type(timeout_ms) is int and 0 < timeout_ms <= 10_000:
            return timeout_ms
        return self.statement_timeout_ms

    def _transaction(self, operation: Callable[[Any], T], timeout_ms: int) -> T:
        with acquire_postgres_connection(self.connection) as connection:
            cursor = connection.cursor()
            try:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cursor.execute(
                    "SELECT set_config('statement_timeout', %s, true)",
                    (f"{timeout_ms}ms",),
                )
                result = operation(cursor)
                connection.commit()
                return result
            except AuditReadError:
                connection.rollback()
                raise
            except (IndexError, KeyError, TypeError, ValueError):
                connection.rollback()
                raise AuditReadError("read_failed") from None
            except Exception as exc:
                connection.rollback()
                if getattr(exc, "sqlstate", None) == "57014":
                    raise AuditReadError("dependency_timeout") from None
                raise AuditReadError("read_failed") from None
            finally:
                cursor.close()

    @staticmethod
    def _canonical_run_id(value: str) -> str:
        try:
            canonical = str(UUID(value))
        except (AttributeError, TypeError, ValueError):
            raise AuditReadError("invalid_request") from None
        if canonical != value:
            raise AuditReadError("invalid_request")
        return canonical

    @staticmethod
    def _rows(cursor: Any, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...]:
        cursor.execute(sql, params)
        return tuple(cursor.fetchall())

    def list_files(self, request: FileListRequest) -> ReadPage:
        if not isinstance(request, FileListRequest):
            raise AuditReadError("invalid_request")
        filters = {
            "search": request.search,
            "statuses": [item.value for item in request.statuses],
            "page_size": request.bounds.page_size,
        }
        last: tuple[Any, ...] | None = None
        if request.cursor:
            last = self.cursor_codec.decode_page(
                request.cursor,
                operation="list_files",
                sort="display_name,logical_file_key",
                filters=filters,
            )
            if len(last) != 2 or not all(isinstance(item, str) for item in last):
                raise AuditReadError("invalid_cursor")

        def load(cursor: Any) -> ReadPage:
            clauses: list[str] = []
            params: list[Any] = []
            if request.search:
                clauses.append("lower(display_name) LIKE %s")
                params.append(f"%{request.search}%")
            if request.statuses:
                clauses.append("status = ANY(%s)")
                params.append([item.value for item in request.statuses])
            if last:
                clauses.append("(lower(display_name), logical_file_key) > (%s, %s)")
                params.extend(last)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            sql = (
                "WITH file_cards AS (SELECT pf.logical_file_key, "
                "COALESCE(NULLIF(pf.source_path,''), NULLIF(pf.object_path,''), "
                "pf.file_id, pf.logical_file_key) AS display_name, pf.status, "
                "(SELECT count(*) FROM lore_core.processing_runs pr "
                "WHERE pr.logical_file_key=pf.logical_file_key) AS run_count, "
                "pf.latest_run_id::text FROM lore_core.processed_files pf) "
                "SELECT logical_file_key, display_name, status, run_count, latest_run_id "
                f"FROM file_cards{where} ORDER BY lower(display_name), logical_file_key LIMIT %s"
            )
            params.append(request.bounds.page_size + 1)
            rows = self._rows(cursor, sql, tuple(params))
            truncated = len(rows) > request.bounds.page_size
            selected = rows[: request.bounds.page_size]
            items = tuple(self._file(row) for row in selected)
            next_cursor = None
            if truncated:
                item = items[-1]
                next_cursor = self.cursor_codec.encode_page(
                    operation="list_files",
                    sort="display_name,logical_file_key",
                    filters=filters,
                    last=item.sort_key,
                )
            return ReadPage(items, "display_name,logical_file_key", next_cursor, truncated)

        return self._transaction(load, self._timeout(request))

    def get_file(self, request: FileCardRequest) -> FileCard:
        if not isinstance(request, FileCardRequest):
            raise AuditReadError("invalid_request")

        def load(cursor: Any) -> FileCard:
            rows = self._rows(
                cursor,
                "SELECT pf.logical_file_key, "
                "COALESCE(NULLIF(pf.source_path,''), NULLIF(pf.object_path,''), "
                "pf.file_id, pf.logical_file_key) AS display_name, pf.status, "
                "(SELECT count(*) FROM lore_core.processing_runs pr "
                "WHERE pr.logical_file_key=pf.logical_file_key) AS run_count, "
                "pf.latest_run_id::text FROM lore_core.processed_files pf "
                "WHERE pf.logical_file_key=%s LIMIT %s",
                (request.logical_file_key, 2),
            )
            if len(rows) != 1 or rows[0][0] != request.logical_file_key:
                raise AuditReadError("not_found", resource="file")
            return self._file(rows[0])

        return self._transaction(load, self._timeout(request))

    def list_runs(self, request: RunListRequest) -> ReadPage:
        if not isinstance(request, RunListRequest):
            raise AuditReadError("invalid_request")
        filters = {
            "logical_file_key": request.logical_file_key,
            "page_size": request.bounds.page_size,
        }
        last: tuple[Any, ...] | None = None
        if request.cursor:
            last = self.cursor_codec.decode_page(
                request.cursor,
                operation="list_runs",
                sort="claimed_at,run_id",
                filters=filters,
            )
            if len(last) != 2 or not all(isinstance(item, str) for item in last):
                raise AuditReadError("invalid_cursor")

        def load(cursor: Any) -> ReadPage:
            params: list[Any] = [request.logical_file_key]
            keyset = ""
            if last:
                keyset = " AND (claimed_at, run_id) > (%s, %s::uuid)"
                params.extend(last)
            params.append(request.bounds.page_size + 1)
            rows = self._rows(
                cursor,
                f"SELECT {_RUN_COLUMNS} FROM lore_core.processing_runs "
                f"WHERE logical_file_key=%s{keyset} ORDER BY claimed_at, run_id LIMIT %s",
                tuple(params),
            )
            truncated = len(rows) > request.bounds.page_size
            items = tuple(self._run(row) for row in rows[: request.bounds.page_size])
            next_cursor = None
            if truncated:
                item = items[-1]
                next_cursor = self.cursor_codec.encode_page(
                    operation="list_runs",
                    sort="claimed_at,run_id",
                    filters=filters,
                    last=(item.claimed_at.isoformat(), item.run_id),
                )
            return ReadPage(items, "claimed_at,run_id", next_cursor, truncated)

        return self._transaction(load, self._timeout(request))

    def get_run(self, request: RunDetailRequest) -> ReadRunDetail:
        if not isinstance(request, RunDetailRequest):
            raise AuditReadError("invalid_request")
        run_id = self._canonical_run_id(request.run_id)

        def load(cursor: Any) -> ReadRunDetail:
            rows = self._rows(
                cursor,
                f"SELECT {_RUN_COLUMNS} FROM lore_core.processing_runs "
                "WHERE run_id=%s LIMIT %s",
                (run_id, 2),
            )
            if not rows:
                raise AuditReadError("not_found", resource="run")
            if len(rows) != 1:
                raise AuditReadError("read_failed")
            return self._run(rows[0], expected_run_id=run_id)

        return self._transaction(load, self._timeout(request))

    def get_source(self, request: SourceContextRequest) -> SourceReadResult:
        if not isinstance(request, SourceContextRequest):
            raise AuditReadError("invalid_request")
        run_id = self._canonical_run_id(request.run_id)

        def load(cursor: Any) -> SourceReadResult:
            rows = self._rows(
                cursor,
                f"SELECT {_QUALIFIED_RUN_COLUMNS}, pf.source_id, pf.stream, pf.file_id, "
                "pf.source_path, pf.object_path FROM lore_core.processing_runs pr "
                "JOIN lore_core.processed_files pf "
                "ON pf.logical_file_key=pr.logical_file_key "
                "WHERE pr.run_id=%s LIMIT %s",
                (run_id, 2),
            )
            if len(rows) != 1:
                raise AuditReadError("not_found", resource="source")
            row = rows[0]
            run = self._run(row[:11], expected_run_id=run_id)
            locator = tuple(row[11:])
            token = None
            if any(value not in (None, "") for value in locator[3:]):
                token = RegisteredSourceToken(run_id, run.source_content_hash, locator)
            return SourceReadResult(run, token)

        return self._transaction(load, self._timeout(request))

    def get_semantic_preflight_counts(self, run_id: str) -> SemanticPreflightCounts:
        run_id = self._canonical_run_id(run_id)

        def load(cursor: Any) -> SemanticPreflightCounts:
            run_rows = self._rows(
                cursor,
                "SELECT status /* semantic preflight run */ "
                "FROM lore_core.processing_runs WHERE run_id=%s LIMIT %s",
                (run_id, 2),
            )
            if len(run_rows) != 1:
                raise AuditReadError("not_found", resource="run")
            status = RunStatus(run_rows[0][0])
            if status in {RunStatus.FAILED, RunStatus.SKIPPED}:
                return self._empty_semantic_preflight()

            chunks = self._rows(
                cursor,
                "SELECT chunk_id, ordinal, pipeline_type, chunk_type, coordinates, "
                "payload_refs, NULL::integer AS content_size_unavailable "
                "/* semantic preflight chunks */ "
                "FROM lore_core.chunks WHERE run_id=%s ORDER BY ordinal, chunk_id",
                (run_id,),
            )
            payloads = self._rows(
                cursor,
                "SELECT payload_id, occurrence_ordinal, kind "
                "/* semantic preflight payloads */ FROM lore_core.payload_occurrences "
                "WHERE run_id=%s ORDER BY payload_id, occurrence_ordinal",
                (run_id,),
            )
            diagnostics = self._rows(
                cursor,
                "SELECT origin, level, diagnostic_key, code, chunk_id, payload_id "
                "/* semantic preflight diagnostics */ FROM lore_core.diagnostics "
                "WHERE run_id=%s ORDER BY origin, diagnostic_key, diagnostic_id",
                (run_id,),
            )
            return self._build_semantic_preflight(chunks, payloads, diagnostics)

        return self._transaction(load, self.statement_timeout_ms)

    @staticmethod
    def _empty_semantic_preflight() -> SemanticPreflightCounts:
        return SemanticPreflightCounts.from_dict({
            "targets": {key: 0 for key in SemanticPreflightCounts.target_fields},
            "diagnostics": {key: 0 for key in SemanticPreflightCounts.diagnostic_fields},
            "mandatory": {key: 0 for key in SemanticPreflightCounts.mandatory_fields},
        })

    @staticmethod
    def _build_semantic_preflight(
        chunks: tuple[Any, ...],
        payloads: tuple[Any, ...],
        diagnostics: tuple[Any, ...],
    ) -> SemanticPreflightCounts:
        if (
            any(len(row) != 7 for row in chunks)
            or any(len(row) != 3 for row in payloads)
            or any(len(row) != 6 for row in diagnostics)
        ):
            raise ValueError("invalid semantic preflight row")
        chunk_rows = sorted(chunks, key=lambda row: (row[1], row[0]))
        payload_ids = {row[0] for row in payloads}
        payload_kinds = {(row[0], row[1]): str(row[2]) for row in payloads}
        table_ids = {row[0] for row in payloads if str(row[2]).casefold() == "table"}
        image_ids = {row[0] for row in payloads if str(row[2]).casefold() == "image"}
        transcript_rows = [
            row
            for row in chunk_rows
            if "transcript" in str(row[2]).casefold()
            or "transcript" in str(row[3]).casefold()
        ]
        boundaries = sum(
            left[1] + 1 == right[1] and left[2] == right[2]
            for left, right in zip(chunk_rows, chunk_rows[1:])
        )
        groups = {
            (
                str(row[0]),
                str(row[2] or row[3]),
                str(row[4] or ""),
                str(row[5] or ""),
            )
            for row in diagnostics
        }
        diagnostic_targets = {
            (
                f"chunk:{row[4]}"
                if row[4]
                else f"payload:{row[5]}"
                if row[5]
                else f"diagnostic:{row[0]}:{row[2] or row[3]}"
            )
            for row in diagnostics
        }

        edge_ids = set()
        if chunk_rows:
            edge_ids = {chunk_rows[0][0], chunk_rows[-1][0]}
        sizes = [
            (row[6], row[0])
            for row in chunk_rows
            if type(row[6]) is int and row[6] >= 0
        ]
        size_ids = {min(sizes)[1], max(sizes)[1]} if sizes else set()
        type_ids: dict[tuple[str, str], str] = {}
        for row in chunk_rows:
            type_ids.setdefault((str(row[2]), str(row[3])), row[0])
        payload_type_ids: dict[str, str] = {}
        for payload_id, _, kind in payloads:
            payload_type_ids.setdefault(str(kind), payload_id)
        referenced: set[str] = set()
        for row in chunk_rows:
            raw_refs = row[5]
            if not isinstance(raw_refs, list):
                raise ValueError("invalid persisted payload refs")
            for item in raw_refs:
                if not isinstance(item, dict) or set(item) != {
                    "payload_id", "kind", "occurrence_ordinal"
                }:
                    raise ValueError("invalid persisted payload ref")
                payload_id = item["payload_id"]
                kind = item["kind"]
                ordinal = item["occurrence_ordinal"]
                if (
                    not isinstance(payload_id, str)
                    or not payload_id
                    or not isinstance(kind, str)
                    or not kind
                    or type(ordinal) is not int
                    or ordinal < 0
                ):
                    raise ValueError("invalid persisted payload ref")
                registered_kind = payload_kinds.get((payload_id, ordinal))
                if registered_kind is not None and registered_kind != kind:
                    raise ValueError("persisted payload ref kind mismatch")
                referenced.add(payload_id)
        broken = referenced - payload_ids

        speakers: set[str] = set()
        time_regions: set[tuple[int, int]] = set()
        transcript_chunk_ids: set[str] = set()
        for row in transcript_rows:
            coordinates = row[4]
            if not isinstance(coordinates, dict):
                continue
            raw_speakers = coordinates.get("speakers")
            if isinstance(raw_speakers, list):
                normalized = {
                    item.strip().casefold() for item in raw_speakers
                    if isinstance(item, str) and item.strip()
                }
                if normalized:
                    speakers.update(normalized)
                    transcript_chunk_ids.add(row[0])
            slots = coordinates.get("slot_boundaries")
            start, end = coordinates.get("start_ms"), coordinates.get("end_ms")
            if (
                isinstance(slots, list) and slots
                and all(
                    isinstance(item, str)
                    and bool(item.strip())
                    and len(item.encode("utf-8")) <= 512
                    for item in slots
                )
                and type(start) is int and type(end) is int and 0 <= start <= end
            ):
                time_regions.add((start, end))
                transcript_chunk_ids.add(row[0])

        mandatory = (
            diagnostic_targets
            | {
                f"chunk:{item}"
                for item in edge_ids
                | size_ids
                | set(type_ids.values())
                | transcript_chunk_ids
            }
            | {f"payload:{item}" for item in set(payload_type_ids.values()) | broken}
        )
        table_targets = {f"payload:{item}" for item in table_ids} & mandatory
        targets = {
            "chunks": len(chunk_rows),
            "boundaries": boundaries,
            "source_comparisons": 1,
            "tables": len(table_ids),
            "images": len(image_ids),
            "transcript_blocks": len(transcript_rows),
            "linked_diagnostic_groups": len(groups),
            "final_synthesis": 1,
        }
        diagnostic_counts = {
            "processing": sum(row[0] != "audit_rule" for row in diagnostics),
            "audit_rule": sum(row[0] == "audit_rule" for row in diagnostics),
            "critical": sum(str(row[1]).casefold() == "critical" for row in diagnostics),
            "warning": sum(str(row[1]).casefold() == "warning" for row in diagnostics),
        }
        mandatory_counts = {
            "deduplicated_targets": len(mandatory),
            "semantic_actions": len(mandatory) + len(table_targets),
            "diagnostic_linked_targets": len(diagnostic_targets),
            "edge_chunks": len(edge_ids),
            "size_extremes": len(size_ids),
            "chunk_types": len(type_ids),
            "payload_types": len(payload_type_ids),
            "broken_references": len(broken),
            "transcript_speakers": len(speakers),
            "transcript_time_regions": len(time_regions),
        }
        return SemanticPreflightCounts.from_dict(
            {
                "targets": targets,
                "diagnostics": diagnostic_counts,
                "mandatory": mandatory_counts,
            }
        )

    def list_chunks(self, request: ChunkListRequest) -> ReadPage:
        if not isinstance(request, ChunkListRequest):
            raise AuditReadError("invalid_request")
        run_id = self._canonical_run_id(request.run_id)
        filters = {"run_id": run_id, "page_size": request.bounds.page_size}
        last: tuple[Any, ...] | None = None
        if request.cursor:
            last = self.cursor_codec.decode_page(
                request.cursor,
                operation="list_chunks",
                sort="ordinal,chunk_id",
                filters=filters,
            )
            if (
                len(last) != 2
                or type(last[0]) is not int
                or not isinstance(last[1], str)
            ):
                raise AuditReadError("invalid_cursor")

        def load(cursor: Any) -> ReadPage:
            params: list[Any] = [run_id]
            keyset = ""
            if last:
                keyset = " AND (ordinal, chunk_id) > (%s, %s)"
                params.extend(last)
            params.append(request.bounds.page_size + 1)
            rows = self._rows(
                cursor,
                "SELECT chunk_id, run_id::text, ordinal, pipeline_type, chunk_type, "
                "content_signature FROM lore_core.chunks WHERE run_id=%s"
                f"{keyset} ORDER BY ordinal, chunk_id LIMIT %s",
                tuple(params),
            )
            truncated = len(rows) > request.bounds.page_size
            items = tuple(self._preview(row) for row in rows[: request.bounds.page_size])
            next_cursor = None
            if truncated:
                next_cursor = self.cursor_codec.encode_page(
                    operation="list_chunks",
                    sort="ordinal,chunk_id",
                    filters=filters,
                    last=items[-1].sort_key,
                )
            return ReadPage(items, "ordinal,chunk_id", next_cursor, truncated)

        return self._transaction(load, self._timeout(request))

    def get_chunk(self, request: ChunkDetailRequest) -> ChunkDetail:
        if not isinstance(request, ChunkDetailRequest):
            raise AuditReadError("invalid_request")
        run_id = self._canonical_run_id(request.run_id)

        def load(cursor: Any) -> ChunkDetail:
            rows = self._rows(
                cursor,
                f"SELECT {_CHUNK_COLUMNS} FROM lore_core.chunks "
                "WHERE run_id=%s AND chunk_id=%s LIMIT %s",
                (run_id, request.chunk_id, 2),
            )
            if not rows:
                raise AuditReadError("not_found", resource="chunk")
            if len(rows) != 1 or rows[0][1] != run_id:
                raise AuditReadError("membership_mismatch", resource="chunk")
            return self._detail(rows[0], request)

        return self._transaction(load, self._timeout(request))

    def get_chunk_neighbors(
        self, request: ChunkNeighborsRequest
    ) -> tuple[ChunkPreview, ...]:
        if not isinstance(request, ChunkNeighborsRequest):
            raise AuditReadError("invalid_request")
        run_id = self._canonical_run_id(request.run_id)

        def load(cursor: Any) -> tuple[ChunkPreview, ...]:
            rows = self._rows(
                cursor,
                "SELECT chunk_id, run_id::text, ordinal, pipeline_type, chunk_type, "
                "content_signature FROM lore_core.chunks WHERE run_id=%s AND ordinal BETWEEN "
                "(SELECT ordinal FROM lore_core.chunks WHERE run_id=%s AND chunk_id=%s)-%s "
                "AND (SELECT ordinal FROM lore_core.chunks WHERE run_id=%s AND chunk_id=%s)+%s "
                "ORDER BY ordinal, chunk_id LIMIT %s",
                (
                    run_id,
                    run_id,
                    request.chunk_id,
                    request.before,
                    run_id,
                    request.chunk_id,
                    request.after,
                    request.before + request.after + 2,
                ),
            )
            items = tuple(self._preview(row) for row in rows)
            if not any(item.chunk_id == request.chunk_id for item in items):
                raise AuditReadError("not_found", resource="chunk")
            return tuple(sorted(items, key=lambda item: item.sort_key))

        return self._transaction(load, self._timeout(request))

    def get_chunks(self, request: ChunkBatchRequest) -> tuple[ChunkPreview, ...]:
        if not isinstance(request, ChunkBatchRequest):
            raise AuditReadError("invalid_request")
        run_id = self._canonical_run_id(request.run_id)

        def load(cursor: Any) -> tuple[ChunkPreview, ...]:
            rows = self._rows(
                cursor,
                "SELECT chunk_id, run_id::text, ordinal, pipeline_type, chunk_type, "
                "content_signature FROM lore_core.chunks WHERE run_id=%s "
                "AND chunk_id = ANY(%s) ORDER BY ordinal, chunk_id LIMIT %s",
                (run_id, list(request.chunk_ids), len(request.chunk_ids) + 1),
            )
            items = tuple(self._preview(row) for row in rows)
            if {item.chunk_id for item in items} != set(request.chunk_ids):
                raise AuditReadError("membership_mismatch", resource="chunk")
            return tuple(sorted(items, key=lambda item: item.sort_key))

        return self._transaction(load, self._timeout(request))

    def get_payload(self, request: PayloadRequest) -> PayloadReadResult:
        if not isinstance(request, PayloadRequest):
            raise AuditReadError("invalid_request")
        run_id = self._canonical_run_id(request.run_id)

        def load(cursor: Any) -> PayloadReadResult:
            occurrences = self._rows(
                cursor,
                "SELECT run_id::text, payload_id, occurrence_ordinal, kind, NULL::text, "
                "coordinates FROM lore_core.payload_occurrences "
                "WHERE run_id=%s AND payload_id=%s ORDER BY payload_id, occurrence_ordinal "
                "LIMIT %s",
                (run_id, request.payload_id, 10_001),
            )
            if not occurrences:
                raise AuditReadError("membership_mismatch", resource="payload")
            if any(row[0] != run_id or row[1] != request.payload_id for row in occurrences):
                raise AuditReadError("membership_mismatch", resource="payload")
            rows = self._rows(
                cursor,
                "SELECT payload_id, kind, storage, storage_uri, content_hash, metadata "
                "FROM lore_core.payloads WHERE payload_id=%s LIMIT %s",
                (request.payload_id, 2),
            )
            if len(rows) != 1 or rows[0][0] != request.payload_id:
                raise AuditReadError("not_found", resource="payload")
            row = rows[0]
            try:
                fact = parse_payload_registration(row[0], row[1], row[5], len(occurrences))
            except ValueError:
                raise AuditReadError("registration_invalid", resource="payload") from None
            detail = PayloadDetail(
                run_id=run_id,
                payload_id=row[0],
                kind=row[1],
                registered=fact.registered,
                availability=(
                    Availability.AVAILABLE if fact.registered else Availability.UNAVAILABLE
                ),
                summary=fact.summary,
                reason_code=None if fact.registered else "unregistered",
            )
            token = None
            if fact.registered:
                if fact.physical is None or not fact.physical.resolved:
                    raise AuditReadError("registration_invalid", resource="payload")
                token = RegisteredPayloadToken(
                    storage_kind=fact.physical.storage_kind,
                    identity=safe_json_to_dict(fact.physical.identity),
                    checksum_sha256=fact.physical.checksum_sha256,
                    byte_size=fact.physical.byte_size,
                    content_type=fact.physical.content_type,
                    registration=safe_json_to_dict(fact.registration_identity),
                )
            return PayloadReadResult(detail, token)

        return self._transaction(load, self._timeout(request))

    def list_occurrences(self, request: OccurrenceListRequest) -> ReadPage:
        if not isinstance(request, OccurrenceListRequest):
            raise AuditReadError("invalid_request")
        run_id = self._canonical_run_id(request.run_id)
        filters = {
            "run_id": run_id,
            "payload_id": request.payload_id,
            "page_size": request.bounds.page_size,
        }
        last: tuple[Any, ...] | None = None
        if request.cursor:
            last = self.cursor_codec.decode_page(
                request.cursor,
                operation="list_occurrences",
                sort="payload_id,occurrence_ordinal",
                filters=filters,
            )
            if len(last) != 2 or not isinstance(last[0], str) or type(last[1]) is not int:
                raise AuditReadError("invalid_cursor")

        def load(cursor: Any) -> ReadPage:
            params: list[Any] = [run_id, request.payload_id]
            keyset = ""
            if last:
                keyset = " AND (payload_id, occurrence_ordinal) > (%s, %s)"
                params.extend(last)
            params.append(request.bounds.page_size + 1)
            rows = self._rows(
                cursor,
                "SELECT run_id::text, payload_id, occurrence_ordinal, kind, NULL::text, "
                "coordinates FROM lore_core.payload_occurrences WHERE run_id=%s "
                f"AND payload_id=%s{keyset} ORDER BY payload_id, occurrence_ordinal LIMIT %s",
                tuple(params),
            )
            truncated = len(rows) > request.bounds.page_size
            items = tuple(self._occurrence(row) for row in rows[: request.bounds.page_size])
            next_cursor = None
            if truncated:
                next_cursor = self.cursor_codec.encode_page(
                    operation="list_occurrences",
                    sort="payload_id,occurrence_ordinal",
                    filters=filters,
                    last=items[-1].sort_key,
                )
            return ReadPage(items, "payload_id,occurrence_ordinal", next_cursor, truncated)

        return self._transaction(load, self._timeout(request))

    def list_diagnostics(self, request: DiagnosticListRequest) -> ReadPage:
        if not isinstance(request, DiagnosticListRequest):
            raise AuditReadError("invalid_request")
        run_id = self._canonical_run_id(request.run_id)
        filters = {
            "run_id": run_id,
            "origins": list(request.origins),
            "page_size": request.bounds.page_size,
        }
        last: tuple[Any, ...] | None = None
        if request.cursor:
            last = self.cursor_codec.decode_page(
                request.cursor,
                operation="list_diagnostics",
                sort=_DIAGNOSTIC_SORT,
                filters=filters,
            )
            if len(last) != 3 or not all(isinstance(item, str) for item in last):
                raise AuditReadError("invalid_cursor")

        def load(cursor: Any) -> ReadPage:
            params: list[Any] = [run_id, list(request.origins)]
            keyset = ""
            if last:
                keyset = (
                    " AND (origin, coalesce(diagnostic_key,''), diagnostic_id) "
                    "> (%s, %s, %s::bigint)"
                )
                params.extend(last)
            params.append(request.bounds.page_size + 1)
            rows = self._rows(
                cursor,
                "SELECT diagnostic_id::text, run_id::text, origin, code, level, "
                "diagnostic_key, chunk_id, payload_id, coalesce(diagnostic_key,'') "
                "AS diagnostic_sort_key FROM lore_core.diagnostics "
                "WHERE run_id=%s AND origin = ANY(%s)"
                f"{keyset} ORDER BY {_DIAGNOSTIC_SORT} LIMIT %s",
                tuple(params),
            )
            truncated = len(rows) > request.bounds.page_size
            selected = rows[: request.bounds.page_size]
            items = tuple(self._diagnostic(row[:8]) for row in selected)
            next_cursor = None
            if truncated:
                tail = items[-1]
                next_cursor = self.cursor_codec.encode_page(
                    operation="list_diagnostics",
                    sort=_DIAGNOSTIC_SORT,
                    filters=filters,
                    last=(tail.origin, selected[-1][8], tail.diagnostic_id),
                )
            return ReadPage(items, _DIAGNOSTIC_SORT, next_cursor, truncated)

        return self._transaction(load, self._timeout(request))

    def resolve_references(
        self, request: ReferenceBatchRequest
    ) -> tuple[ReferenceResolution, ...]:
        if not isinstance(request, ReferenceBatchRequest):
            raise AuditReadError("invalid_request")
        run_id = self._canonical_run_id(request.run_id)

        def load(cursor: Any) -> tuple[ReferenceResolution, ...]:
            payload_ids = sorted({item[0] for item in request.references})
            occurrences = self._rows(
                cursor,
                "SELECT run_id::text, payload_id, occurrence_ordinal, kind, NULL::text, "
                "coordinates FROM lore_core.payload_occurrences WHERE run_id=%s "
                "AND payload_id = ANY(%s) ORDER BY payload_id, occurrence_ordinal LIMIT %s",
                (run_id, payload_ids, len(payload_ids) * 10_000 + 1),
            )
            occurrence_kinds: dict[str, str] = {}
            for row in occurrences:
                occurrence_kinds.setdefault(row[1], row[3])
            registered: dict[str, bool] = {}
            present = sorted(occurrence_kinds)
            if present:
                rows = self._rows(
                    cursor,
                    "SELECT payload_id, kind, storage, storage_uri, content_hash, metadata "
                    "FROM lore_core.payloads WHERE payload_id = ANY(%s) ORDER BY payload_id "
                    "LIMIT %s",
                    (present, len(present) + 1),
                )
                for row in rows:
                    try:
                        fact = parse_payload_registration(row[0], row[1], row[5], 1)
                    except ValueError:
                        fact = None
                    registered[row[0]] = bool(fact and fact.registered)
            result = []
            for payload_id, kind in request.references:
                actual_kind = occurrence_kinds.get(payload_id)
                if actual_kind is None:
                    available, is_registered, reason = (
                        Availability.UNAVAILABLE,
                        False,
                        "missing_occurrence",
                    )
                elif actual_kind != kind:
                    available, is_registered, reason = Availability.UNAVAILABLE, False, "kind_mismatch"
                elif registered.get(payload_id):
                    available, is_registered, reason = Availability.AVAILABLE, True, None
                else:
                    available, is_registered, reason = Availability.UNAVAILABLE, False, "unregistered"
                result.append(
                    ReferenceResolution(run_id, payload_id, kind, available, is_registered, reason)
                )
            return tuple(result)

        return self._transaction(load, self._timeout(request))

    def compare_runs(self, request: RunCompareRequest) -> RunComparison:
        if not isinstance(request, RunCompareRequest):
            raise AuditReadError("invalid_request")
        left_id = self._canonical_run_id(request.left_run_id)
        right_id = self._canonical_run_id(request.right_run_id)

        def load(cursor: Any) -> RunComparison:
            runs = self._rows(
                cursor,
                "/* comparison processing_runs */ SELECT run_id::text, logical_file_key "
                "FROM lore_core.processing_runs WHERE run_id = ANY(%s) ORDER BY run_id",
                ([left_id, right_id],),
            )
            if len(runs) != 2 or {row[0] for row in runs} != {left_id, right_id}:
                raise AuditReadError("not_found", resource="run")
            if len({row[1] for row in runs}) != 1:
                raise AuditReadError("membership_mismatch", resource="run")
            logical_file_key = runs[0][1]
            chunks = self._rows(
                cursor,
                "/* comparison chunks */ SELECT run_id::text, chunk_id, ordinal, "
                "content_signature, chunk_type, coordinates FROM lore_core.chunks "
                "WHERE run_id = ANY(%s) ORDER BY run_id, ordinal, chunk_id",
                ([left_id, right_id],),
            )
            self._rows(
                cursor,
                "/* comparison payload_occurrences */ SELECT run_id::text, payload_id, "
                "occurrence_ordinal FROM lore_core.payload_occurrences WHERE run_id = ANY(%s) "
                "ORDER BY run_id, payload_id, occurrence_ordinal",
                ([left_id, right_id],),
            )
            return self._compare_chunk_rows(left_id, right_id, logical_file_key, chunks)

        return self._transaction(load, self._timeout(request))

    @staticmethod
    def _occurrence(row: Any) -> PayloadOccurrenceDetail:
        if len(row) != 6:
            raise ValueError
        return PayloadOccurrenceDetail(
            run_id=row[0],
            payload_id=row[1],
            occurrence_ordinal=row[2],
            kind=row[3],
            chunk_id=row[4],
            coordinates=row[5],
        )

    @staticmethod
    def _diagnostic(row: Any) -> DiagnosticDetail:
        if len(row) != 8:
            raise ValueError
        return DiagnosticDetail(
            diagnostic_id=row[0],
            run_id=row[1],
            origin=row[2],
            code=row[3],
            level=row[4],
            diagnostic_key=row[5],
            chunk_id=row[6],
            payload_id=row[7],
        )

    @staticmethod
    def _compare_chunk_rows(
        left_id: str,
        right_id: str,
        logical_file_key: str,
        rows: tuple[Any, ...],
    ) -> RunComparison:
        if any(len(row) != 6 or row[0] not in {left_id, right_id} for row in rows):
            raise ValueError
        left = [row for row in rows if row[0] == left_id]
        right = [row for row in rows if row[0] == right_id]
        unchanged: list[str] = []

        def group_by_signature(values: list[Any]) -> dict[str, list[Any]]:
            groups: dict[str, list[Any]] = {}
            for row in values:
                groups.setdefault(row[3], []).append(row)
            for group in groups.values():
                group.sort(key=lambda item: (item[2], item[1]))
            return groups

        left_signatures = group_by_signature(left)
        right_signatures = group_by_signature(right)
        left_remaining: list[Any] = []
        right_remaining: list[Any] = []
        for signature in sorted(set(left_signatures) | set(right_signatures)):
            left_group = left_signatures.get(signature, [])
            right_group = right_signatures.get(signature, [])
            common = min(len(left_group), len(right_group))
            unchanged.extend(row[1] for row in left_group[:common])
            left_remaining.extend(left_group[common:])
            right_remaining.extend(right_group[common:])

        def structural_key(row: Any) -> tuple[str, str]:
            return (
                row[4],
                json.dumps(row[5], ensure_ascii=True, sort_keys=True, separators=(",", ":")),
            )

        def group_structurally(values: list[Any]) -> dict[tuple[str, str], list[Any]]:
            groups: dict[tuple[str, str], list[Any]] = {}
            for row in values:
                groups.setdefault(structural_key(row), []).append(row)
            for group in groups.values():
                group.sort(key=lambda item: (item[2], item[1]))
            return groups

        left_structural = group_structurally(left_remaining)
        right_structural = group_structurally(right_remaining)
        changed: list[tuple[str, str]] = []
        removed: list[str] = []
        added: list[str] = []
        for key in sorted(set(left_structural) | set(right_structural)):
            left_group = left_structural.get(key, [])
            right_group = right_structural.get(key, [])
            common = min(len(left_group), len(right_group))
            changed.extend(
                (left_group[index][1], right_group[index][1]) for index in range(common)
            )
            removed.extend(row[1] for row in left_group[common:])
            added.extend(row[1] for row in right_group[common:])
        return RunComparison(
            left_id,
            right_id,
            logical_file_key,
            tuple(unchanged),
            tuple(changed),
            tuple(added),
            tuple(removed),
        )

    @staticmethod
    def _file(row: Any) -> FileCard:
        if len(row) != 5:
            raise ValueError
        return FileCard(row[0], row[1], RunStatus(row[2]), row[3], row[4])

    @staticmethod
    def _run(row: Any, *, expected_run_id: str | None = None) -> ReadRunDetail:
        if len(row) != 11 or (expected_run_id is not None and row[0] != expected_run_id):
            raise ValueError
        return ReadRunDetail(
            run_id=row[0],
            logical_file_key=row[1],
            status=RunStatus(row[2]),
            source_content_hash=row[3],
            config_hash=row[4],
            claimed_at=row[5],
            finished_at=row[6],
            chunk_count=row[7],
            payload_count=row[8],
            warning_count=row[9],
            error_count=row[10],
        )

    @staticmethod
    def _preview(row: Any) -> ChunkPreview:
        if len(row) != 6:
            raise ValueError
        return ChunkPreview(
            chunk_id=row[0],
            run_id=row[1],
            ordinal=row[2],
            pipeline_type=row[3],
            chunk_type=row[4],
            content_signature=row[5],
        )

    def _detail(self, row: Any, request: ChunkDetailRequest) -> ChunkDetail:
        if len(row) != 13:
            raise ValueError
        preview = ChunkPreview(
            chunk_id=row[0],
            run_id=row[1],
            ordinal=row[2],
            pipeline_type=row[3],
            chunk_type=row[4],
            content_signature=row[10],
        )
        display_hash = hashlib.sha256(row[7].encode("utf-8")).hexdigest()
        return ChunkDetail(
            preview=preview,
            display_text=self.text_windows.window(
                row[7],
                run_id=row[1],
                chunk_id=row[0],
                field="display_text",
                content_hash=display_hash,
                max_bytes=request.bounds.max_text_bytes,
                continuation=request.display_continuation,
            ),
            full_text=self.text_windows.window(
                row[6],
                run_id=row[1],
                chunk_id=row[0],
                field="full_text",
                content_hash=row[12],
                max_bytes=request.bounds.max_text_bytes,
                continuation=request.full_continuation,
            ),
            vector_text=self.text_windows.window(
                row[5],
                run_id=row[1],
                chunk_id=row[0],
                field="vector_text",
                content_hash=row[11],
                max_bytes=request.bounds.max_text_bytes,
                continuation=request.vector_continuation,
            ),
            coordinates=row[8],
            payload_refs=tuple(row[9]),
        )


__all__ = [
    "AuditCoreReadRepository",
    "PayloadReadResult",
    "PostgresAuditReadRepository",
    "RegisteredPayloadToken",
]
