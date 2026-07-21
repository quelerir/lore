"""Application service composing exact audit reads, pure evaluation, and writes."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Protocol
from uuid import UUID

from .contracts import (
    AUDIT_FAILED,
    AuditLifecycleResult,
    LifecycleDiagnostic,
    LifecycleOutcome,
)
from .engine import run_audit
from .engine_contracts import AUDIT_V1, AuditEngineInput, AuditEngineResult, PayloadResolutionFact
from .persistence import AuditResultWriter
from .snapshot_repository import AuditReadBounds, AuditSnapshotReader

_ERROR_MESSAGES = {
    "invalid_request": "audit request is invalid",
    "read_failed": "audit snapshot read failed",
    "resolution_failed": "audit dependency resolution failed",
    "engine_failed": "audit evaluation failed",
    "completed_write_failed": "audit result persistence failed",
    "failure_recording_failed": "audit execution and failure recording failed",
}


class AuditExecutionError(RuntimeError):
    """Public fixed-category service error that never includes raw exception text."""

    def __init__(self, category: str) -> None:
        if category not in _ERROR_MESSAGES:
            category = "engine_failed"
        self.category = category
        super().__init__(_ERROR_MESSAGES[category])


class PayloadCapabilityResolver(Protocol):
    """Optional already-constructed capability check over registered payload facts."""

    def resolve(
        self, facts: tuple[PayloadResolutionFact, ...]
    ) -> tuple[PayloadResolutionFact, ...]: ...


@dataclass(frozen=True)
class AuditServiceResult:
    run_id: str
    ruleset_version: str
    status: str
    checked_rule_count: int
    outcome_counts: Mapping[str, int]
    severity_counts: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome_counts", MappingProxyType(dict(self.outcome_counts)))
        object.__setattr__(self, "severity_counts", MappingProxyType(dict(self.severity_counts)))

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "ruleset_version": self.ruleset_version,
            "status": self.status,
            "checked_rule_count": self.checked_rule_count,
            "outcome_counts": dict(self.outcome_counts),
            "severity_counts": dict(self.severity_counts),
        }


class _EngineLifecycleFailure(RuntimeError):
    pass


class AuditService:
    """Execute one exact audit/v1 run through injected bounded dependencies."""

    def __init__(
        self,
        reader: AuditSnapshotReader,
        writer: AuditResultWriter,
        bounds: AuditReadBounds,
        *,
        payload_resolver: PayloadCapabilityResolver | None = None,
        engine: Callable[[AuditEngineInput], AuditEngineResult] = run_audit,
    ) -> None:
        if not isinstance(bounds, AuditReadBounds):
            raise TypeError("bounds must be AuditReadBounds")
        self.reader = reader
        self.writer = writer
        self.bounds = bounds
        self.payload_resolver = payload_resolver
        self.engine = engine

    def audit_run(self, run_id: str, ruleset_version: str = AUDIT_V1) -> AuditServiceResult:
        canonical = self._validate_request(run_id, ruleset_version)

        try:
            bundle = self.reader.load_exact_run(canonical, AUDIT_V1, self.bounds)
        except Exception as exc:
            self._raise_recorded_failure(canonical, "read_failed", "read", exc)

        try:
            payload_facts = bundle.payload_facts
            if self.payload_resolver is not None:
                resolved_facts = tuple(self.payload_resolver.resolve(payload_facts))
                self._validate_resolved_facts(payload_facts, resolved_facts)
                payload_facts = resolved_facts
            engine_input = AuditEngineInput(
                snapshot=bundle.snapshot,
                ruleset_version=AUDIT_V1,
                token_facts=(),
                payload_facts=payload_facts,
            )
        except Exception as exc:
            self._raise_recorded_failure(
                canonical, "resolution_failed", "resolution", exc
            )

        try:
            result = self.engine(engine_input)
            if not isinstance(result, AuditEngineResult):
                raise TypeError("engine result has an invalid type")
            if result.lifecycle.outcome is not LifecycleOutcome.COMPLETED:
                raise _EngineLifecycleFailure("audit engine failed closed")
            if (
                result.lifecycle.run_id != canonical
                or result.lifecycle.ruleset_version != AUDIT_V1
            ):
                raise _EngineLifecycleFailure("audit engine result identity mismatch")
        except Exception as exc:
            self._raise_recorded_failure(canonical, "engine_failed", "engine", exc)

        try:
            self.writer.write_completed(result)
        except Exception as exc:
            self._raise_recorded_failure(
                canonical, "completed_write_failed", "completed_write", exc
            )

        lifecycle = result.lifecycle
        projection = lifecycle.to_dict()
        return AuditServiceResult(
            run_id=canonical,
            ruleset_version=AUDIT_V1,
            status="completed",
            checked_rule_count=lifecycle.checked_rule_count,
            outcome_counts=projection["outcome_counts"],
            severity_counts=projection["severity_counts"],
        )

    def _raise_recorded_failure(
        self,
        run_id: str,
        category: str,
        stage: str,
        primary: Exception,
    ) -> None:
        lifecycle = AuditLifecycleResult(
            outcome=LifecycleOutcome.FAILED,
            ruleset_version=AUDIT_V1,
            run_id=run_id,
            code=AUDIT_FAILED,
            checked_rule_count=None,
            outcome_counts=None,
            severity_counts=None,
            diagnostic=LifecycleDiagnostic(
                code=AUDIT_FAILED,
                message="Audit execution failed",
                details={
                    "category": category,
                    "ruleset_version": AUDIT_V1,
                    "stage": stage,
                },
            ),
        )
        try:
            self.writer.write_failed(lifecycle)
        except Exception:
            raise AuditExecutionError("failure_recording_failed") from primary
        raise AuditExecutionError(category) from primary

    @staticmethod
    def _validate_resolved_facts(
        registered: tuple[PayloadResolutionFact, ...],
        resolved: tuple[PayloadResolutionFact, ...],
    ) -> None:
        if len(registered) != len(resolved):
            raise ValueError("payload resolver changed exact-run membership")
        for expected, actual in zip(registered, resolved, strict=True):
            if not isinstance(actual, PayloadResolutionFact):
                raise TypeError("payload resolver returned an invalid fact")
            expected_projection = expected.to_dict()
            actual_projection = actual.to_dict()
            expected_physical = expected_projection.pop("physical")
            actual_physical = actual_projection.pop("physical")
            if expected_projection != actual_projection:
                raise ValueError("payload resolver changed immutable registration evidence")
            if (expected_physical is None) != (actual_physical is None):
                raise ValueError("payload resolver changed physical evidence shape")
            if expected_physical is not None:
                expected_physical.pop("resolved")
                actual_physical.pop("resolved")
                if expected_physical != actual_physical:
                    raise ValueError("payload resolver changed immutable physical evidence")

    @staticmethod
    def _validate_request(run_id: str, ruleset_version: str) -> str:
        try:
            canonical = str(UUID(run_id))
        except (AttributeError, TypeError, ValueError):
            raise AuditExecutionError("invalid_request") from None
        if canonical != run_id or ruleset_version != AUDIT_V1:
            raise AuditExecutionError("invalid_request")
        return canonical


__all__ = [
    "AuditExecutionError",
    "AuditService",
    "AuditServiceResult",
    "PayloadCapabilityResolver",
]
