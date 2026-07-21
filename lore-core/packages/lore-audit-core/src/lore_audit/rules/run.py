"""Pure audit/v1 evaluators for terminal run and result-contract facts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Any

from lore_core_domain.run_status import RunStatus

from ..contracts import (
    AuditTarget,
    DiagnosticOrigin,
    RuleOutcome,
    RuleResult,
)
from ..engine_contracts import AuditEngineInput
from ..ruleset import AUDIT_V1_RULESET

_MAX_DIAGNOSTIC_EVIDENCE = 8


def _declared_rule(rule_id: str):
    return next(rule for rule in AUDIT_V1_RULESET.rules if rule.rule_id == rule_id)


def _result(
    engine_input: AuditEngineInput,
    rule_id: str,
    defects: list[Mapping[str, Any]],
    *,
    details: Mapping[str, Any] | None = None,
) -> RuleResult:
    target = AuditTarget(kind="run", target_id=engine_input.snapshot.run.run_id)
    if not defects:
        return RuleResult(
            ruleset_version=engine_input.ruleset_version,
            rule_id=rule_id,
            outcome=RuleOutcome.PASS,
            target=target,
            details=details or {},
        )
    rule = _declared_rule(rule_id)
    finding_details = {
        "ruleset_version": engine_input.ruleset_version,
        "defects": defects,
    }
    if details:
        finding_details.update(details)
    return RuleResult(
        ruleset_version=engine_input.ruleset_version,
        rule_id=rule_id,
        outcome=RuleOutcome.FINDING,
        target=target,
        severity=rule.severity,
        diagnostic_key=AUDIT_V1_RULESET.diagnostic_key(target, rule_id),
        origin=DiagnosticOrigin.AUDIT_RULE,
        message=f"Audit rule {rule_id} found inconsistent persisted facts",
        details=finding_details,
    )


def evaluate_terminal_status(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Check count/status combinations that remain possible after contract validation."""

    run = engine_input.snapshot.run
    defects: list[Mapping[str, Any]] = []
    if run.status is RunStatus.SUCCESS and run.error_count:
        defects.append({"code": "success_has_errors", "error_count": run.error_count})
    elif run.status is RunStatus.FAILED and run.error_count == 0:
        defects.append({"code": "failed_without_errors", "error_count": 0})
    elif run.status is RunStatus.SKIPPED and run.error_count:
        defects.append({"code": "skipped_has_errors", "error_count": run.error_count})
    elif run.status is RunStatus.STALE and run.error_count == 0:
        defects.append({"code": "stale_without_errors", "error_count": 0})
    return (_result(engine_input, "terminal_status", defects),)


def evaluate_result_presence(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Compare persisted run counts with canonical chunk and registration identities."""

    run = engine_input.snapshot.run
    actual = {
        "chunk_count": len(engine_input.snapshot.chunks),
        "payload_count": len(engine_input.payload_facts),
    }
    expected = {"chunk_count": run.chunk_count, "payload_count": run.payload_count}
    defects: list[Mapping[str, Any]] = []
    if run.status is RunStatus.SUCCESS:
        if actual["chunk_count"] != expected["chunk_count"]:
            defects.append({"code": "chunk_count_mismatch"})
        if actual["payload_count"] != expected["payload_count"]:
            defects.append({"code": "payload_count_mismatch"})
    elif any(
        (
            run.chunk_count,
            run.payload_count,
            len(engine_input.snapshot.chunks),
            len(engine_input.snapshot.payload_occurrences),
            len(engine_input.token_facts),
            len(engine_input.payload_facts),
        )
    ):
        defects.append({"code": "non_success_has_results"})
    details = {"actual": actual, "expected": expected} if defects else None
    return (_result(engine_input, "result_presence", defects, details=details),)


def evaluate_processing_diagnostics(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Check diagnostic count consistency and expose bounded stable ID/code evidence."""

    run = engine_input.snapshot.run
    diagnostics = engine_input.snapshot.processing_diagnostics
    level_counts = Counter(item.level for item in diagnostics)
    code_counts = Counter(item.code for item in diagnostics)
    defects: list[Mapping[str, Any]] = []
    if run.status is not RunStatus.SUCCESS and not diagnostics:
        defects.append({"code": "missing_processing_diagnostic"})
    unsupported_levels = sorted(set(level_counts) - {"warning", "error"})
    if unsupported_levels:
        defects.append(
            {"code": "unsupported_diagnostic_level", "levels": unsupported_levels}
        )
    if (
        level_counts.get("warning", 0) != run.warning_count
        or level_counts.get("error", 0) != run.error_count
    ):
        defects.append(
            {
                "code": "diagnostic_count_mismatch",
                "expected_error_count": run.error_count,
                "expected_warning_count": run.warning_count,
            }
        )
    facts = [
        {"diagnostic_id": item.diagnostic_id, "code": item.code}
        for item in diagnostics[:_MAX_DIAGNOSTIC_EVIDENCE]
    ]
    details = {
        "diagnostics": facts,
        "level_counts": dict(sorted(level_counts.items())),
        "code_counts": dict(sorted(code_counts.items())),
        "total_count": len(diagnostics),
        "truncated": len(diagnostics) > _MAX_DIAGNOSTIC_EVIDENCE,
    }
    if not diagnostics and not defects:
        details = {}
    return (
        _result(
            engine_input,
            "processing_diagnostics",
            defects,
            details=details,
        ),
    )


__all__ = [
    "evaluate_processing_diagnostics",
    "evaluate_result_presence",
    "evaluate_terminal_status",
]
