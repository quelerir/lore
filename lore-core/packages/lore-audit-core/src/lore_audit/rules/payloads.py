"""Pure audit/v1 evaluators for persisted payload and resolution facts."""

from __future__ import annotations

import re
from math import isfinite
from collections import defaultdict
from collections.abc import Callable, Mapping
from typing import Any

from ..contracts import AuditTarget, DiagnosticOrigin, RuleOutcome, RuleResult
from ..engine_contracts import AuditEngineInput, PayloadResolutionFact
from ..ruleset import AUDIT_V1_RULESET, empty_domain_target
from ..validation import safe_json_to_dict

_MAX_DEFECTS = 8
_MAX_LOCATION_ITEMS = 16
_MAX_REFERENCE_STRING = 256
_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)


def _rule(rule_id: str):
    return next(rule for rule in AUDIT_V1_RULESET.rules if rule.rule_id == rule_id)


def _result(
    engine_input: AuditEngineInput,
    rule_id: str,
    target: AuditTarget,
    defects: list[Mapping[str, Any]] | None = None,
    *,
    applicable: bool = True,
) -> RuleResult:
    if not applicable:
        return RuleResult(
            engine_input.ruleset_version, rule_id, RuleOutcome.NOT_APPLICABLE, target
        )
    defects = sorted(
        defects or [],
        key=lambda item: (
            str(item.get("code", "")),
            str(item.get("payload_id", "")),
            str(item.get("occurrence_ordinal", "")),
        ),
    )
    if not defects:
        return RuleResult(engine_input.ruleset_version, rule_id, RuleOutcome.PASS, target)
    declared = _rule(rule_id)
    details = {
        "ruleset_version": engine_input.ruleset_version,
        "defects": defects[:_MAX_DEFECTS],
        "total": len(defects),
        "truncated": len(defects) > _MAX_DEFECTS,
    }
    return RuleResult(
        ruleset_version=engine_input.ruleset_version,
        rule_id=rule_id,
        outcome=RuleOutcome.FINDING,
        target=target,
        severity=declared.severity,
        diagnostic_key=AUDIT_V1_RULESET.diagnostic_key(target, rule_id),
        origin=DiagnosticOrigin.AUDIT_RULE,
        message=f"Audit rule {rule_id} found inconsistent persisted payload facts",
        details=details,
    )


def _payload_domains(engine_input: AuditEngineInput) -> tuple[tuple[str, str], ...]:
    domains = {(fact.payload_id, fact.kind) for fact in engine_input.payload_facts}
    domains.update(
        (item.payload_id, item.kind) for item in engine_input.snapshot.payload_occurrences
    )
    return tuple(sorted(domains))


def _evaluate_payloads(
    engine_input: AuditEngineInput,
    rule_id: str,
    evaluator: Callable[[str, str, PayloadResolutionFact | None], list[Mapping[str, Any]]],
    *,
    selected_kind: str | None = None,
) -> tuple[RuleResult, ...]:
    domains = _payload_domains(engine_input)
    if not domains:
        return (
            _result(
                engine_input,
                rule_id,
                empty_domain_target(_rule(rule_id)),
                applicable=False,
            ),
        )
    facts = {(fact.payload_id, fact.kind): fact for fact in engine_input.payload_facts}
    results = []
    for payload_id, kind in domains:
        target = AuditTarget("payload", payload_id)
        if selected_kind is not None and kind != selected_kind:
            results.append(_result(engine_input, rule_id, target, applicable=False))
            continue
        results.append(_result(engine_input, rule_id, target, evaluator(payload_id, kind, facts.get((payload_id, kind)))))
    return tuple(results)


