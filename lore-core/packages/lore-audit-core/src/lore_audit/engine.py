"""Deterministic, fail-closed orchestration for the pure audit/v1 engine."""

from __future__ import annotations

from .contracts import (
    AUDIT_COMPLETED,
    AUDIT_FAILED,
    AuditLifecycleResult,
    AuditTarget,
    LifecycleDiagnostic,
    LifecycleOutcome,
    RuleOutcome,
    RuleResult,
    Severity,
)
from .engine_contracts import AuditEngineInput, AuditEngineResult, EMPTY_DOMAIN_TARGET_ID
from .rules.chunks import (
    evaluate_chunk_coordinates,
    evaluate_chunk_ordinal,
    evaluate_chunk_texts,
    evaluate_chunk_type,
    evaluate_persisted_hashes,
    evaluate_vector_hard_limit,
)
from .rules.payloads import (
    evaluate_image_metadata,
    evaluate_image_storage_identity,
    evaluate_payload_occurrences,
    evaluate_payload_references,
    evaluate_payload_resolution,
    evaluate_table_metadata,
    evaluate_table_storage_identity,
    evaluate_table_summary,
)
from .rules.run import (
    evaluate_processing_diagnostics,
    evaluate_result_presence,
    evaluate_terminal_status,
)
from .rules.transcripts import (
    evaluate_transcript_intervals,
    evaluate_transcript_ordering,
    evaluate_transcript_source_splits,
    evaluate_transcript_speakers,
)
from .ruleset import select_rules, validate_evaluator_registry
from .suppression import classify_finding


