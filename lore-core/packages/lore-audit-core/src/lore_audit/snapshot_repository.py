"""Bounded exact-run audit snapshot repository."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from lore_audit.contracts import (
    AuditChunk,
    AuditPayloadOccurrence,
    AuditRun,
    AuditSnapshot,
    ProcessingDiagnostic,
)
from lore_audit.engine_contracts import PayloadResolutionFact
from lore_audit.registration import parse_payload_registration
from lore_core_domain.run_status import RunStatus


_BOUNDS_ERROR = "invalid audit read bounds"
_ERROR_MESSAGES = {
    "invalid_request": "audit repository request is invalid",
    "snapshot_unavailable": "exact audit snapshot is unavailable",
    "snapshot_invalid": "exact audit snapshot is invalid",
    "snapshot_bounds": "exact audit snapshot exceeds configured bounds",
    "read_failed": "exact audit snapshot read failed",
}
_COUNT_CAP = 1_000_000
_BYTE_CAP = 1_000_000_000


class AuditRepositoryError(RuntimeError):
    """Safe fixed-category repository failure."""

    def __init__(self, category: str) -> None:
        if category not in _ERROR_MESSAGES:
            category = "read_failed"
        self.category = category
        super().__init__(_ERROR_MESSAGES[category])


@dataclass(frozen=True)
class AuditReadBounds:
    """Explicit caps applied before persisted values become domain objects."""

    max_runs: int = 1
    max_chunks: int = 100_000
    max_occurrences: int = 100_000
    max_diagnostics: int = 100_000
    max_payloads: int = 100_000
    max_text_bytes: int = 4_000_000
    max_aggregate_text_bytes: int = 100_000_000
    max_json_bytes: int = 1_000_000
    max_registration_bytes: int = 8_192

    def __post_init__(self) -> None:
        counts = (
            self.max_runs,
            self.max_chunks,
            self.max_occurrences,
            self.max_diagnostics,
            self.max_payloads,
        )
        byte_limits = (
            self.max_text_bytes,
            self.max_aggregate_text_bytes,
            self.max_json_bytes,
            self.max_registration_bytes,
        )
        valid = (
            all(type(value) is int and 0 < value <= _COUNT_CAP for value in counts)
            and all(type(value) is int and 0 < value <= _BYTE_CAP for value in byte_limits)
            and self.max_runs == 1
            and self.max_aggregate_text_bytes >= self.max_text_bytes
        )
        if not valid:
            raise ValueError(_BOUNDS_ERROR)


@dataclass(frozen=True)
class AuditSnapshotBundle:
    """Immutable snapshot plus registration-derived facts; token facts stay unavailable."""

    snapshot: AuditSnapshot
    payload_facts: tuple[PayloadResolutionFact, ...]
    token_facts: tuple[()] = field(default=(), init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot, AuditSnapshot):
            raise AuditRepositoryError("snapshot_invalid")
        facts = tuple(self.payload_facts)
        if any(not isinstance(item, PayloadResolutionFact) for item in facts):
            raise AuditRepositoryError("snapshot_invalid")
        if len({item.payload_id for item in facts}) != len(facts):
            raise AuditRepositoryError("snapshot_invalid")
        required = {item.payload_id for item in self.snapshot.payload_occurrences}
        if {item.payload_id for item in facts} != required:
            raise AuditRepositoryError("snapshot_invalid")
        occurrences_by_id = {
            payload_id: tuple(
                occurrence
                for occurrence in self.snapshot.payload_occurrences
                if occurrence.payload_id == payload_id
            )
            for payload_id in required
        }
        for fact in facts:
            occurrences = occurrences_by_id[fact.payload_id]
            if (
                fact.occurrence_count != len(occurrences)
                or any(item.kind != fact.kind for item in occurrences)
            ):
                raise AuditRepositoryError("snapshot_invalid")
            if (
                fact.kind == "image"
                and fact.registered
                and (
                    fact.physical is None
                    or fact.physical.checksum_sha256
                    != occurrences[0].content_hash
                )
            ):
                raise AuditRepositoryError("snapshot_invalid")
        object.__setattr__(
            self,
            "payload_facts",
            tuple(sorted(facts, key=lambda item: item.payload_id)),
        )

    @classmethod
    def from_payload_rows(
        cls,
        snapshot: AuditSnapshot,
        payload_rows: Iterable[Mapping[str, Any]],
    ) -> AuditSnapshotBundle:
        """Project exactly one global registry row per occurrence-derived payload ID."""

        try:
            if not isinstance(snapshot, AuditSnapshot):
                raise ValueError
            run_id = snapshot.run.run_id
            records = (
                *snapshot.chunks,
                *snapshot.payload_occurrences,
                *snapshot.processing_diagnostics,
            )
            if any(item.run_id != run_id for item in records):
                raise ValueError

            rows = tuple(payload_rows)
            if any(not isinstance(row, Mapping) for row in rows):
                raise ValueError
            payload_ids = {item.payload_id for item in snapshot.payload_occurrences}
            row_ids = [row.get("payload_id") for row in rows]
            if len(row_ids) != len(set(row_ids)) or set(row_ids) != payload_ids:
                raise ValueError

            occurrence_counts = Counter(
                item.payload_id for item in snapshot.payload_occurrences
            )
            occurrences_by_id = {
                payload_id: tuple(
                    item
                    for item in snapshot.payload_occurrences
                    if item.payload_id == payload_id
                )
                for payload_id in payload_ids
            }
            facts: list[PayloadResolutionFact] = []
            for row in rows:
                payload_id = row["payload_id"]
                occurrences = occurrences_by_id[payload_id]
                expected = occurrences[0]
                if any(
                    item.kind != expected.kind
                    or item.content_hash != expected.content_hash
                    or item.storage_identity != expected.storage_identity
                    for item in occurrences
                ):
                    raise ValueError
                if (
                    row.get("kind") != expected.kind
                    or row.get("storage") != expected.kind
                    or row.get("storage_identity") != expected.storage_identity
                    or row.get("content_hash") != expected.content_hash
                ):
                    raise ValueError
                facts.append(
                    parse_payload_registration(
                        payload_id,
                        expected.kind,
                        row.get("metadata"),
                        occurrence_count=occurrence_counts[payload_id],
                    )
                )
            return cls(snapshot=snapshot, payload_facts=tuple(facts))
        except AuditRepositoryError:
            raise
        except (KeyError, TypeError, ValueError):
            raise AuditRepositoryError("snapshot_invalid") from None


class AuditSnapshotReader(Protocol):
    """Only supported read surface: one canonical exact run."""

    def load_exact_run(
        self, run_id: str, ruleset_version: str, bounds: AuditReadBounds
    ) -> AuditSnapshotBundle: ...


class PostgresAuditSnapshotRepository:
    """Read one exact terminal run in one bounded repeatable-read transaction."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def load_exact_run(
        self, run_id: str, ruleset_version: str, bounds: AuditReadBounds
    ) -> AuditSnapshotBundle:
        canonical = self._validate_request(run_id, ruleset_version, bounds)
        cursor = self.connection.cursor()
        try:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            run_rows = self._fetch_rows(
                cursor,
                "SELECT run_id::text, logical_file_key, status, source_content_hash, "
                "config_hash, operator_version, chunk_schema_version, claimed_at, finished_at, "
                "chunk_count, payload_count, warning_count, error_count "
                "FROM lore_core.processing_runs WHERE run_id=%s LIMIT %s",
                (canonical, bounds.max_runs + 1),
                bounds.max_runs,
            )
            if not run_rows:
                raise AuditRepositoryError("snapshot_unavailable")
            run = self._build_run(run_rows[0], canonical)

            chunk_rows = self._fetch_rows(
                cursor,
                "SELECT chunk_id, run_id::text, ordinal, pipeline_type, chunk_type, "
                "vector_text, fulltext, display_text, coordinates, metadata, payload_refs, "
                "content_signature, vector_text_hash, fulltext_hash "
                "FROM lore_core.chunks WHERE run_id=%s "
                "ORDER BY ordinal, chunk_id LIMIT %s",
                (canonical, bounds.max_chunks + 1),
                bounds.max_chunks,
            )
            occurrence_rows = self._fetch_rows(
                cursor,
                "SELECT run_id::text, payload_id, occurrence_ordinal, kind, storage_identity, "
                "content_hash, coordinates, metadata "
                "FROM lore_core.payload_occurrences WHERE run_id=%s "
                "ORDER BY payload_id, occurrence_ordinal LIMIT %s",
                (canonical, bounds.max_occurrences + 1),
                bounds.max_occurrences,
            )
            diagnostic_rows = self._fetch_rows(
                cursor,
                "SELECT diagnostic_id::text, run_id::text, chunk_id, payload_id, level, code, "
                "message, stage, details FROM lore_core.diagnostics "
                "WHERE run_id=%s AND origin='splitter' "
                "ORDER BY diagnostic_id, code LIMIT %s",
                (canonical, bounds.max_diagnostics + 1),
                bounds.max_diagnostics,
            )

            self._validate_raw_bounds(
                chunk_rows, occurrence_rows, diagnostic_rows, bounds
            )
            chunks = tuple(self._build_chunk(row) for row in chunk_rows)
            occurrences = tuple(
                self._build_occurrence(row) for row in occurrence_rows
            )
            diagnostics = tuple(
                self._build_diagnostic(row) for row in diagnostic_rows
            )
            self._validate_count_drift(run, chunks, occurrences, diagnostics)
            snapshot = AuditSnapshot(
                ruleset_version=ruleset_version,
                run=run,
                chunks=chunks,
                payload_occurrences=occurrences,
                processing_diagnostics=diagnostics,
            )

            payload_ids = sorted({item.payload_id for item in occurrences})
            if len(payload_ids) > bounds.max_payloads:
                raise AuditRepositoryError("snapshot_bounds")
            payload_rows: tuple[Any, ...] = ()
            if payload_ids:
                payload_rows = self._fetch_rows(
                    cursor,
                    "SELECT payload_id, run_id::text, logical_file_key, kind, storage, "
                    "storage_uri, content_hash, metadata FROM lore_core.payloads "
                    "WHERE payload_id = ANY(%s) ORDER BY payload_id LIMIT %s",
                    (payload_ids, bounds.max_payloads + 1),
                    bounds.max_payloads,
                )
            projected_payloads = tuple(
                self._build_payload_row(row, bounds) for row in payload_rows
            )
            bundle = AuditSnapshotBundle.from_payload_rows(
                snapshot, projected_payloads
            )
            self.connection.commit()
            return bundle
        except AuditRepositoryError:
            self.connection.rollback()
            raise
        except (KeyError, TypeError, ValueError, IndexError):
            self.connection.rollback()
            raise AuditRepositoryError("snapshot_invalid") from None
        except Exception:
            self.connection.rollback()
            raise AuditRepositoryError("read_failed") from None
        finally:
            cursor.close()

    @staticmethod
    def _validate_request(
        run_id: str, ruleset_version: str, bounds: AuditReadBounds
    ) -> str:
        try:
            canonical = str(UUID(run_id))
        except (AttributeError, TypeError, ValueError):
            raise AuditRepositoryError("invalid_request") from None
        if ruleset_version != "audit/v1" or not isinstance(bounds, AuditReadBounds):
            raise AuditRepositoryError("invalid_request")
        return canonical

    @staticmethod
    def _fetch_rows(cursor: Any, sql: str, params: tuple[Any, ...], limit: int) -> tuple[Any, ...]:
        cursor.execute(sql, params)
        rows = tuple(cursor.fetchall())
        if len(rows) > limit:
            raise AuditRepositoryError("snapshot_bounds")
        return rows

    @staticmethod
    def _build_run(row: Any, run_id: str) -> AuditRun:
        if len(row) != 13 or row[0] != run_id:
            raise ValueError
        try:
            status = RunStatus(row[2])
        except (TypeError, ValueError):
            raise ValueError from None
        if status not in {
            RunStatus.SUCCESS,
            RunStatus.SKIPPED,
            RunStatus.FAILED,
            RunStatus.STALE,
        } or row[8] is None:
            raise ValueError
        return AuditRun(
            run_id=row[0],
            logical_file_key=row[1],
            status=status,
            source_content_hash=row[3],
            config_hash=row[4],
            operator_version=row[5],
            chunk_schema_version=row[6],
            claimed_at=row[7],
            finished_at=row[8],
            chunk_count=row[9],
            payload_count=row[10],
            warning_count=row[11],
            error_count=row[12],
        )

    @classmethod
    def _build_chunk(cls, row: Any) -> AuditChunk:
        if len(row) != 14:
            raise ValueError
        return AuditChunk(
            chunk_id=row[0],
            run_id=row[1],
            ordinal=row[2],
            pipeline_type=row[3],
            chunk_type=row[4],
            vector_text=row[5],
            fulltext=row[6],
            display_text=row[7],
            coordinates=row[8],
            metadata=row[9],
            payload_refs=row[10],
            content_signature=row[11],
            vector_text_hash=row[12],
            fulltext_hash=row[13],
        )

    @staticmethod
    def _build_occurrence(row: Any) -> AuditPayloadOccurrence:
        if len(row) != 8:
            raise ValueError
        return AuditPayloadOccurrence(
            run_id=row[0],
            payload_id=row[1],
            occurrence_ordinal=row[2],
            kind=row[3],
            storage_identity=row[4],
            content_hash=row[5],
            coordinates=row[6],
            metadata=row[7],
        )

    @staticmethod
    def _build_diagnostic(row: Any) -> ProcessingDiagnostic:
        if len(row) != 9:
            raise ValueError
        return ProcessingDiagnostic(
            diagnostic_id=row[0],
            run_id=row[1],
            chunk_id=row[2],
            payload_id=row[3],
            level=row[4],
            code=row[5],
            message=row[6],
            stage=row[7],
            details=row[8],
        )

    @classmethod
    def _build_payload_row(
        cls, row: Any, bounds: AuditReadBounds
    ) -> dict[str, Any]:
        if len(row) != 8:
            raise ValueError
        cls._json_size(row[7], bounds.max_json_bytes)
        metadata = row[7]
        if isinstance(metadata, Mapping) and "audit_registration" in metadata:
            cls._json_size(
                metadata["audit_registration"], bounds.max_registration_bytes
            )
        return {
            "payload_id": row[0],
            "owner_run_id": row[1],
            "logical_file_key": row[2],
            "kind": row[3],
            "storage": row[4],
            "storage_identity": row[5],
            "content_hash": row[6],
            "metadata": metadata,
        }

    @classmethod
    def _validate_raw_bounds(
        cls,
        chunks: tuple[Any, ...],
        occurrences: tuple[Any, ...],
        diagnostics: tuple[Any, ...],
        bounds: AuditReadBounds,
    ) -> None:
        aggregate = 0
        for row in chunks:
            if len(row) != 14:
                raise ValueError
            for value in row[5:8]:
                size = cls._text_size(value, bounds.max_text_bytes)
                aggregate += size
                if aggregate > bounds.max_aggregate_text_bytes:
                    raise AuditRepositoryError("snapshot_bounds")
            for value in row[8:11]:
                cls._json_size(value, bounds.max_json_bytes)
        for row in occurrences:
            if len(row) != 8:
                raise ValueError
            cls._json_size(row[6], bounds.max_json_bytes)
            cls._json_size(row[7], bounds.max_json_bytes)
        for row in diagnostics:
            if len(row) != 9:
                raise ValueError
            aggregate += cls._text_size(row[6], bounds.max_text_bytes)
            if aggregate > bounds.max_aggregate_text_bytes:
                raise AuditRepositoryError("snapshot_bounds")
            cls._json_size(row[8], bounds.max_json_bytes)

    @staticmethod
    def _text_size(value: Any, limit: int) -> int:
        if not isinstance(value, str):
            raise ValueError
        size = len(value.encode("utf-8"))
        if size > limit:
            raise AuditRepositoryError("snapshot_bounds")
        return size

    @staticmethod
    def _json_size(value: Any, limit: int) -> int:
        try:
            encoded = json.dumps(
                value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError):
            raise ValueError from None
        if len(encoded) > limit:
            raise AuditRepositoryError("snapshot_bounds")
        return len(encoded)

    @staticmethod
    def _validate_count_drift(
        run: AuditRun,
        chunks: tuple[AuditChunk, ...],
        occurrences: tuple[AuditPayloadOccurrence, ...],
        diagnostics: tuple[ProcessingDiagnostic, ...],
    ) -> None:
        warning_count = sum(item.level == "warning" for item in diagnostics)
        error_count = sum(item.level in {"error", "critical"} for item in diagnostics)
        if (
            run.chunk_count != len(chunks)
            or run.payload_count != len(occurrences)
            or run.warning_count != warning_count
            or run.error_count != error_count
        ):
            raise ValueError


__all__ = [
    "AuditReadBounds",
    "AuditRepositoryError",
    "AuditSnapshotBundle",
    "AuditSnapshotReader",
    "PostgresAuditSnapshotRepository",
]
