"""Pure audit/v1 evaluators for persisted chunk facts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any

from lore_core_domain.text import normalize_text
from lore_core_domain.redaction import redact_value

from ..contracts import (
    AuditChunk,
    AuditTarget,
    DiagnosticOrigin,
    RuleOutcome,
    RuleResult,
)
from ..engine_contracts import AuditEngineInput
from ..ruleset import AUDIT_V1_RULESET, empty_domain_target
from ..validation import safe_json_to_dict

_TEXT_LIMITS = {
    "display_text": 12_000,
    "vector_text": 8_000,
    "fulltext": 16_000,
}
_ALLOWED_TYPES = {
    "document": frozenset({"heading", "table_payload", "text"}),
    "docx": frozenset({"heading", "table_payload", "text"}),
    "markdown": frozenset({"heading", "paragraph", "table", "table_payload", "text"}),
    "workbook": frozenset({"table", "table_payload", "text"}),
    "transcript": frozenset({"transcript_topic"}),
    "presentation": frozenset({"presentation"}),
    "pdf": frozenset({"document_like", "presentation_like", "scanned_or_unsupported"}),
}
_NUMERIC_COORDINATES = (
    "page",
    "slide",
    "page_start",
    "page_end",
    "slide_start",
    "slide_end",
    "start_ms",
    "end_ms",
)
_COORDINATE_RANGES = (
    ("page_start", "page_end"),
    ("slide_start", "slide_end"),
    ("start_ms", "end_ms"),
)


def _declared_rule(rule_id: str):
    return next(rule for rule in AUDIT_V1_RULESET.rules if rule.rule_id == rule_id)


def _result(
    engine_input: AuditEngineInput,
    chunk: AuditChunk,
    rule_id: str,
    defects: list[Mapping[str, Any]],
    *,
    details: Mapping[str, Any] | None = None,
) -> RuleResult:
    target = AuditTarget(kind="chunk", target_id=chunk.chunk_id)
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
        message=f"Audit rule {rule_id} found inconsistent persisted chunk facts",
        details=finding_details,
    )


def _evaluate_chunks(
    engine_input: AuditEngineInput,
    evaluator: Callable[[AuditChunk], tuple[list[Mapping[str, Any]], Mapping[str, Any] | None]],
    rule_id: str,
) -> tuple[RuleResult, ...]:
    if not engine_input.snapshot.chunks:
        return (
            RuleResult(
                engine_input.ruleset_version,
                rule_id,
                RuleOutcome.NOT_APPLICABLE,
                empty_domain_target(_declared_rule(rule_id)),
            ),
        )
    results = []
    for chunk in sorted(engine_input.snapshot.chunks, key=lambda item: item.chunk_id):
        defects, details = evaluator(chunk)
        results.append(_result(engine_input, chunk, rule_id, defects, details=details))
    return tuple(results)


def evaluate_chunk_texts(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Check the three persisted views against exact Splitter character limits."""

    def evaluate(chunk: AuditChunk):
        defects: list[Mapping[str, Any]] = []
        excerpt = None
        for name, limit in _TEXT_LIMITS.items():
            text = getattr(chunk, name)
            if not text.strip():
                defects.append({"code": f"empty_{name}", "actual_length": len(text)})
            elif len(text) > limit:
                defects.append(
                    {
                        "code": f"budget_{name}",
                        "actual_length": len(text),
                        "limit": limit,
                    }
                )
                if excerpt is None:
                    excerpt = redact_value(text[:80])
        details = {"excerpt": excerpt} if excerpt is not None else None
        return defects, details

    return _evaluate_chunks(engine_input, evaluate, "chunk_texts")


