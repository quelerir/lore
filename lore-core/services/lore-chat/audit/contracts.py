"""Closed immutable vocabulary for pure audit domain values."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from audit._vendor.run_status import RunStatus

from .validation import (
    build_diagnostic_key,
    canonicalize_safe_json,
    safe_json_to_dict,
    validate_reason_code,
    validate_rule_id,
    validate_ruleset_version,
    validate_target_id,
    validate_target_kind,
    utc_iso8601,
)

AUDIT_SNAPSHOT_SCHEMA_VERSION = "audit/snapshot/v1"
RULE_RESULT_SCHEMA_VERSION = "audit/rule-result/v1"
AUDIT_LIFECYCLE_SCHEMA_VERSION = "audit/lifecycle/v1"
AUDIT_COMPLETED = "AUDIT_COMPLETED"
AUDIT_FAILED = "AUDIT_FAILED"


def _require_non_empty_string(value: str, *, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value:
        raise ValueError(f"{name} must not be empty")


def _require_non_negative(value: int, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")


class DiagnosticOrigin(StrEnum):
    SPLITTER = "splitter"
    AUDIT_RULE = "audit_rule"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class RuleOutcome(StrEnum):
    PASS = "pass"
    FINDING = "finding"
    SUPPRESSED = "suppressed"
    NOT_APPLICABLE = "not_applicable"


class LifecycleOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    NO_RUN = "no_run"


@dataclass(frozen=True)
class AuditRun:
    run_id: str
    logical_file_key: str
    status: RunStatus
    source_content_hash: str
    config_hash: str
    operator_version: str
    chunk_schema_version: str
    claimed_at: datetime
    finished_at: datetime
    chunk_count: int
    payload_count: int
    warning_count: int
    error_count: int

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "logical_file_key",
            "source_content_hash",
            "config_hash",
            "operator_version",
            "chunk_schema_version",
        ):
            _require_non_empty_string(getattr(self, name), name=name)
        if not isinstance(self.status, RunStatus):
            raise TypeError("status must be a RunStatus")
        if self.status not in {
            RunStatus.SUCCESS,
            RunStatus.SKIPPED,
            RunStatus.FAILED,
            RunStatus.STALE,
        }:
            raise ValueError("audit run status must be terminal")
        utc_iso8601(self.claimed_at)
        utc_iso8601(self.finished_at)
        if self.finished_at < self.claimed_at:
            raise ValueError("finished_at must not precede claimed_at")
        for name in ("chunk_count", "payload_count", "warning_count", "error_count"):
            _require_non_negative(getattr(self, name), name=name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "logical_file_key": self.logical_file_key,
            "status": self.status.value,
            "source_content_hash": self.source_content_hash,
            "config_hash": self.config_hash,
            "operator_version": self.operator_version,
            "chunk_schema_version": self.chunk_schema_version,
            "claimed_at": utc_iso8601(self.claimed_at),
            "finished_at": utc_iso8601(self.finished_at),
            "chunk_count": self.chunk_count,
            "payload_count": self.payload_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
        }


@dataclass(frozen=True)
class AuditChunk:
    chunk_id: str
    run_id: str
    ordinal: int
    pipeline_type: str
    chunk_type: str
    vector_text: str
    fulltext: str
    display_text: str
    coordinates: Any = field(default_factory=dict)
    metadata: Any = field(default_factory=dict)
    payload_refs: Any = field(default_factory=tuple)
    content_signature: str = ""
    vector_text_hash: str = ""
    fulltext_hash: str = ""

    def __post_init__(self) -> None:
        for name in (
            "chunk_id",
            "run_id",
            "pipeline_type",
            "chunk_type",
            "content_signature",
            "vector_text_hash",
            "fulltext_hash",
        ):
            _require_non_empty_string(getattr(self, name), name=name)
        for name in ("vector_text", "fulltext", "display_text"):
            if not isinstance(getattr(self, name), str):
                raise TypeError(f"{name} must be a string")
        _require_non_negative(self.ordinal, name="ordinal")
        object.__setattr__(self, "coordinates", canonicalize_safe_json(self.coordinates))
        object.__setattr__(self, "metadata", canonicalize_safe_json(self.metadata))
        object.__setattr__(self, "payload_refs", canonicalize_safe_json(self.payload_refs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "run_id": self.run_id,
            "ordinal": self.ordinal,
            "pipeline_type": self.pipeline_type,
            "chunk_type": self.chunk_type,
            "vector_text": self.vector_text,
            "fulltext": self.fulltext,
            "display_text": self.display_text,
            "coordinates": safe_json_to_dict(self.coordinates),
            "metadata": safe_json_to_dict(self.metadata),
            "payload_refs": safe_json_to_dict(self.payload_refs),
            "content_signature": self.content_signature,
            "vector_text_hash": self.vector_text_hash,
            "fulltext_hash": self.fulltext_hash,
        }


@dataclass(frozen=True)
class AuditPayloadOccurrence:
    run_id: str
    payload_id: str
    occurrence_ordinal: int
    kind: str
    storage_identity: str
    content_hash: str
    coordinates: Any = field(default_factory=dict)
    metadata: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("run_id", "payload_id", "kind", "storage_identity", "content_hash"):
            _require_non_empty_string(getattr(self, name), name=name)
        _require_non_negative(self.occurrence_ordinal, name="occurrence_ordinal")
        object.__setattr__(self, "coordinates", canonicalize_safe_json(self.coordinates))
        object.__setattr__(self, "metadata", canonicalize_safe_json(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "payload_id": self.payload_id,
            "occurrence_ordinal": self.occurrence_ordinal,
            "kind": self.kind,
            "storage_identity": self.storage_identity,
            "content_hash": self.content_hash,
            "coordinates": safe_json_to_dict(self.coordinates),
            "metadata": safe_json_to_dict(self.metadata),
        }


@dataclass(frozen=True)
class ProcessingDiagnostic:
    diagnostic_id: str
    run_id: str
    chunk_id: str | None
    payload_id: str | None
    level: str
    code: str
    message: str
    stage: str
    details: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("diagnostic_id", "run_id", "level", "code", "stage"):
            _require_non_empty_string(getattr(self, name), name=name)
        for name in ("chunk_id", "payload_id"):
            value = getattr(self, name)
            if value is not None:
                _require_non_empty_string(value, name=name)
        message = canonicalize_safe_json(self.message)
        if not isinstance(message, str) or not message:
            raise ValueError("message must be a non-empty safe string")
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "details", canonicalize_safe_json(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnostic_id": self.diagnostic_id,
            "run_id": self.run_id,
            "chunk_id": self.chunk_id,
            "payload_id": self.payload_id,
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "stage": self.stage,
            "details": safe_json_to_dict(self.details),
        }


@dataclass(frozen=True)
class AuditSnapshot:
    ruleset_version: str
    run: AuditRun
    chunks: tuple[AuditChunk, ...]
    payload_occurrences: tuple[AuditPayloadOccurrence, ...]
    processing_diagnostics: tuple[ProcessingDiagnostic, ...]

    def __post_init__(self) -> None:
        validate_ruleset_version(self.ruleset_version)
        if not isinstance(self.run, AuditRun):
            raise TypeError("run must be an AuditRun")
        chunks = self._typed_tuple(self.chunks, AuditChunk, "chunks")
        occurrences = self._typed_tuple(
            self.payload_occurrences, AuditPayloadOccurrence, "payload occurrences"
        )
        diagnostics = self._typed_tuple(
            self.processing_diagnostics, ProcessingDiagnostic, "processing diagnostics"
        )
        self._reject_duplicates((item.chunk_id for item in chunks), "chunk id")
        self._reject_duplicates((item.ordinal for item in chunks), "chunk ordinal")
        self._reject_duplicates(
            ((item.payload_id, item.occurrence_ordinal) for item in occurrences),
            "payload occurrence identity",
        )
        self._reject_duplicates(
            (item.diagnostic_id for item in diagnostics), "processing diagnostic id"
        )
        records = (*chunks, *occurrences, *diagnostics)
        if any(record.run_id != self.run.run_id for record in records):
            raise ValueError("snapshot records must belong to the snapshot run")
        chunk_ids = {item.chunk_id for item in chunks}
        payload_ids = {item.payload_id for item in occurrences}
        if any(item.chunk_id is not None and item.chunk_id not in chunk_ids for item in diagnostics):
            raise ValueError("snapshot diagnostic references a chunk outside the snapshot")
        if any(
            item.payload_id is not None and item.payload_id not in payload_ids for item in diagnostics
        ):
            raise ValueError("snapshot diagnostic references a payload outside the snapshot")
        object.__setattr__(self, "chunks", tuple(sorted(chunks, key=lambda item: (item.ordinal, item.chunk_id))))
        object.__setattr__(
            self,
            "payload_occurrences",
            tuple(sorted(occurrences, key=lambda item: (item.payload_id, item.occurrence_ordinal))),
        )
        object.__setattr__(
            self,
            "processing_diagnostics",
            tuple(sorted(diagnostics, key=lambda item: (item.diagnostic_id, item.code))),
        )

    @staticmethod
    def _typed_tuple(values: Any, item_type: type, name: str) -> tuple[Any, ...]:
        try:
            items = tuple(values)
        except TypeError as exc:
            raise TypeError(f"{name} must be iterable") from exc
        if any(not isinstance(item, item_type) for item in items):
            raise TypeError(f"{name} contains an invalid record")
        return items

    @staticmethod
    def _reject_duplicates(values: Any, name: str) -> None:
        items = tuple(values)
        if len(items) != len(set(items)):
            raise ValueError(f"snapshot contains duplicate {name}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AUDIT_SNAPSHOT_SCHEMA_VERSION,
            "ruleset_version": self.ruleset_version,
            "run": self.run.to_dict(),
            "chunks": [item.to_dict() for item in self.chunks],
            "payload_occurrences": [item.to_dict() for item in self.payload_occurrences],
            "processing_diagnostics": [item.to_dict() for item in self.processing_diagnostics],
        }


@dataclass(frozen=True)
class AuditTarget:
    kind: str
    target_id: str

    def __post_init__(self) -> None:
        validate_target_kind(self.kind)
        validate_target_id(self.target_id)

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "target_id": self.target_id}


@dataclass(frozen=True)
class Suppression:
    reason_code: str
    processing_diagnostic_ids: tuple[str, ...]
    details: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_reason_code(self.reason_code)
        if not isinstance(self.details, Mapping):
            raise TypeError("suppression details must be a mapping")
        try:
            candidate_ids = tuple(self.processing_diagnostic_ids)
        except TypeError as exc:
            raise TypeError("processing diagnostic ids must be iterable") from exc
        if not candidate_ids:
            raise ValueError("suppression requires a processing diagnostic id")
        unique_ids: list[str] = []
        seen: set[str] = set()
        for diagnostic_id in candidate_ids:
            validate_target_id(diagnostic_id)
            if diagnostic_id not in seen:
                unique_ids.append(diagnostic_id)
                seen.add(diagnostic_id)
        object.__setattr__(self, "processing_diagnostic_ids", tuple(unique_ids))
        object.__setattr__(self, "details", canonicalize_safe_json(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "processing_diagnostic_ids": list(self.processing_diagnostic_ids),
            "details": safe_json_to_dict(self.details),
        }


@dataclass(frozen=True)
class RuleResult:
    ruleset_version: str
    rule_id: str
    outcome: RuleOutcome
    target: AuditTarget
    severity: Severity | None = None
    diagnostic_key: str | None = None
    origin: DiagnosticOrigin | None = None
    message: str | None = None
    details: Any = field(default_factory=dict)
    suppression: Suppression | None = None

    def __post_init__(self) -> None:
        validate_ruleset_version(self.ruleset_version)
        validate_rule_id(self.rule_id)
        if not isinstance(self.outcome, RuleOutcome):
            raise TypeError("outcome must be a RuleOutcome")
        if not isinstance(self.target, AuditTarget):
            raise TypeError("target must be an AuditTarget")
        if not isinstance(self.details, Mapping):
            raise TypeError("result details must be a mapping")
        details = canonicalize_safe_json(self.details)
        message = self.message
        if message is not None:
            message = canonicalize_safe_json(message)
            if not isinstance(message, str) or not message:
                raise ValueError("message must be a non-empty safe string")
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "details", details)

        if self.outcome is RuleOutcome.FINDING:
            self._validate_finding(details)
        elif self.outcome is RuleOutcome.SUPPRESSED:
            if not isinstance(self.suppression, Suppression):
                raise TypeError("suppressed result requires a Suppression")
            self._reject_finding_fields()
        else:
            if self.suppression is not None:
                raise ValueError("pass and not-applicable results cannot be suppressed")
            self._reject_finding_fields()

    def _validate_finding(self, details: Any) -> None:
        if not isinstance(self.severity, Severity):
            raise TypeError("finding severity must be a Severity")
        if self.origin is not DiagnosticOrigin.AUDIT_RULE:
            raise ValueError("finding origin must be audit_rule")
        if self.message is None:
            raise ValueError("finding requires a message")
        if self.suppression is not None:
            raise ValueError("finding cannot carry suppression")
        expected_key = build_diagnostic_key(
            self.ruleset_version,
            self.target.kind,
            self.target.target_id,
            self.rule_id,
        )
        if self.diagnostic_key != expected_key:
            raise ValueError("finding diagnostic key is not canonical")
        projected = safe_json_to_dict(details)
        if projected.get("ruleset_version") != self.ruleset_version:
            raise ValueError("finding details must carry the matching ruleset version")

    def _reject_finding_fields(self) -> None:
        if any(
            value is not None
            for value in (self.severity, self.diagnostic_key, self.origin, self.message)
        ):
            raise ValueError("non-finding result carries finding-only fields")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RULE_RESULT_SCHEMA_VERSION,
            "ruleset_version": self.ruleset_version,
            "rule_id": self.rule_id,
            "outcome": self.outcome.value,
            "target": self.target.to_dict(),
            "severity": self.severity.value if self.severity is not None else None,
            "diagnostic_key": self.diagnostic_key,
            "origin": self.origin.value if self.origin is not None else None,
            "message": self.message,
            "details": safe_json_to_dict(self.details),
            "suppression": self.suppression.to_dict() if self.suppression is not None else None,
        }


@dataclass(frozen=True)
class LifecycleDiagnostic:
    code: str
    message: str
    details: Any = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_non_empty_string(self.code, name="code")
        message = canonicalize_safe_json(self.message)
        if not isinstance(message, str) or not message:
            raise ValueError("message must be a non-empty safe string")
        if not isinstance(self.details, Mapping):
            raise TypeError("lifecycle diagnostic details must be a mapping")
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "details", canonicalize_safe_json(self.details))

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": safe_json_to_dict(self.details),
        }


@dataclass(frozen=True)
class AuditLifecycleResult:
    outcome: LifecycleOutcome
    ruleset_version: str
    run_id: str | None
    code: str | None
    checked_rule_count: int | None
    outcome_counts: Mapping[RuleOutcome, int] | None
    severity_counts: Mapping[Severity, int] | None
    diagnostic: LifecycleDiagnostic | None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, LifecycleOutcome):
            raise TypeError("outcome must be a LifecycleOutcome")
        validate_ruleset_version(self.ruleset_version)
        if self.outcome is LifecycleOutcome.NO_RUN:
            if any(
                value is not None
                for value in (
                    self.run_id,
                    self.code,
                    self.checked_rule_count,
                    self.outcome_counts,
                    self.severity_counts,
                    self.diagnostic,
                )
            ):
                raise ValueError("no-run lifecycle cannot carry write-shaped fields")
            return

        _require_non_empty_string(self.run_id, name="run_id")
        if self.outcome is LifecycleOutcome.FAILED:
            self._validate_failed()
            return
        self._validate_completed()

    def _validate_failed(self) -> None:
        if self.code != AUDIT_FAILED:
            raise ValueError("failed lifecycle code must be AUDIT_FAILED")
        if not isinstance(self.diagnostic, LifecycleDiagnostic):
            raise TypeError("failed lifecycle requires a diagnostic")
        if self.diagnostic.code != AUDIT_FAILED:
            raise ValueError("failed lifecycle diagnostic code must be AUDIT_FAILED")
        if any(
            value is not None
            for value in (self.checked_rule_count, self.outcome_counts, self.severity_counts)
        ):
            raise ValueError("failed lifecycle cannot carry completed counts")

    def _validate_completed(self) -> None:
        if self.code != AUDIT_COMPLETED:
            raise ValueError("completed lifecycle code must be AUDIT_COMPLETED")
        if self.diagnostic is not None:
            raise ValueError("completed lifecycle cannot carry a failure diagnostic")
        if self.checked_rule_count is None:
            raise TypeError("completed lifecycle requires checked_rule_count")
        _require_non_negative(self.checked_rule_count, name="checked_rule_count")
        outcome_counts = self._validated_counts(
            self.outcome_counts, RuleOutcome, "outcome_counts"
        )
        severity_counts = self._validated_counts(
            self.severity_counts, Severity, "severity_counts"
        )
        if sum(outcome_counts.values()) != self.checked_rule_count:
            raise ValueError("outcome counts must total checked_rule_count")
        if sum(severity_counts.values()) != outcome_counts[RuleOutcome.FINDING]:
            raise ValueError("severity counts must total finding count")
        object.__setattr__(self, "outcome_counts", MappingProxyType(outcome_counts))
        object.__setattr__(self, "severity_counts", MappingProxyType(severity_counts))

    @staticmethod
    def _validated_counts(values: Any, enum_type: type, name: str) -> dict[Any, int]:
        if not isinstance(values, Mapping):
            raise TypeError(f"{name} must be a mapping")
        expected = tuple(enum_type)
        if set(values) != set(expected) or any(not isinstance(key, enum_type) for key in values):
            raise ValueError(f"{name} must contain every exact enum key")
        counts = {key: values[key] for key in expected}
        for value in counts.values():
            _require_non_negative(value, name=name)
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AUDIT_LIFECYCLE_SCHEMA_VERSION,
            "outcome": self.outcome.value,
            "ruleset_version": self.ruleset_version,
            "run_id": self.run_id,
            "code": self.code,
            "checked_rule_count": self.checked_rule_count,
            "outcome_counts": self._counts_to_dict(self.outcome_counts, RuleOutcome),
            "severity_counts": self._counts_to_dict(self.severity_counts, Severity),
            "diagnostic": self.diagnostic.to_dict() if self.diagnostic is not None else None,
        }

    @staticmethod
    def _counts_to_dict(values: Mapping | None, enum_type: type) -> dict[str, int] | None:
        if values is None:
            return None
        return {key.value: values[key] for key in enum_type}


@dataclass(frozen=True)
class AuditRule:
    rule_id: str
    target_kind: str
    severity: Severity

    def __post_init__(self) -> None:
        validate_rule_id(self.rule_id)
        validate_target_kind(self.target_kind)
        if not isinstance(self.severity, Severity):
            raise TypeError("severity must be a Severity")

    def to_dict(self) -> dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "target_kind": self.target_kind,
            "severity": self.severity.value,
        }


@dataclass(frozen=True)
class AuditRuleset:
    version: str
    rules: tuple[AuditRule, ...]

    def __post_init__(self) -> None:
        validate_ruleset_version(self.version)
        try:
            rules = tuple(self.rules)
        except TypeError as exc:
            raise TypeError("rules must be iterable") from exc
        if not rules:
            raise ValueError("ruleset requires at least one rule")
        if any(not isinstance(rule, AuditRule) for rule in rules):
            raise TypeError("ruleset entries must be AuditRule values")
        rule_ids = [rule.rule_id for rule in rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("ruleset contains duplicate rule ids")
        object.__setattr__(self, "rules", rules)

    def diagnostic_key(self, target: AuditTarget, rule_id: str) -> str:
        if not isinstance(target, AuditTarget):
            raise TypeError("target must be an AuditTarget")
        rule = next((item for item in self.rules if item.rule_id == rule_id), None)
        if rule is None:
            raise ValueError("rule_id is not declared by this ruleset")
        if target.kind != rule.target_kind:
            raise ValueError("target kind does not match the declared rule target kind")
        return build_diagnostic_key(self.version, target.kind, target.target_id, rule_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "rules": [rule.to_dict() for rule in self.rules],
        }


__all__ = [
    "AUDIT_COMPLETED",
    "AUDIT_FAILED",
    "AUDIT_LIFECYCLE_SCHEMA_VERSION",
    "AUDIT_SNAPSHOT_SCHEMA_VERSION",
    "RULE_RESULT_SCHEMA_VERSION",
    "AuditChunk",
    "AuditLifecycleResult",
    "AuditPayloadOccurrence",
    "AuditRule",
    "AuditRun",
    "AuditRuleset",
    "AuditSnapshot",
    "AuditTarget",
    "DiagnosticOrigin",
    "LifecycleDiagnostic",
    "LifecycleOutcome",
    "ProcessingDiagnostic",
    "RuleOutcome",
    "RuleResult",
    "Severity",
    "Suppression",
]
