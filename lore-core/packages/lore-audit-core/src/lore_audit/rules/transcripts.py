"""Pure audit/v1 evaluators for persisted transcript coordinates."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from ..contracts import AuditChunk, AuditTarget, DiagnosticOrigin, RuleOutcome, RuleResult
from ..engine_contracts import AuditEngineInput
from ..ruleset import AUDIT_V1_RULESET, empty_domain_target
from ..validation import safe_json_to_dict

_MAX_DEFECTS = 8


def _rule(rule_id: str):
    return next(rule for rule in AUDIT_V1_RULESET.rules if rule.rule_id == rule_id)


def _result(
    engine_input: AuditEngineInput,
    chunk: AuditChunk | None,
    rule_id: str,
    defects: list[Mapping[str, Any]] | None = None,
    *,
    applicable: bool = True,
) -> RuleResult:
    target = (
        AuditTarget("chunk", chunk.chunk_id)
        if chunk is not None
        else empty_domain_target(_rule(rule_id))
    )
    if not applicable:
        return RuleResult(engine_input.ruleset_version, rule_id, RuleOutcome.NOT_APPLICABLE, target)
    defects = sorted(
        defects or [],
        key=lambda item: (
            str(item.get("code", "")),
            str(item.get("slot_id", "")),
            str(item.get("ordinal", "")),
        ),
    )
    if not defects:
        return RuleResult(engine_input.ruleset_version, rule_id, RuleOutcome.PASS, target)
    declared = _rule(rule_id)
    return RuleResult(
        ruleset_version=engine_input.ruleset_version,
        rule_id=rule_id,
        outcome=RuleOutcome.FINDING,
        target=target,
        severity=declared.severity,
        diagnostic_key=AUDIT_V1_RULESET.diagnostic_key(target, rule_id),
        origin=DiagnosticOrigin.AUDIT_RULE,
        message=f"Audit rule {rule_id} found inconsistent persisted transcript facts",
        details={
            "ruleset_version": engine_input.ruleset_version,
            "defects": defects[:_MAX_DEFECTS],
            "total": len(defects),
            "truncated": len(defects) > _MAX_DEFECTS,
        },
    )


def _boundaries(coordinates: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[Mapping[str, Any]]]:
    parsed = []
    defects: list[Mapping[str, Any]] = []
    values = coordinates.get("slot_boundaries", [])
    if not isinstance(values, list):
        return [], [{"code": "malformed_slot_boundary", "parser_code": "TRAN-01-NO_RELIABLE_SLOTS"}]
    for index, raw in enumerate(values):
        if not isinstance(raw, str):
            defects.append({"code": "malformed_slot_boundary", "index": index, "parser_code": "TRAN-01-NO_RELIABLE_SLOTS"})
            continue
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            defects.append({"code": "malformed_slot_boundary", "index": index, "parser_code": "TRAN-01-NO_RELIABLE_SLOTS"})
            continue
        if not isinstance(value, dict):
            defects.append({"code": "malformed_slot_boundary", "index": index, "parser_code": "TRAN-01-NO_RELIABLE_SLOTS"})
            continue
        parsed.append(value)
    return parsed, defects


def _evaluate(
    engine_input: AuditEngineInput,
    rule_id: str,
    evaluator: Callable[[Mapping[str, Any]], list[Mapping[str, Any]]],
) -> tuple[RuleResult, ...]:
    chunks = tuple(sorted(engine_input.snapshot.chunks, key=lambda item: item.chunk_id))
    if not chunks:
        return (_result(engine_input, None, rule_id, applicable=False),)
    results = []
    for chunk in chunks:
        if chunk.pipeline_type != "transcript":
            results.append(_result(engine_input, chunk, rule_id, applicable=False))
            continue
        results.append(
            _result(engine_input, chunk, rule_id, evaluator(safe_json_to_dict(chunk.coordinates)))
        )
    return tuple(results)


def evaluate_transcript_speakers(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    def evaluate(coordinates: Mapping[str, Any]):
        boundaries, defects = _boundaries(coordinates)
        speaker = coordinates.get("speaker")
        speakers = coordinates.get("speakers")
        valid_speakers = (
            isinstance(speakers, list)
            and bool(speakers)
            and all(isinstance(item, str) and item.strip() for item in speakers)
        )
        if not valid_speakers or (
            speaker is not None
            and (
                not isinstance(speaker, str)
                or not speaker.strip()
                or speaker not in speakers
            )
        ):
            defects.append(
                {
                    "code": "missing_transcript_speaker",
                    "parser_code": "TRAN-01-NO_RELIABLE_SLOTS",
                }
            )
        boundary_speakers = {item.get("speaker") for item in boundaries}
        if boundaries and (
            None in boundary_speakers
            or not valid_speakers
            or not boundary_speakers.issubset(set(speakers))
        ):
            defects.append({"code": "inconsistent_transcript_speakers"})
        return defects

    return _evaluate(engine_input, "transcript_speakers", evaluate)


def _valid_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def evaluate_transcript_intervals(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    def evaluate(coordinates: Mapping[str, Any]):
        boundaries, defects = _boundaries(coordinates)
        start = coordinates.get("start_ms")
        end = coordinates.get("end_ms")
        if not _valid_int(start) or not _valid_int(end) or start < 0 or end < start:
            defects.append({"code": "invalid_transcript_interval", "parser_code": "TRAN-01-INVALID_COORDINATE"})
            return defects
        for item in boundaries:
            slot_start, slot_end = item.get("start_ms"), item.get("end_ms")
            if not _valid_int(slot_start) or not _valid_int(slot_end) or slot_start < start or slot_end < slot_start or slot_end > end:
                defects.append({"code": "invalid_slot_interval", "slot_id": item.get("slot_id"), "parser_code": "TRAN-01-INVALID_COORDINATE"})
        return defects

    return _evaluate(engine_input, "transcript_intervals", evaluate)


def evaluate_transcript_ordering(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    def evaluate(coordinates: Mapping[str, Any]):
        boundaries, defects = _boundaries(coordinates)
        ids = [item.get("slot_id") for item in boundaries]
        ordinals = [item.get("ordinal") for item in boundaries]
        if len(ids) != len(set(ids)):
            defects.append({"code": "duplicate_slot_id"})
        if any(not isinstance(value, str) or not value for value in ids):
            defects.append({"code": "invalid_slot_id"})
        if any(not _valid_int(value) or value < 0 for value in ordinals):
            defects.append({"code": "invalid_slot_ordinal"})
        elif ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
            defects.append({"code": "reordered_slot_ordinal"})
        starts = [item.get("start_ms") for item in boundaries]
        if all(_valid_int(value) for value in starts) and starts != sorted(starts):
            defects.append({"code": "reordered_slot_interval"})
        return defects

    return _evaluate(engine_input, "transcript_ordering", evaluate)


def evaluate_transcript_source_splits(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    def evaluate(coordinates: Mapping[str, Any]):
        boundaries, defects = _boundaries(coordinates)
        slot_ids = [item.get("slot_id") for item in boundaries]
        lineage = coordinates.get("continuation_lineage")
        internal = coordinates.get("internal_boundaries")
        lineage_entries: list[tuple[str, int]] = []
        if isinstance(lineage, list):
            for value in lineage:
                if not isinstance(value, str):
                    lineage_entries = []
                    break
                slot_id, marker, index = value.rpartition(":split:")
                if marker != ":split:" or not index.isdigit():
                    lineage_entries = []
                    break
                lineage_entries.append((slot_id, int(index)))
        if not isinstance(lineage, list) or (
            lineage
            and (
                len(lineage_entries) != len(lineage)
                or len(lineage_entries) != len(set(lineage_entries))
                or any(slot_id not in slot_ids for slot_id, _index in lineage_entries)
            )
        ):
            defects.append(
                {
                    "code": "broken_continuation_lineage",
                    "parser_code": "TRAN-01-NO_RELIABLE_SLOTS",
                }
            )
        expected_internal = [
            f"{item.get('slot_id')}:{item.get('start_ms')}:{item.get('end_ms')}"
            for item in boundaries
        ]
        if not isinstance(internal, list) or internal != expected_internal:
            defects.append({"code": "noncontiguous_source_split"})
        for previous, current in zip(boundaries, boundaries[1:], strict=False):
            previous_ordinal = previous.get("ordinal")
            current_ordinal = current.get("ordinal")
            if (
                not _valid_int(previous_ordinal)
                or not _valid_int(current_ordinal)
                or current_ordinal != previous_ordinal + 1
            ):
                defects.append({"code": "noncontiguous_source_slot", "slot_id": current.get("slot_id")})
        return defects

    return _evaluate(engine_input, "transcript_source_splits", evaluate)


__all__ = [
    "evaluate_transcript_intervals",
    "evaluate_transcript_ordering",
    "evaluate_transcript_source_splits",
    "evaluate_transcript_speakers",
]
