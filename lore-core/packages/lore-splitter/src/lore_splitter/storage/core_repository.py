from __future__ import annotations

# SQL statements remain readable as single parameterized strings.
# ruff: noqa: E501
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from lore_audit.registration import parse_payload_registration
from lore_splitter.contracts import SourceFile
from lore_splitter.per_file import (
    DEFAULT_LEASE_SECONDS,
    Diagnostic,
    ProcessingAlreadyActive,
    ProcessingIdentity,
    RunResult,
    RunStatus,
    sanitize_metadata,
)


class CoreRepository:
    """Postgres control-plane adapter; all values are parameterized."""

    def __init__(
        self,
        connection: Any,
        *,
        core_schema: str = "lore_core",
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        if core_schema != "lore_core":
            raise ValueError("core schema must be the configured lore_core schema")
        self.connection = connection
        self.lease_seconds = lease_seconds

    def claim(
        self,
        source: SourceFile,
        identity: ProcessingIdentity,
        *,
        overwrite: bool = False,
        orchestration_claim_key: str | None = None,
        now: datetime | None = None,
    ) -> str | RunResult:
        now = now or datetime.now(UTC)
        safe_metadata, drift = sanitize_metadata(source)
        cursor = self.connection.cursor()
        try:
            if orchestration_claim_key is not None:
                cursor.execute(
                    "SELECT run_id, status, supersedes_run_id, chunk_count, payload_count, warning_count, error_count FROM lore_core.processing_runs WHERE orchestration_claim_key=%s FOR UPDATE",
                    (orchestration_claim_key,),
                )
                owned = cursor.fetchone()
                if owned:
                    status = RunStatus(owned[1])
                    self.connection.commit()
                    if status is RunStatus.ACTIVE:
                        return str(owned[0])
                    if status not in {RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.FAILED}:
                        raise ValueError("owned processing run has unsupported status")
                    return RunResult(
                        str(owned[0]),
                        status,
                        reused=True,
                        supersedes_run_id=str(owned[2]) if owned[2] else None,
                        chunk_count=int(owned[3]),
                        payload_count=int(owned[4]),
                        warning_count=int(owned[5]),
                        error_count=int(owned[6]),
                    )
            cursor.execute(
                "SELECT current_success_run_id FROM lore_core.processed_files WHERE logical_file_key=%s FOR UPDATE",
                (identity.logical_key,),
            )
            snapshot = cursor.fetchone()
            current_success_run_id = snapshot[0] if snapshot else None
            cursor.execute(
                "SELECT run_id, status, claimed_at, lease_until FROM lore_core.processing_runs WHERE logical_file_key=%s AND source_content_hash=%s AND config_hash=%s AND operator_version=%s AND chunk_schema_version=%s AND status IN ('active','success') ORDER BY claimed_at DESC LIMIT 1 FOR UPDATE",
                (
                    identity.logical_key,
                    identity.source_content_hash,
                    identity.config_hash,
                    identity.operator_version,
                    identity.chunk_schema_version,
                ),
            )
            row = cursor.fetchone()
            if row and row[1] == "active" and row[3] > now:
                raise ProcessingAlreadyActive(identity.logical_key, str(row[0]))
            if row and row[1] == "success" and not overwrite:
                cursor.execute(
                    "UPDATE lore_core.processed_files SET source_path=%s, object_path=%s, sanitized_metadata=%s, schema_drift_fields=%s, last_seen_at=%s, updated_at=%s WHERE logical_file_key=%s",
                    (
                        source.source_path,
                        source.object_path,
                        Jsonb(safe_metadata),
                        Jsonb(list(drift)),
                        now,
                        now,
                        identity.logical_key,
                    ),
                )
                self.connection.commit()
                return RunResult(str(row[0]), RunStatus.SUCCESS, reused=True)
            run_id = str(uuid.uuid4())
            supersedes = current_success_run_id
            lease_until = now + timedelta(seconds=self.lease_seconds)
            cursor.execute(
                "INSERT INTO lore_core.processed_files (logical_file_key, source_id, stream, file_id, source_path, object_path, mime_type, source_content_hash, config_hash, operator_version, chunk_schema_version, status, latest_run_id, current_success_run_id, sanitized_metadata, schema_drift_fields, last_seen_at, updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s,%s,%s) ON CONFLICT (logical_file_key) DO UPDATE SET status='active', latest_run_id=EXCLUDED.latest_run_id, source_path=EXCLUDED.source_path, object_path=EXCLUDED.object_path, mime_type=EXCLUDED.mime_type, source_content_hash=EXCLUDED.source_content_hash, config_hash=EXCLUDED.config_hash, operator_version=EXCLUDED.operator_version, chunk_schema_version=EXCLUDED.chunk_schema_version, sanitized_metadata=EXCLUDED.sanitized_metadata, schema_drift_fields=EXCLUDED.schema_drift_fields, updated_at=EXCLUDED.updated_at",
                (
                    identity.logical_key,
                    source.source_id,
                    source.stream,
                    source.file_id,
                    source.source_path,
                    source.object_path,
                    source.mime_type,
                    identity.source_content_hash,
                    identity.config_hash,
                    identity.operator_version,
                    identity.chunk_schema_version,
                    run_id,
                    current_success_run_id,
                    Jsonb(safe_metadata),
                    Jsonb(list(drift)),
                    now,
                    now,
                ),
            )
            cursor.execute(
                "INSERT INTO lore_core.processing_runs (run_id, logical_file_key, source_content_hash, config_hash, operator_version, chunk_schema_version, status, supersedes_run_id, claimed_at, heartbeat_at, lease_until, orchestration_claim_key) VALUES (%s,%s,%s,%s,%s,%s,'active',%s,%s,%s,%s,%s)",
                (
                    run_id,
                    identity.logical_key,
                    identity.source_content_hash,
                    identity.config_hash,
                    identity.operator_version,
                    identity.chunk_schema_version,
                    supersedes,
                    now,
                    now,
                    lease_until,
                    orchestration_claim_key,
                ),
            )
            self.connection.commit()
            return run_id
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def heartbeat(self, run_id: str, *, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "UPDATE lore_core.processing_runs SET heartbeat_at=%s, lease_until=%s WHERE run_id=%s AND status='active'",
                (now, now + timedelta(seconds=self.lease_seconds), run_id),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def record_skipped(
        self,
        source: SourceFile,
        identity: ProcessingIdentity,
        diagnostic: Diagnostic,
        *,
        now: datetime | None = None,
    ) -> RunResult:
        """Persist an unsupported/input-skipped outcome with its diagnostic."""
        claimed = self.claim(source, identity, now=now)
        if isinstance(claimed, RunResult):
            return claimed
        self.add_diagnostic(identity.logical_key, diagnostic, run_id=claimed)
        return self.finalize(claimed, status=RunStatus.SKIPPED, warning_count=1)

    def add_diagnostic(
        self, logical_key: str, diagnostic: Diagnostic, *, run_id: str | None = None
    ) -> None:
        cursor = self.connection.cursor()
        try:
            safe = diagnostic.to_dict()
            cursor.execute(
                "INSERT INTO lore_core.diagnostics (logical_file_key, run_id, level, code, message, stage, details) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (
                    logical_key,
                    run_id,
                    safe["level"],
                    safe["code"],
                    safe["message"],
                    safe["stage"],
                    Jsonb(safe["details"]),
                ),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def finalize(
        self,
        run_id: str,
        *,
        status: RunStatus,
        chunk_count: int = 0,
        payload_count: int = 0,
        warning_count: int = 0,
        error_count: int = 0,
        error: dict[str, Any] | None = None,
    ) -> RunResult:
        if status not in {RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.FAILED, RunStatus.STALE}:
            raise ValueError("final status must be terminal")
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                "UPDATE lore_core.processing_runs SET status=%s, finished_at=now(), chunk_count=%s, payload_count=%s, warning_count=%s, error_count=%s, error=%s WHERE run_id=%s RETURNING logical_file_key, supersedes_run_id",
                (
                    status.value,
                    chunk_count,
                    payload_count,
                    warning_count,
                    error_count,
                    Jsonb(error or {}),
                    run_id,
                ),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"unknown run: {run_id}")
            current_success = run_id if status is RunStatus.SUCCESS else None
            cursor.execute(
                "UPDATE lore_core.processed_files SET status=%s, latest_run_id=%s, current_success_run_id=COALESCE(%s,current_success_run_id), updated_at=now() WHERE logical_file_key=%s",
                (status.value, run_id, current_success, row[0]),
            )
            self.connection.commit()
            return RunResult(
                run_id,
                status,
                supersedes_run_id=str(row[1]) if row[1] else None,
                chunk_count=chunk_count,
                payload_count=payload_count,
                warning_count=warning_count,
                error_count=error_count,
            )
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def finalize_persisted(
        self,
        run_id: str,
        *,
        logical_file_key: str,
        chunks: list[dict[str, Any]],
        payloads: list[dict[str, Any]],
        diagnostics: list[Diagnostic],
        counts: dict[str, int],
        status: RunStatus = RunStatus.SUCCESS,
    ) -> RunResult:
        """Insert final durable rows in one parameterized transaction after payload verification."""
        if status is RunStatus.SUCCESS and any(not item.get("verified", False) for item in payloads):
            raise ValueError("required payload is not verified")
        if status is RunStatus.SUCCESS:
            for payload in payloads:
                parse_payload_registration(
                    payload["payload_id"],
                    payload["kind"],
                    payload.get("metadata", {}),
                    1,
                )
        cursor = self.connection.cursor()
        try:
            for chunk in chunks:
                cursor.execute("INSERT INTO lore_core.chunks (chunk_id, logical_file_key, run_id, ordinal, pipeline_type, chunk_type, vector_text, fulltext, display_text, coordinates, metadata, payload_refs, content_signature, vector_text_hash, fulltext_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", (chunk["chunk_id"], logical_file_key, run_id, chunk["ordinal"], chunk["pipeline_type"], chunk["chunk_type"], chunk["vector_text"], chunk["fulltext"], chunk["display_text"], Jsonb(chunk.get("coordinates", {})), Jsonb(chunk.get("metadata", {})), Jsonb(chunk.get("payload_refs", [])), chunk["content_signature"], chunk["vector_hash"], chunk["fulltext_hash"]))
            for payload in payloads:
                cursor.execute("INSERT INTO lore_core.payloads (payload_id, logical_file_key, run_id, kind, storage, storage_uri, coordinates, metadata, content_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (payload_id) DO UPDATE SET metadata=CASE WHEN payloads.metadata ? 'audit_registration' THEN payloads.metadata ELSE jsonb_set(payloads.metadata, '{audit_registration}', EXCLUDED.metadata->'audit_registration', true) END WHERE payloads.kind=EXCLUDED.kind AND payloads.storage=EXCLUDED.storage AND payloads.storage_uri IS NOT DISTINCT FROM EXCLUDED.storage_uri AND payloads.content_hash=EXCLUDED.content_hash AND (NOT (payloads.metadata ? 'audit_registration') OR jsonb_set(jsonb_set(payloads.metadata->'audit_registration', '{registration_identity}', (payloads.metadata->'audit_registration'->'registration_identity') - ARRAY['source_kind','source_checksum','source_location'], false), '{metadata}', (payloads.metadata->'audit_registration'->'metadata') - ARRAY['source_kind','source_checksum','source_location','sheet','range'], false)=jsonb_set(jsonb_set(EXCLUDED.metadata->'audit_registration', '{registration_identity}', (EXCLUDED.metadata->'audit_registration'->'registration_identity') - ARRAY['source_kind','source_checksum','source_location'], false), '{metadata}', (EXCLUDED.metadata->'audit_registration'->'metadata') - ARRAY['source_kind','source_checksum','source_location','sheet','range'], false)) RETURNING payload_id", (payload["payload_id"], logical_file_key, run_id, payload["kind"], payload["kind"], payload["storage_identity"], Jsonb(payload.get("coordinates", {})), Jsonb(payload.get("metadata", {})), payload["content_hash"]))
                if not cursor.fetchone():
                    raise ValueError("payload registration conflict")
                cursor.execute("INSERT INTO lore_core.payload_occurrences (run_id, payload_id, occurrence_ordinal, kind, storage_identity, content_hash, coordinates, metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (run_id, payload["payload_id"], payload["occurrence_ordinal"], payload["kind"], payload["storage_identity"], payload["content_hash"], Jsonb(payload.get("coordinates", {})), Jsonb(payload.get("occurrence_metadata", {}))))
            for diagnostic in diagnostics:
                safe = diagnostic.to_dict()
                cursor.execute("INSERT INTO lore_core.diagnostics (logical_file_key, run_id, level, code, message, stage, details) SELECT logical_file_key,%s,%s,%s,%s,%s,%s FROM lore_core.processing_runs WHERE run_id=%s", (run_id, safe["level"], safe["code"], safe["message"], safe["stage"], Jsonb(safe["details"]), run_id))
            if status not in {RunStatus.SUCCESS, RunStatus.SKIPPED, RunStatus.FAILED, RunStatus.STALE}:
                raise ValueError("final status must be terminal")
            cursor.execute(
                "UPDATE lore_core.processing_runs SET status=%s, finished_at=now(), chunk_count=%s, payload_count=%s, warning_count=%s, error_count=%s WHERE run_id=%s RETURNING logical_file_key, supersedes_run_id",
                (
                    status.value,
                    counts.get("chunk_count", len(chunks)),
                    counts.get("payload_count", len(payloads)),
                    counts.get("warning_count", 0),
                    counts.get("error_count", 0),
                    run_id,
                ),
            )
            terminal = cursor.fetchone()
            if not terminal:
                raise ValueError(f"unknown run: {run_id}")
            current_success = run_id if status is RunStatus.SUCCESS else None
            cursor.execute(
                "UPDATE lore_core.processed_files SET status=%s, latest_run_id=%s, current_success_run_id=COALESCE(%s,current_success_run_id), updated_at=now() WHERE logical_file_key=%s",
                (status.value, run_id, current_success, terminal[0]),
            )
            self.connection.commit()
            return RunResult(
                run_id,
                status,
                supersedes_run_id=str(terminal[1]) if terminal[1] else None,
                chunk_count=counts.get("chunk_count", len(chunks)),
                payload_count=counts.get("payload_count", len(payloads)),
                warning_count=counts.get("warning_count", 0),
                error_count=counts.get("error_count", 0),
            )
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()