def evaluate_payload_references(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Match chunk refs to exact occurrence triples and explicit registration facts."""

    if not engine_input.snapshot.chunks:
        return (
            _result(
                engine_input,
                "payload_references",
                empty_domain_target(_rule("payload_references")),
                applicable=False,
            ),
        )

    occurrence_triples = {
        (item.payload_id, item.kind, item.occurrence_ordinal)
        for item in engine_input.snapshot.payload_occurrences
    }
    registered = {
        (fact.payload_id, fact.kind)
        for fact in engine_input.payload_facts
        if fact.registered
    }
    results = []
    for chunk in sorted(engine_input.snapshot.chunks, key=lambda item: item.chunk_id):
        defects: list[Mapping[str, Any]] = []
        refs = safe_json_to_dict(chunk.payload_refs)
        if not isinstance(refs, list):
            refs = []
            defects.append({"code": "invalid_payload_ref_collection"})
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {
                "payload_id",
                "kind",
                "occurrence_ordinal",
            }:
                defects.append({"code": "invalid_payload_ref"})
                continue
            payload_id = ref["payload_id"]
            kind = ref["kind"]
            ordinal = ref["occurrence_ordinal"]
            if (
                not isinstance(payload_id, str)
                or not payload_id
                or len(payload_id) > _MAX_REFERENCE_STRING
                or not isinstance(kind, str)
                or not kind
                or len(kind) > _MAX_REFERENCE_STRING
                or kind not in {"table", "image"}
                or not isinstance(ordinal, int)
                or isinstance(ordinal, bool)
                or ordinal < 0
            ):
                defects.append({"code": "invalid_payload_ref"})
                continue
            triple = (payload_id, kind, ordinal)
            identity = {
                "payload_id": payload_id,
                "kind": kind,
                "occurrence_ordinal": ordinal,
            }
            if triple not in occurrence_triples:
                defects.append({"code": "unresolved_payload_ref", **identity})
            if triple[:2] not in registered:
                defects.append({"code": "unregistered_payload_ref", **identity})
        results.append(
            _result(
                engine_input,
                "payload_references",
                AuditTarget("chunk", chunk.chunk_id),
                defects,
            )
        )
    return tuple(results)


def evaluate_payload_occurrences(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Require kind agreement and a unique zero-based contiguous ordinal sequence."""

    grouped = defaultdict(list)
    for item in engine_input.snapshot.payload_occurrences:
        grouped[(item.payload_id, item.kind)].append(item.occurrence_ordinal)

    def evaluate(payload_id: str, kind: str, fact: PayloadResolutionFact | None):
        ordinals = sorted(grouped[(payload_id, kind)])
        defects: list[Mapping[str, Any]] = []
        if ordinals != list(range(len(ordinals))):
            defects.append({"code": "occurrence_ordinal_gap", "actual": ordinals})
        if fact is None:
            defects.append({"code": "missing_payload_registration"})
        elif fact.occurrence_count != len(ordinals):
            defects.append(
                {
                    "code": "occurrence_count_mismatch",
                    "actual": len(ordinals),
                    "expected": fact.occurrence_count,
                }
            )
        return defects

    return _evaluate_payloads(engine_input, "payload_occurrences", evaluate)


def evaluate_payload_resolution(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Require explicit registration and an explicit kind-compatible resolved object."""

    def evaluate(_payload_id: str, _kind: str, fact: PayloadResolutionFact | None):
        if fact is None:
            return [{"code": "missing_payload_resolution_fact"}]
        defects: list[Mapping[str, Any]] = []
        if not fact.registered:
            defects.append({"code": "payload_not_registered"})
        if fact.physical is None or not fact.physical.resolved:
            defects.append({"code": "payload_not_resolved"})
        return defects

    return _evaluate_payloads(engine_input, "payload_resolution", evaluate)


def _missing_fields(values: Mapping[str, Any], required: tuple[str, ...]) -> list[str]:
    return sorted(key for key in required if values.get(key) in (None, "", [], {}))


def _mismatched_fields(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
    fields: tuple[str, ...],
) -> list[str]:
    return sorted(key for key in fields if actual.get(key) != expected.get(key))


def _bounded_text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= _MAX_REFERENCE_STRING


def _bounded_count(value: Any, *, positive: bool = False) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= (1 if positive else 0)
    )


def _valid_columns(value: Any) -> bool:
    return isinstance(value, list) and all(
        isinstance(column, dict)
        and _bounded_text(column.get("name"))
        and _bounded_text(column.get("type"))
        for column in value
    )


def _valid_location_value(value: Any, *, depth: int = 0) -> bool:
    if isinstance(value, str):
        return _bounded_text(value)
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, int):
        return value >= 0
    if isinstance(value, float):
        return isfinite(value)
    if isinstance(value, list):
        return 0 < len(value) <= _MAX_LOCATION_ITEMS and all(
            _valid_location_value(item, depth=depth + 1) for item in value
        )
    if isinstance(value, Mapping):
        return (
            depth < 3
            and 0 < len(value) <= _MAX_LOCATION_ITEMS
            and all(_bounded_text(key) for key in value)
            and all(
                _valid_location_value(item, depth=depth + 1)
                for item in value.values()
            )
        )
    return False


def _valid_persisted_xlsx_location(value: Mapping[str, Any]) -> bool:
    sheet = value.get("sheet")
    cell_range = value.get("range")
    return (
        isinstance(value.get("workbook_checksum"), str)
        and _SHA256.fullmatch(value["workbook_checksum"]) is not None
        and isinstance(sheet, Mapping)
        and _bounded_text(sheet.get("name"))
        and _bounded_count(sheet.get("index"), positive=True)
        and isinstance(cell_range, Mapping)
        and _bounded_text(cell_range.get("a1_range"))
    )


def _valid_candidate_xlsx_location(value: Mapping[str, Any]) -> bool:
    cell_range = value.get("range")
    return (
        isinstance(value.get("workbook_checksum"), str)
        and _SHA256.fullmatch(value["workbook_checksum"]) is not None
        and _bounded_text(value.get("sheet_name"))
        and _bounded_count(value.get("sheet_index"), positive=True)
        and _bounded_count(value.get("header_row"), positive=True)
        and isinstance(cell_range, Mapping)
        and _bounded_text(cell_range.get("a1_range"))
        and all(
            _bounded_count(cell_range.get(field), positive=True)
            for field in ("min_row", "max_row", "min_column", "max_column")
        )
    )


def _valid_xlsx_location(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    if "sheet" in value:
        return _valid_persisted_xlsx_location(value)
    return _valid_candidate_xlsx_location(value)


def _valid_markdown_location(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    line_start = value.get("line_start")
    line_end = value.get("line_end")
    return (
        _bounded_count(value.get("table_index"), positive=True)
        and _bounded_count(line_start, positive=True)
        and _bounded_count(line_end, positive=True)
        and line_start <= line_end
    )


def _valid_source_location(value: Any, *, table: bool = False) -> bool:
    if not isinstance(value, Mapping) or not _valid_location_value(value):
        return False
    if not table:
        return True
    if "xlsx" in value:
        return _valid_xlsx_location(value["xlsx"])
    if "markdown" in value:
        return _valid_markdown_location(value["markdown"])
    if "sheet" in value or "range" in value:
        return _bounded_text(value.get("sheet")) and _bounded_text(value.get("range"))
    return True


def _valid_persisted_table_coordinate(value: Any) -> bool:
    return _bounded_text(value) or (
        isinstance(value, Mapping) and _valid_location_value(value)
    )


def _invalid_table_fields(*projections: Mapping[str, Any]) -> list[str]:
    invalid = set()
    for values in projections:
        columns = values.get("columns")
        if not _valid_columns(columns):
            invalid.add("columns")
        if not _bounded_count(values.get("row_count")):
            invalid.add("row_count")
        if not _bounded_count(values.get("column_count")):
            invalid.add("column_count")
        elif isinstance(columns, list) and values["column_count"] != len(columns):
            invalid.add("column_count")
        for field in ("source_kind", "source_checksum"):
            if not _bounded_text(values.get(field)):
                invalid.add(field)
        checksum = values.get("source_checksum")
        if isinstance(checksum, str) and _SHA256.fullmatch(checksum) is None:
            invalid.add("source_checksum")
        if not _valid_source_location(values.get("source_location"), table=True):
            invalid.add("source_location")
        for field in ("sheet", "range"):
            if field in values and not _valid_persisted_table_coordinate(values[field]):
                invalid.add(field)
    return sorted(invalid)


def _invalid_image_fields(*projections: Mapping[str, Any]) -> list[str]:
    invalid = set()
    for values in projections:
        for field in ("content_type", "extension", "source_kind", "source_checksum"):
            if not _bounded_text(values.get(field)):
                invalid.add(field)
        if not _bounded_count(values.get("byte_size")):
            invalid.add("byte_size")
        for field in ("width", "height"):
            if not _bounded_count(values.get(field), positive=True):
                invalid.add(field)
        for field in ("checksum_sha256", "source_checksum"):
            checksum = values.get(field)
            if not isinstance(checksum, str) or _SHA256.fullmatch(checksum) is None:
                invalid.add(field)
        if not _valid_source_location(values.get("source_location")):
            invalid.add("source_location")
    return sorted(invalid)


def evaluate_table_metadata(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    required = (
        "columns",
        "row_count",
        "column_count",
        "source_kind",
        "source_checksum",
        "source_location",
    )

    def evaluate(_payload_id: str, _kind: str, fact: PayloadResolutionFact | None):
        metadata = safe_json_to_dict(fact.metadata) if fact else {}
        registration = safe_json_to_dict(fact.registration_identity) if fact else {}
        missing = _missing_fields(metadata, required)
        defects = []
        if missing:
            defects.append({"code": "missing_table_metadata", "fields": missing})
        invalid = _invalid_table_fields(metadata, registration)
        if invalid:
            defects.append({"code": "invalid_table_metadata", "fields": invalid})
        if fact:
            mismatched = _mismatched_fields(metadata, registration, required)
            if mismatched:
                defects.append(
                    {"code": "table_metadata_mismatch", "fields": mismatched}
                )
        return defects

    return _evaluate_payloads(engine_input, "table_metadata", evaluate, selected_kind="table")


def evaluate_table_summary(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    required = ("profile_signature", "row_count", "column_count")

    def evaluate(_payload_id: str, _kind: str, fact: PayloadResolutionFact | None):
        summary = safe_json_to_dict(fact.summary) if fact else {}
        missing = _missing_fields(summary, required)
        defects = []
        if missing:
            defects.append({"code": "missing_table_summary", "fields": missing})
        if fact:
            registration = safe_json_to_dict(fact.registration_identity)
            if any(summary.get(key) != registration.get(key) for key in required):
                defects.append({"code": "table_summary_mismatch"})
        return defects

    return _evaluate_payloads(engine_input, "table_summary", evaluate, selected_kind="table")


def evaluate_table_storage_identity(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    def evaluate(_payload_id: str, _kind: str, fact: PayloadResolutionFact | None):
        if fact is None or fact.physical is None or not fact.physical.resolved:
            return [{"code": "table_storage_unresolved"}]
        registration = safe_json_to_dict(fact.registration_identity)
        physical = safe_json_to_dict(fact.physical.identity)
        expected = {key: registration.get(key) for key in ("schema_name", "table_name")}
        return [] if physical == expected and expected["schema_name"] == "lore_toast" else [{"code": "table_storage_identity_mismatch"}]

    return _evaluate_payloads(engine_input, "table_storage_identity", evaluate, selected_kind="table")


def evaluate_image_metadata(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    required = (
        "content_type",
        "extension",
        "byte_size",
        "checksum_sha256",
        "source_kind",
        "source_checksum",
        "source_location",
        "width",
        "height",
    )

    def evaluate(_payload_id: str, _kind: str, fact: PayloadResolutionFact | None):
        metadata = safe_json_to_dict(fact.metadata) if fact else {}
        registration = safe_json_to_dict(fact.registration_identity) if fact else {}
        missing = _missing_fields(metadata, required)
        defects = []
        if missing:
            defects.append({"code": "missing_image_metadata", "fields": missing})
        invalid = _invalid_image_fields(metadata, registration)
        if invalid:
            defects.append({"code": "invalid_image_metadata", "fields": invalid})
        if fact:
            mismatched = _mismatched_fields(metadata, registration, required)
            if mismatched:
                defects.append(
                    {"code": "image_metadata_mismatch", "fields": mismatched}
                )
        return defects

    return _evaluate_payloads(engine_input, "image_metadata", evaluate, selected_kind="image")


def evaluate_image_storage_identity(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    def evaluate(_payload_id: str, _kind: str, fact: PayloadResolutionFact | None):
        if fact is None or fact.physical is None or not fact.physical.resolved:
            return [{"code": "image_storage_unresolved"}]
        registration = safe_json_to_dict(fact.registration_identity)
        physical = fact.physical
        identity = safe_json_to_dict(physical.identity)
        mismatched = (
            identity != {key: registration.get(key) for key in ("bucket", "object_key")}
            or physical.checksum_sha256 != registration.get("checksum_sha256")
            or physical.byte_size != registration.get("byte_size")
            or physical.content_type != registration.get("content_type")
        )
        return [{"code": "image_storage_identity_mismatch"}] if mismatched else []

    return _evaluate_payloads(engine_input, "image_storage_identity", evaluate, selected_kind="image")


__all__ = [
    "evaluate_image_metadata",
    "evaluate_image_storage_identity",
    "evaluate_payload_occurrences",
    "evaluate_payload_references",
    "evaluate_payload_resolution",
    "evaluate_table_metadata",
    "evaluate_table_storage_identity",
    "evaluate_table_summary",
]