def _evaluate_lifecycle_contract(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    return (
        RuleResult(
            ruleset_version=engine_input.ruleset_version,
            rule_id="lifecycle_contract",
            outcome=RuleOutcome.PASS,
            target=AuditTarget("run", engine_input.snapshot.run.run_id),
        ),
    )


_EVALUATORS = {
    "terminal_status": evaluate_terminal_status,
    "result_presence": evaluate_result_presence,
    "processing_diagnostics": evaluate_processing_diagnostics,
    "chunk_texts": evaluate_chunk_texts,
    "chunk_type": evaluate_chunk_type,
    "chunk_ordinal": evaluate_chunk_ordinal,
    "chunk_coordinates": evaluate_chunk_coordinates,
    "vector_hard_limit": evaluate_vector_hard_limit,
    "persisted_hashes": evaluate_persisted_hashes,
    "payload_references": evaluate_payload_references,
    "payload_occurrences": evaluate_payload_occurrences,
    "payload_resolution": evaluate_payload_resolution,
    "table_metadata": evaluate_table_metadata,
    "table_summary": evaluate_table_summary,
    "table_storage_identity": evaluate_table_storage_identity,
    "image_metadata": evaluate_image_metadata,
    "image_storage_identity": evaluate_image_storage_identity,
    "transcript_speakers": evaluate_transcript_speakers,
    "transcript_intervals": evaluate_transcript_intervals,
    "transcript_ordering": evaluate_transcript_ordering,
    "transcript_source_splits": evaluate_transcript_source_splits,
    "lifecycle_contract": _evaluate_lifecycle_contract,
}


def _expected_target_ids(engine_input: AuditEngineInput, rule) -> frozenset[str]:
    if (
        rule.rule_id == "vector_hard_limit"
        and engine_input.snapshot.chunks
        and not engine_input.token_facts
    ):
        return frozenset({EMPTY_DOMAIN_TARGET_ID})
    if rule.target_kind == "run":
        return frozenset({engine_input.snapshot.run.run_id})
    if rule.target_kind == "chunk":
        target_ids = {chunk.chunk_id for chunk in engine_input.snapshot.chunks}
    else:
        target_ids = {
            occurrence.payload_id
            for occurrence in engine_input.snapshot.payload_occurrences
        }
        target_ids.update(fact.payload_id for fact in engine_input.payload_facts)
    return frozenset(target_ids or {EMPTY_DOMAIN_TARGET_ID})


def _completed(engine_input: AuditEngineInput, results: tuple[RuleResult, ...]) -> AuditEngineResult:
    outcome_counts = {outcome: 0 for outcome in RuleOutcome}
    severity_counts = {severity: 0 for severity in Severity}
    for result in results:
        outcome_counts[result.outcome] += 1
        if result.outcome is RuleOutcome.FINDING:
            severity_counts[result.severity] += 1
    lifecycle = AuditLifecycleResult(
        outcome=LifecycleOutcome.COMPLETED,
        ruleset_version=engine_input.ruleset_version,
        run_id=engine_input.snapshot.run.run_id,
        code=AUDIT_COMPLETED,
        checked_rule_count=len(results),
        outcome_counts=outcome_counts,
        severity_counts=severity_counts,
        diagnostic=None,
    )
    return AuditEngineResult(results, lifecycle)


def _failed(
    engine_input: AuditEngineInput,
    failed_rule_id: str,
    exception: Exception,
) -> AuditEngineResult:
    diagnostic = LifecycleDiagnostic(
        code=AUDIT_FAILED,
        message="Audit evaluation failed closed",
        details={
            "ruleset_version": engine_input.ruleset_version,
            "run_id": engine_input.snapshot.run.run_id,
            "failed_rule_id": failed_rule_id,
            "exception_class": type(exception).__name__,
        },
    )
    lifecycle = AuditLifecycleResult(
        outcome=LifecycleOutcome.FAILED,
        ruleset_version=engine_input.ruleset_version,
        run_id=engine_input.snapshot.run.run_id,
        code=AUDIT_FAILED,
        checked_rule_count=None,
        outcome_counts=None,
        severity_counts=None,
        diagnostic=diagnostic,
    )
    return AuditEngineResult((), lifecycle)


def run_audit(engine_input: AuditEngineInput) -> AuditEngineResult:
    """Evaluate exact audit/v1 rules in catalog order using only supplied facts."""

    if not isinstance(engine_input, AuditEngineInput):
        raise TypeError("engine_input must be an AuditEngineInput")

    failed_rule_id = "registry_validation"
    try:
        validate_evaluator_registry(_EVALUATORS)
        selected_rules = select_rules(engine_input.snapshot.run.status)
        results: list[RuleResult] = []
        identities: set[tuple[str, str, str]] = set()

        for rule in selected_rules:
            failed_rule_id = rule.rule_id
            evaluated = tuple(_EVALUATORS[rule.rule_id](engine_input))
            if any(not isinstance(result, RuleResult) for result in evaluated):
                raise TypeError("evaluator output must contain RuleResult values")
            actual_target_ids = frozenset(
                result.target.target_id for result in evaluated
            )
            if actual_target_ids != _expected_target_ids(engine_input, rule):
                raise ValueError("evaluator output target domain mismatch")
            ordered = sorted(
                evaluated,
                key=lambda result: (result.target.kind, result.target.target_id),
            )
            for result in ordered:
                if result.ruleset_version != engine_input.ruleset_version:
                    raise ValueError("evaluator output ruleset version mismatch")
                if result.rule_id != rule.rule_id:
                    raise ValueError("evaluator output rule id mismatch")
                if result.target.kind != rule.target_kind:
                    raise ValueError("evaluator output target kind mismatch")
                identity = (result.rule_id, result.target.kind, result.target.target_id)
                if identity in identities:
                    raise ValueError("duplicate evaluator output identity")
                identities.add(identity)
                if result.outcome is RuleOutcome.FINDING:
                    result = classify_finding(
                        result,
                        engine_input.snapshot.processing_diagnostics,
                    )
                results.append(result)
        return _completed(engine_input, tuple(results))
    except Exception as exc:
        return _failed(engine_input, failed_rule_id, exc)


__all__ = ["run_audit"]
