"""The sole supported audit/v1 rule catalog and pure dispatch metadata."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from lore_core_domain.run_status import RunStatus

from .contracts import AuditRule, AuditRuleset, AuditTarget, RuleResult, Severity
from .engine_contracts import AuditEngineInput, EMPTY_DOMAIN_TARGET_ID
from .validation import MAX_TARGET_ID_LENGTH, validate_target_id


class RuleEvaluator(Protocol):
    def __call__(self, engine_input: AuditEngineInput) -> tuple[RuleResult, ...]: ...


AUDIT_V1_RULESET = AuditRuleset(
    version="audit/v1",
    rules=(
        AuditRule("terminal_status", "run", Severity.ERROR),
        AuditRule("result_presence", "run", Severity.ERROR),
        AuditRule("processing_diagnostics", "run", Severity.WARNING),
        AuditRule("chunk_texts", "chunk", Severity.ERROR),
        AuditRule("chunk_type", "chunk", Severity.WARNING),
        AuditRule("chunk_ordinal", "chunk", Severity.ERROR),
        AuditRule("chunk_coordinates", "chunk", Severity.WARNING),
        AuditRule("vector_hard_limit", "chunk", Severity.ERROR),
        AuditRule("persisted_hashes", "chunk", Severity.ERROR),
        AuditRule("payload_references", "chunk", Severity.ERROR),
        AuditRule("payload_occurrences", "payload", Severity.ERROR),
        AuditRule("payload_resolution", "payload", Severity.ERROR),
        AuditRule("table_metadata", "payload", Severity.WARNING),
        AuditRule("table_summary", "payload", Severity.WARNING),
        AuditRule("table_storage_identity", "payload", Severity.ERROR),
        AuditRule("image_metadata", "payload", Severity.WARNING),
        AuditRule("image_storage_identity", "payload", Severity.ERROR),
        AuditRule("transcript_speakers", "chunk", Severity.WARNING),
        AuditRule("transcript_intervals", "chunk", Severity.ERROR),
        AuditRule("transcript_ordering", "chunk", Severity.ERROR),
        AuditRule("transcript_source_splits", "chunk", Severity.WARNING),
        AuditRule("lifecycle_contract", "run", Severity.CRITICAL),
    ),
)

_RESULT_CONTRACT_RULE_IDS = frozenset(
    {"terminal_status", "result_presence", "processing_diagnostics", "lifecycle_contract"}
)

validate_target_id(EMPTY_DOMAIN_TARGET_ID)
if len(EMPTY_DOMAIN_TARGET_ID) > MAX_TARGET_ID_LENGTH:  # pragma: no cover - import invariant
    raise RuntimeError("empty-domain target exceeds the Phase 19 target bound")


def _require_exact_ruleset(ruleset: AuditRuleset) -> None:
    if not isinstance(ruleset, AuditRuleset):
        raise TypeError("ruleset must be an AuditRuleset")
    if ruleset.to_dict() != AUDIT_V1_RULESET.to_dict():
        raise ValueError("ruleset must be the exact audit/v1 catalog")


def select_rules(status: RunStatus, ruleset: AuditRuleset = AUDIT_V1_RULESET) -> tuple[AuditRule, ...]:
    """Select from the one catalog without maintaining a second ordered list."""

    _require_exact_ruleset(ruleset)
    if not isinstance(status, RunStatus):
        raise TypeError("status must be a RunStatus")
    if status is RunStatus.SUCCESS:
        return ruleset.rules
    if status not in {RunStatus.FAILED, RunStatus.SKIPPED, RunStatus.STALE}:
        raise ValueError("audit selection requires a terminal run status")
    return tuple(rule for rule in ruleset.rules if rule.rule_id in _RESULT_CONTRACT_RULE_IDS)


def validate_evaluator_registry(registry: Mapping[str, RuleEvaluator]) -> None:
    """Fail closed unless every and only catalog rule has one callable."""

    if not isinstance(registry, Mapping):
        raise TypeError("evaluator registry must be a mapping")
    expected = {rule.rule_id for rule in AUDIT_V1_RULESET.rules}
    actual = set(registry)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise ValueError(f"evaluator registry parity mismatch: missing={missing}, extra={extra}")
    non_callable = sorted(rule_id for rule_id in expected if not callable(registry[rule_id]))
    if non_callable:
        raise TypeError(f"evaluator registry entries are not callable: {non_callable}")


def empty_domain_target(rule: AuditRule) -> AuditTarget:
    """Return the collision-safe same-kind target used for one normal N/A result."""

    if not isinstance(rule, AuditRule):
        raise TypeError("rule must be an AuditRule")
    declared = next(
        (candidate for candidate in AUDIT_V1_RULESET.rules if candidate.rule_id == rule.rule_id),
        None,
    )
    if declared is None or declared.to_dict() != rule.to_dict():
        raise ValueError("rule is not exact declared audit/v1 metadata")
    return AuditTarget(kind=rule.target_kind, target_id=EMPTY_DOMAIN_TARGET_ID)


__all__ = [
    "AUDIT_V1_RULESET",
    "EMPTY_DOMAIN_TARGET_ID",
    "RuleEvaluator",
    "empty_domain_target",
    "select_rules",
    "validate_evaluator_registry",
]