def evaluate_chunk_type(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Check the versioned pipeline/chunk-type matrix and required coordinate family."""

    def evaluate(chunk: AuditChunk):
        defects: list[Mapping[str, Any]] = []
        allowed = _ALLOWED_TYPES.get(chunk.pipeline_type)
        if allowed is None:
            defects.append(
                {"code": "unsupported_pipeline_type", "actual": chunk.pipeline_type}
            )
        elif chunk.chunk_type not in allowed:
            defects.append({"code": "unsupported_chunk_type", "actual": chunk.chunk_type})
        coordinates = safe_json_to_dict(chunk.coordinates)
        compatible = True
        if chunk.pipeline_type == "transcript":
            compatible = all(key in coordinates for key in ("start_ms", "end_ms"))
        elif chunk.pipeline_type == "workbook" and chunk.chunk_type in {"table", "table_payload"}:
            compatible = all(coordinates.get(key) for key in ("sheet", "range"))
        elif chunk.pipeline_type == "presentation":
            compatible = any(
                key in coordinates for key in ("slide", "slide_start", "slide_end")
            )
        if not compatible:
            defects.append({"code": "incompatible_chunk_coordinates"})
        return defects, None

    return _evaluate_chunks(engine_input, evaluate, "chunk_type")


def evaluate_chunk_ordinal(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Compare each persisted ordinal with its expected position in the canonical sequence."""

    expected_by_id = {
        chunk.chunk_id: expected
        for expected, chunk in enumerate(engine_input.snapshot.chunks)
    }

    def evaluate(chunk: AuditChunk):
        expected = expected_by_id[chunk.chunk_id]
        defects = []
        if chunk.ordinal != expected:
            defects.append(
                {"code": "invalid_ordinal", "actual": chunk.ordinal, "expected": expected}
            )
        return defects, None

    return _evaluate_chunks(engine_input, evaluate, "chunk_ordinal")


def evaluate_chunk_coordinates(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Check known numeric coordinates for exact types, non-negativity, and ordering."""

    def evaluate(chunk: AuditChunk):
        coordinates = safe_json_to_dict(chunk.coordinates)
        defects: list[Mapping[str, Any]] = []
        invalid_keys: set[str] = set()
        for key in _NUMERIC_COORDINATES:
            if key not in coordinates or coordinates[key] is None:
                continue
            value = coordinates[key]
            if not isinstance(value, int) or isinstance(value, bool):
                defects.append(
                    {"code": "invalid_coordinate_type", "coordinate": key}
                )
                invalid_keys.add(key)
            elif value < 0:
                defects.append(
                    {"code": "negative_coordinate", "coordinate": key, "actual": value}
                )
        for start_key, end_key in _COORDINATE_RANGES:
            if (
                start_key in coordinates
                and end_key in coordinates
                and start_key not in invalid_keys
                and end_key not in invalid_keys
                and isinstance(coordinates[start_key], int)
                and isinstance(coordinates[end_key], int)
                and coordinates[end_key] < coordinates[start_key]
            ):
                defects.append(
                    {
                        "code": "inverted_coordinate_range",
                        "start_coordinate": start_key,
                        "start": coordinates[start_key],
                        "end_coordinate": end_key,
                        "end": coordinates[end_key],
                    }
                )
        return defects, None

    return _evaluate_chunks(engine_input, evaluate, "chunk_coordinates")


def evaluate_vector_hard_limit(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Compare only ready-rendered token facts; never tokenize or load defaults."""

    facts = {fact.chunk_id: fact for fact in engine_input.token_facts}
    chunks = engine_input.snapshot.chunks
    if chunks and not facts:
        rule = _declared_rule("vector_hard_limit")
        target = empty_domain_target(rule)
        return (
            RuleResult(
                ruleset_version=engine_input.ruleset_version,
                rule_id=rule.rule_id,
                outcome=RuleOutcome.FINDING,
                target=target,
                severity=rule.severity,
                diagnostic_key=AUDIT_V1_RULESET.diagnostic_key(target, rule.rule_id),
                origin=DiagnosticOrigin.AUDIT_RULE,
                message="Audit rule vector_hard_limit lacks persisted token facts",
                details={
                    "ruleset_version": engine_input.ruleset_version,
                    "defects": [{"code": "missing_token_fact"}],
                    "chunk_count": len(chunks),
                },
            ),
        )

    def evaluate(chunk: AuditChunk):
        fact = facts.get(chunk.chunk_id)
        if fact is None:
            return [{"code": "missing_token_fact"}], None
        details = {
            "counter_id": fact.tokenizer_id,
            "observed_count": fact.vector_token_count,
            "hard_limit": fact.vector_hard_limit,
        }
        defects = []
        if fact.vector_token_count > fact.vector_hard_limit:
            defects.append(
                {
                    "code": "vector_token_hard_limit",
                    "actual": fact.vector_token_count,
                    "limit": fact.vector_hard_limit,
                }
            )
        return defects, details

    return _evaluate_chunks(engine_input, evaluate, "vector_hard_limit")


def evaluate_persisted_hashes(engine_input: AuditEngineInput) -> tuple[RuleResult, ...]:
    """Recompute vector/fulltext SHA-256 using the exact Splitter normalization rule."""

    def evaluate(chunk: AuditChunk):
        expected = {
            "vector_text_hash": hashlib.sha256(
                normalize_text(chunk.vector_text).encode()
            ).hexdigest(),
            "fulltext_hash": hashlib.sha256(normalize_text(chunk.fulltext).encode()).hexdigest(),
        }
        actual = {
            "vector_text_hash": chunk.vector_text_hash,
            "fulltext_hash": chunk.fulltext_hash,
        }
        defects: list[Mapping[str, Any]] = []
        for name in ("vector_text_hash", "fulltext_hash"):
            if actual[name] != expected[name]:
                defects.append(
                    {
                        "code": f"{name}_mismatch",
                        "actual": actual[name],
                        "expected": expected[name],
                    }
                )
        return defects, None

    return _evaluate_chunks(engine_input, evaluate, "persisted_hashes")


__all__ = [
    "evaluate_chunk_coordinates",
    "evaluate_chunk_ordinal",
    "evaluate_chunk_texts",
    "evaluate_chunk_type",
    "evaluate_persisted_hashes",
    "evaluate_vector_hard_limit",
]
