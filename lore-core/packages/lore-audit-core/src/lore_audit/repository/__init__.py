"""Canonical bounded PostgreSQL reads for Splitter inspection.

The ``PostgresAuditReadRepository`` class is assembled here from three
split sub-modules:

- ``queries``   — SQL column strings and sort constants
- ``mapping``   — row-to-DTO parsing and semantic preflight computation
- ``cursoring`` — keyset pagination cursor helpers
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar
from uuid import UUID

from lore_audit.read_contracts import (
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
from lore_audit.postgres_connections import acquire_postgres_connection
from lore_audit.read_cursor import CursorCodec, TextWindowBuilder
from lore_audit.registration import parse_payload_registration
from lore_audit.validation import safe_json_to_dict
from lore_audit.run_status import RunStatus
from lore_audit.repository.queries import (
    _CHUNK_COLUMNS,
    _DIAGNOSTIC_SORT,
    _QUALIFIED_RUN_COLUMNS,
    _RUN_COLUMNS,
)
from lore_audit.repository.mapping import (
    build_semantic_preflight,
    compare_chunk_rows,
    empty_semantic_preflight,
    map_detail,
    map_diagnostic,
    map_file,
    map_occurrence,
    map_preview,
    map_run,
)
from lore_audit.repository.cursoring import decode_page_cursor, encode_page_cursor


T = TypeVar("T")


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
            last = decode_page_cursor(
                self.cursor_codec,
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
            items = tuple(map_file(row) for row in selected)
            next_cursor = None
            if truncated:
                item = items[-1]
                next_cursor = encode_page_cursor(
                    self.cursor_codec,
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
            return map_file(rows[0])

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
            last = decode_page_cursor(
                self.cursor_codec,
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
            items = tuple(map_run(row) for row in rows[: request.bounds.page_size])
            next_cursor = None
            if truncated:
                item = items[-1]
                next_cursor = encode_page_cursor(
                    self.cursor_codec,
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
            return map_run(rows[0], expected_run_id=run_id)

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
            run = map_run(row[:11], expected_run_id=run_id)
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
                return empty_semantic_preflight()

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
            return build_semantic_preflight(chunks, payloads, diagnostics)

        return self._transaction(load, self.statement_timeout_ms)

    def list_chunks(self, request: ChunkListRequest) -> ReadPage:
        if not isinstance(request, ChunkListRequest):
            raise AuditReadError("invalid_request")
        run_id = self._canonical_run_id(request.run_id)
        filters = {"run_id": run_id, "page_size": request.bounds.page_size}
        last: tuple[Any, ...] | None = None
        if request.cursor:
            last = decode_page_cursor(
                self.cursor_codec,
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
            items = tuple(map_preview(row) for row in rows[: request.bounds.page_size])
            next_cursor = None
            if truncated:
                next_cursor = encode_page_cursor(
                    self.cursor_codec,
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
            return map_detail(rows[0], request, self.text_windows)

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
            items = tuple(map_preview(row) for row in rows)
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
            items = tuple(map_preview(row) for row in rows)
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
            last = decode_page_cursor(
                self.cursor_codec,
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
            items = tuple(map_occurrence(row) for row in rows[: request.bounds.page_size])
            next_cursor = None
            if truncated:
                next_cursor = encode_page_cursor(
                    self.cursor_codec,
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
            last = decode_page_cursor(
                self.cursor_codec,
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
            items = tuple(map_diagnostic(row[:8]) for row in selected)
            next_cursor = None
            if truncated:
                tail = items[-1]
                next_cursor = encode_page_cursor(
                    self.cursor_codec,
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
            return compare_chunk_rows(left_id, right_id, logical_file_key, chunks)

        return self._transaction(load, self._timeout(request))

    # Delegate static mapper methods to module-level functions for backwards compat
    @staticmethod
    def _occurrence(row: Any) -> PayloadOccurrenceDetail:
        return map_occurrence(row)

    @staticmethod
    def _diagnostic(row: Any) -> DiagnosticDetail:
        return map_diagnostic(row)

    @staticmethod
    def _compare_chunk_rows(
        left_id: str,
        right_id: str,
        logical_file_key: str,
        rows: tuple[Any, ...],
    ) -> RunComparison:
        return compare_chunk_rows(left_id, right_id, logical_file_key, rows)

    @staticmethod
    def _file(row: Any) -> FileCard:
        return map_file(row)

    @staticmethod
    def _run(row: Any, *, expected_run_id: str | None = None) -> ReadRunDetail:
        return map_run(row, expected_run_id=expected_run_id)

    @staticmethod
    def _preview(row: Any) -> ChunkPreview:
        return map_preview(row)

    def _detail(self, row: Any, request: ChunkDetailRequest) -> ChunkDetail:
        return map_detail(row, request, self.text_windows)

    @staticmethod
    def _empty_semantic_preflight() -> SemanticPreflightCounts:
        return empty_semantic_preflight()

    @staticmethod
    def _build_semantic_preflight(
        chunks: tuple[Any, ...],
        payloads: tuple[Any, ...],
        diagnostics: tuple[Any, ...],
    ) -> SemanticPreflightCounts:
        return build_semantic_preflight(chunks, payloads, diagnostics)


__all__ = [
    "AuditCoreReadRepository",
    "PayloadReadResult",
    "PostgresAuditReadRepository",
    "RegisteredPayloadToken",
    "RegisteredSourceToken",
    "SourceReadResult",
]
