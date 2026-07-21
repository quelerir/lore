"""Transactional audit-only persistence for deterministic audit results."""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from psycopg.types.json import Jsonb

from .contracts import (
    AUDIT_COMPLETED,
    AUDIT_FAILED,
    AuditLifecycleResult,
    DiagnosticOrigin,
    LifecycleOutcome,
    RuleOutcome,
)
from .engine_contracts import AUDIT_V1, EMPTY_DOMAIN_TARGET_ID, AuditEngineResult

_COMPLETED_KEY = "audit/v1:lifecycle:AUDIT_COMPLETED"
_FAILED_KEY = "audit/v1:lifecycle:AUDIT_FAILED"
_FINDING_PREFIX = "audit/v1:%"
_LIFECYCLE_PREFIX = "audit/v1:lifecycle:%"


class AuditResultWriter(Protocol):
    """Audit-only mutation boundary used by the application service."""

    def write_completed(self, result: AuditEngineResult) -> None: ...

    def write_failed(self, lifecycle: AuditLifecycleResult) -> None: ...


class PostgresAuditResultWriter:
    """Persist audit findings and lifecycle rows without processing authority."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def write_completed(self, result: AuditEngineResult) -> None:
        run_id = self._validate_completed(result)
        findings = tuple(
            item for item in result.results if item.outcome is RuleOutcome.FINDING
        )
        current_keys = [item.diagnostic_key for item in findings]
        cursor = self.connection.cursor()
        try:
            self._lock_exact_run(cursor, run_id)
            for item in findings:
                target = item.target
                is_concrete_target = target.target_id != EMPTY_DOMAIN_TARGET_ID
                chunk_id = (
                    target.target_id
                    if is_concrete_target and target.kind == "chunk"
                    else None
                )
                payload_id = (
                    target.target_id
                    if is_concrete_target and target.kind in {"table", "image"}
                    else None
                )
                cursor.execute(
                    "INSERT INTO lore_core.diagnostics "
                    "(logical_file_key,run_id,chunk_id,payload_id,level,code,message,stage,"
                    "details,origin,diagnostic_key) "
                    "SELECT logical_file_key,%s,%s,%s,%s,%s,%s,'audit',%s,'audit_rule',%s "
                    "FROM lore_core.processing_runs WHERE run_id=%s "
                    "ON CONFLICT (run_id, diagnostic_key) WHERE origin='audit_rule' "
                    "DO UPDATE SET chunk_id=EXCLUDED.chunk_id,payload_id=EXCLUDED.payload_id,"
                    "level=EXCLUDED.level,code=EXCLUDED.code,message=EXCLUDED.message,"
                    "stage=EXCLUDED.stage,details=EXCLUDED.details RETURNING diagnostic_id",
                    (
                        run_id,
                        chunk_id,
                        payload_id,
                        item.severity.value,
                        item.rule_id,
                        item.message,
                        Jsonb(item.to_dict()),
                        item.diagnostic_key,
                        run_id,
                    ),
                )
                self._require_affected_row(cursor)
            cursor.execute(
                "DELETE FROM lore_core.diagnostics WHERE run_id=%s AND origin='audit_rule' "
                "AND diagnostic_key LIKE %s AND diagnostic_key NOT LIKE %s "
                "AND NOT (diagnostic_key = ANY(%s))",
                (run_id, _FINDING_PREFIX, _LIFECYCLE_PREFIX, current_keys),
            )
            self._upsert_lifecycle(
                cursor,
                run_id=run_id,
                key=_COMPLETED_KEY,
                code=AUDIT_COMPLETED,
                message="Audit completed",
                details=result.lifecycle.to_dict(),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def write_failed(self, lifecycle: AuditLifecycleResult) -> None:
        run_id = self._validate_failed(lifecycle)
        cursor = self.connection.cursor()
        try:
            self._lock_exact_run(cursor, run_id)
            self._upsert_lifecycle(
                cursor,
                run_id=run_id,
                key=_FAILED_KEY,
                code=AUDIT_FAILED,
                message="Audit execution failed",
                details=lifecycle.to_dict(),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    @staticmethod
    def _upsert_lifecycle(
        cursor: Any,
        *,
        run_id: str,
        key: str,
        code: str,
        message: str,
        details: dict[str, Any],
    ) -> None:
        cursor.execute(
            "INSERT INTO lore_core.diagnostics "
            "(logical_file_key,run_id,level,code,message,stage,details,origin,diagnostic_key) "
            "SELECT logical_file_key,%s,'info',%s,%s,'audit',%s,'audit_rule',%s "
            "FROM lore_core.processing_runs WHERE run_id=%s "
            "ON CONFLICT (run_id, diagnostic_key) WHERE origin='audit_rule' "
            "DO UPDATE SET level=EXCLUDED.level,code=EXCLUDED.code,message=EXCLUDED.message,"
            "stage=EXCLUDED.stage,details=EXCLUDED.details RETURNING diagnostic_id",
            (run_id, code, message, Jsonb(details), key, run_id),
        )
        PostgresAuditResultWriter._require_affected_row(cursor)

    @staticmethod
    def _lock_exact_run(cursor: Any, run_id: str) -> None:
        cursor.execute(
            "SELECT run_id FROM lore_core.processing_runs WHERE run_id=%s FOR KEY SHARE",
            (run_id,),
        )
        row = cursor.fetchone()
        if row is None or len(row) != 1 or str(row[0]) != run_id:
            raise RuntimeError("audit processing run does not exist")

    @staticmethod
    def _require_affected_row(cursor: Any) -> None:
        row = cursor.fetchone()
        if row is None or len(row) != 1:
            raise RuntimeError("audit diagnostic write affected no rows")

    @classmethod
    def _validate_completed(cls, result: AuditEngineResult) -> str:
        if not isinstance(result, AuditEngineResult):
            raise TypeError("result must be an AuditEngineResult")
        lifecycle = result.lifecycle
        if (
            lifecycle.outcome is not LifecycleOutcome.COMPLETED
            or lifecycle.code != AUDIT_COMPLETED
            or lifecycle.ruleset_version != AUDIT_V1
        ):
            raise ValueError("writer accepts only completed audit/v1 results")
        if any(
            item.ruleset_version != AUDIT_V1
            or (
                item.outcome is RuleOutcome.FINDING
                and item.origin is not DiagnosticOrigin.AUDIT_RULE
            )
            for item in result.results
        ):
            raise ValueError("result contains an incompatible audit result")
        return cls._canonical_run_id(lifecycle.run_id)

    @classmethod
    def _validate_failed(cls, lifecycle: AuditLifecycleResult) -> str:
        if not isinstance(lifecycle, AuditLifecycleResult):
            raise TypeError("lifecycle must be an AuditLifecycleResult")
        if (
            lifecycle.outcome is not LifecycleOutcome.FAILED
            or lifecycle.code != AUDIT_FAILED
            or lifecycle.ruleset_version != AUDIT_V1
        ):
            raise ValueError("writer accepts only failed audit/v1 lifecycle results")
        return cls._canonical_run_id(lifecycle.run_id)

    @staticmethod
    def _canonical_run_id(run_id: str | None) -> str:
        try:
            canonical = str(UUID(run_id))
        except (AttributeError, TypeError, ValueError):
            raise ValueError("audit lifecycle run_id must be canonical") from None
        if canonical != run_id:
            raise ValueError("audit lifecycle run_id must be canonical")
        return canonical


__all__ = ["AuditResultWriter", "PostgresAuditResultWriter"]
