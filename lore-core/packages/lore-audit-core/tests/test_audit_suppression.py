from __future__ import annotations

import json

import pytest

from lore_audit.contracts import (
    AuditTarget,
    DiagnosticOrigin,
    ProcessingDiagnostic,
    RuleOutcome,
    RuleResult,
    Severity,
)
from lore_audit.suppression import (
    AUDIT_V1_SUPPRESSION_MAP,
    classify_finding,
)


def finding(rule_id="chunk_texts", defects=None, target=None, details=None):
    target = target or AuditTarget("chunk", "chunk-1")
    details = details or {
        "ruleset_version": "audit/v1",
        "defects": defects or [{"code": "empty_vector_text"}],
    }
    return RuleResult(
        ruleset_version="audit/v1",
        rule_id=rule_id,
        outcome=RuleOutcome.FINDING,
        target=target,
        severity=Severity.ERROR,
        diagnostic_key=f"audit/v1:{target.kind}:{target.target_id}:{rule_id}",
        origin=DiagnosticOrigin.AUDIT_RULE,
        message="bounded finding",
        details=details,
    )


def diagnostic(identifier="diag-1", code="empty_vector_text", **overrides):
    values = dict(
        diagnostic_id=identifier,
        run_id="run-1",
        chunk_id="chunk-1",
        payload_id=None,
        level="warning",
        code=code,
        message="ignored prose",
        stage="ignored-stage",
        details={},
    )
    values.update(overrides)
    return ProcessingDiagnostic(**values)


def test_exact_target_code_and_complete_coverage_suppresses_with_original_facts():
    raw = finding(defects=[{"code": "empty_vector_text"}, {"code": "budget_fulltext"}])
    result = classify_finding(raw, (diagnostic("diag-2", "budget_fulltext"), diagnostic()))

    assert result.outcome is RuleOutcome.SUPPRESSED
    assert result.suppression.reason_code == "explained_by_processing"
    assert result.suppression.processing_diagnostic_ids == ("diag-1", "diag-2")
    assert result.to_dict()["suppression"]["details"] == {
        "defects": [{"code": "empty_vector_text"}, {"code": "budget_fulltext"}],
        "mapping_codes": ["budget_fulltext", "empty_vector_text"],
        "mapping_version": "audit/v1",
        "ruleset_version": "audit/v1",
    }


def test_partial_exact_coverage_stays_one_finding_with_related_ids():
    raw = finding(defects=[{"code": "empty_vector_text"}, {"code": "budget_fulltext"}])
    result = classify_finding(raw, (diagnostic(),))

    assert result.outcome is RuleOutcome.FINDING
    assert result.diagnostic_key == raw.diagnostic_key
    assert result.to_dict()["details"]["related_processing_diagnostic_ids"] == ["diag-1"]
    assert result.to_dict()["details"]["defects"] == raw.to_dict()["details"]["defects"]


def test_truncated_complete_retained_coverage_stays_finding_with_related_ids():
    defects = [
        {"code": "unresolved_payload_ref", "occurrence_ordinal": ordinal}
        for ordinal in range(8)
    ]
    raw = finding(
        rule_id="payload_references",
        details={
            "ruleset_version": "audit/v1",
            "defects": defects,
            "total": 9,
            "truncated": True,
        },
    )
    diagnostics = tuple(
        diagnostic(
            f"diag-{ordinal}",
            "unresolved_payload_ref",
            details={"occurrence_ordinal": ordinal},
        )
        for ordinal in range(8)
    )

    result = classify_finding(raw, diagnostics)

    assert result.outcome is RuleOutcome.FINDING
    assert result.to_dict()["details"]["related_processing_diagnostic_ids"] == [
        f"diag-{ordinal}" for ordinal in range(8)
    ]
    assert result.to_dict()["details"]["truncated"] is True


def test_unrelated_target_unlisted_and_broad_codes_never_suppress():
    raw = finding()
    unrelated = diagnostic(chunk_id="chunk-2")
    broad = diagnostic("diag-2", "deterministic_processing_failure")
    result = classify_finding(raw, (unrelated, broad))

    assert result.outcome is RuleOutcome.FINDING
    assert "related_processing_diagnostic_ids" not in result.to_dict()["details"]


def test_payload_target_requires_exact_payload_and_explicit_defect_coverage():
    raw = finding(
        rule_id="table_metadata",
        defects=[{"code": "missing_table_metadata", "fields": ["columns"]}],
        target=AuditTarget("payload", "table-1"),
    )
    matching = diagnostic(
        code="low_meaning_table",
        chunk_id=None,
        payload_id="table-1",
        details={"defect_codes": ["missing_table_metadata"]},
    )
    unrelated = diagnostic(
        "diag-2",
        "low_meaning_table",
        chunk_id=None,
        payload_id="table-2",
        details={"defect_codes": ["missing_table_metadata"]},
    )

    assert classify_finding(raw, (matching,)).outcome is RuleOutcome.SUPPRESSED
    assert classify_finding(raw, (unrelated,)).outcome is RuleOutcome.FINDING


def test_transcript_parser_code_and_slot_scope_must_both_match():
    raw = finding(
        rule_id="transcript_intervals",
        defects=[
            {
                "code": "invalid_slot_interval",
                "parser_code": "TRAN-01-INVALID_COORDINATE",
                "slot_id": "slot-7",
            }
        ],
    )
    matching = diagnostic(
        code="TRAN-01-INVALID_COORDINATE",
        details={"slot_id": "slot-7"},
    )
    wrong_slot = diagnostic(
        "diag-2",
        "TRAN-01-INVALID_COORDINATE",
        details={"slot_id": "slot-8"},
    )

    assert classify_finding(raw, (matching,)).outcome is RuleOutcome.SUPPRESSED
    assert classify_finding(raw, (wrong_slot,)).outcome is RuleOutcome.FINDING


def test_diagnostic_permutations_ignore_prose_level_and_stage_and_serialize_identically():
    raw = finding(defects=[{"code": "empty_vector_text"}, {"code": "budget_fulltext"}])
    diagnostics = (
        diagnostic("diag-2", "budget_fulltext", message="secret two", level="error", stage="x"),
        diagnostic("diag-1", "empty_vector_text", message="secret one", level="info", stage="y"),
    )

    first = classify_finding(raw, diagnostics)
    second = classify_finding(raw, tuple(reversed(diagnostics)))

    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)
    assert "secret" not in json.dumps(first.to_dict())


@pytest.mark.parametrize(
    "code",
    ("deterministic_processing_failure", "lane_warning", "LLM-FATAL", "LLM-RETRY-EXHAUSTED"),
)
def test_broad_codes_never_enter_the_exact_map(code):
    assert all(code not in AUDIT_V1_SUPPRESSION_MAP.codes_for(rule_id) for rule_id in (
        "chunk_texts",
        "payload_references",
        "transcript_intervals",
    ))


def test_versioned_map_covers_each_narrow_eligible_family():
    assert AUDIT_V1_SUPPRESSION_MAP.version == "audit/v1"
    for rule_id in (
        "chunk_texts",
        "chunk_ordinal",
        "vector_hard_limit",
        "payload_references",
        "table_metadata",
        "table_summary",
        "image_metadata",
        "image_storage_identity",
        "transcript_speakers",
        "transcript_intervals",
        "transcript_ordering",
        "transcript_source_splits",
    ):
        assert AUDIT_V1_SUPPRESSION_MAP.codes_for(rule_id)
