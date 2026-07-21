"""Shared audit domain StrEnums extracted from contracts.py."""

from __future__ import annotations

from enum import StrEnum


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


__all__ = [
    "DiagnosticOrigin",
    "LifecycleOutcome",
    "RuleOutcome",
    "Severity",
]
