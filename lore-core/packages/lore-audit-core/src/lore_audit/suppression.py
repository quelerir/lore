"""Exact, deterministic classification of processing-explained audit findings."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .contracts import ProcessingDiagnostic, RuleOutcome, RuleResult, Suppression
from .validation import safe_json_to_dict

_TRANSCRIPT_CODES = frozenset(
    {
        "TRAN-01-NO_RELIABLE_SLOTS",
        "TRAN-01-INVALID_COORDINATE",
        "LLM-NONCONTIGUOUS-COVERAGE",
        "LLM-COVERAGE",
        "TRAN-04-VALIDATION",
    }
)
_SCOPE_KEYS = frozenset(
    {
        "slot_id",
        "source_slot_id",
        "occurrence_ordinal",
        "range",
        "sheet",
        "source_location",
    }
)


@dataclass(frozen=True)
class SuppressionMap:
    """Immutable rule-to-processing-code metadata for one exact ruleset."""

    version: str
    rules: Mapping[str, frozenset[str]]

    def __post_init__(self) -> None:
        frozen = {
            rule_id: frozenset(codes)
            for rule_id, codes in sorted(self.rules.items())
        }
        object.__setattr__(self, "rules", MappingProxyType(frozen))

    def codes_for(self, rule_id: str) -> frozenset[str]:
        return self.rules.get(rule_id, frozenset())


AUDIT_V1_SUPPRESSION_MAP = SuppressionMap(
    version="audit/v1",
    rules={
        "chunk_texts": frozenset(
            {
                "empty_display_text",
                "empty_vector_text",
                "empty_fulltext",
                "budget_display_text",
                "budget_vector_text",
                "budget_fulltext",
            }
        ),
        "chunk_ordinal": frozenset({"invalid_ordinal"}),
        "vector_hard_limit": frozenset({"vector_token_hard_limit"}),
        "payload_references": frozenset({"unresolved_payload_ref"}),
        "table_metadata": frozenset({"low_meaning_table", "low_meaning_fragment"}),
        "table_summary": frozenset({"low_meaning_table", "low_meaning_fragment"}),
        "image_metadata": frozenset(
            {"image_skipped", "external_image_failed", "image_extraction_failed"}
        ),
        "image_storage_identity": frozenset(
            {"image_skipped", "external_image_failed", "image_extraction_failed"}
        ),
        "transcript_speakers": _TRANSCRIPT_CODES,
        "transcript_intervals": _TRANSCRIPT_CODES,
        "transcript_ordering": _TRANSCRIPT_CODES,
        "transcript_source_splits": _TRANSCRIPT_CODES,
    },
)


def _target_matches(result: RuleResult, diagnostic: ProcessingDiagnostic) -> bool:
    if result.target.kind == "chunk":
        return diagnostic.chunk_id == result.target.target_id
    if result.target.kind == "payload":
        return diagnostic.payload_id == result.target.target_id
    return False


def _scope_matches(defect: Mapping[str, Any], diagnostic: ProcessingDiagnostic) -> bool:
    details = safe_json_to_dict(diagnostic.details)
    scoped = sorted(key for key in _SCOPE_KEYS if key in defect)
    return not scoped or all(details.get(key) == defect[key] for key in scoped)


def _covers(defect: Mapping[str, Any], diagnostic: ProcessingDiagnostic) -> bool:
    if not _scope_matches(defect, diagnostic):
        return False
    defect_code = defect.get("code")
    parser_code = defect.get("parser_code")
    if diagnostic.code in {defect_code, parser_code}:
        return True
    details = safe_json_to_dict(diagnostic.details)
    declared_codes = details.get("defect_codes", ())
    return (
        isinstance(declared_codes, list)
        and isinstance(defect_code, str)
        and defect_code in declared_codes
    )


def _finding_with_related_ids(result: RuleResult, diagnostic_ids: tuple[str, ...]) -> RuleResult:
    details = safe_json_to_dict(result.details)
    details["related_processing_diagnostic_ids"] = list(diagnostic_ids)
    return RuleResult(
        ruleset_version=result.ruleset_version,
        rule_id=result.rule_id,
        outcome=result.outcome,
        target=result.target,
        severity=result.severity,
        diagnostic_key=result.diagnostic_key,
        origin=result.origin,
        message=result.message,
        details=details,
    )


def classify_finding(
    result: RuleResult,
    diagnostics: Iterable[ProcessingDiagnostic],
) -> RuleResult:
    """Suppress only exact-target findings whose every bounded defect is explained."""

    if not isinstance(result, RuleResult) or result.outcome is not RuleOutcome.FINDING:
        raise TypeError("suppression classification requires a finding RuleResult")
    candidates = tuple(diagnostics)
    if any(not isinstance(item, ProcessingDiagnostic) for item in candidates):
        raise TypeError("diagnostics must contain ProcessingDiagnostic values")
    if result.ruleset_version != AUDIT_V1_SUPPRESSION_MAP.version:
        return result

    eligible_codes = AUDIT_V1_SUPPRESSION_MAP.codes_for(result.rule_id)
    if not eligible_codes:
        return result
    details = safe_json_to_dict(result.details)
    defects = details.get("defects")
    if not isinstance(defects, list) or not defects:
        return result

    eligible = tuple(
        sorted(
            (
                item
                for item in candidates
                if item.code in eligible_codes and _target_matches(result, item)
            ),
            key=lambda item: (item.diagnostic_id, item.code),
        )
    )
    covered_by = {
        index: tuple(item for item in eligible if _covers(defect, item))
        for index, defect in enumerate(defects)
        if isinstance(defect, Mapping)
    }
    related = tuple(
        sorted(
            {
                item.diagnostic_id
                for matches in covered_by.values()
                for item in matches
            }
        )
    )
    if details.get("truncated") is True:
        return _finding_with_related_ids(result, related) if related else result
    if len(covered_by) != len(defects) or any(not covered_by[index] for index in covered_by):
        return _finding_with_related_ids(result, related) if related else result

    matched = tuple(
        sorted(
            {
                (item.diagnostic_id, item.code)
                for matches in covered_by.values()
                for item in matches
            }
        )
    )
    original_facts = details
    original_facts.update(
        {
            "mapping_codes": sorted({code for _, code in matched}),
            "mapping_version": AUDIT_V1_SUPPRESSION_MAP.version,
        }
    )
    return RuleResult(
        ruleset_version=result.ruleset_version,
        rule_id=result.rule_id,
        outcome=RuleOutcome.SUPPRESSED,
        target=result.target,
        details={},
        suppression=Suppression(
            reason_code="explained_by_processing",
            processing_diagnostic_ids=tuple(identifier for identifier, _ in matched),
            details=original_facts,
        ),
    )


__all__ = ["AUDIT_V1_SUPPRESSION_MAP", "SuppressionMap", "classify_finding"]
