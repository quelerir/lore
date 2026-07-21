from __future__ import annotations

import ast
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lore_audit import engine as engine_module
from lore_audit.contracts import (
    AUDIT_COMPLETED,
    AUDIT_FAILED,
    AuditChunk,
    AuditRun,
    AuditSnapshot,
    AuditTarget,
    LifecycleOutcome,
    ProcessingDiagnostic,
    RuleOutcome,
    RuleResult,
    Severity,
)
from lore_audit.engine import run_audit
from lore_audit.engine_contracts import AuditEngineInput, ChunkTokenFact
from lore_audit.ruleset import AUDIT_V1_RULESET, EMPTY_DOMAIN_TARGET_ID
from lore_audit.validation import safe_json_to_dict
from lore_core_domain.text import normalize_text
from lore_core_domain.run_status import RunStatus

NOW = datetime(2026, 7, 16, 9, 0, tzinfo=UTC)


def text_hash(value: str) -> str:
    return hashlib.sha256(normalize_text(value).encode()).hexdigest()


def audit_chunk(chunk_id="chunk-1", ordinal=0, **overrides):
    vector_text = overrides.pop("vector_text", "vector text")
    fulltext = overrides.pop("fulltext", "full text")
    values = {
        "chunk_id": chunk_id,
        "run_id": "run-1",
        "ordinal": ordinal,
        "pipeline_type": "document",
        "chunk_type": "text",
        "vector_text": vector_text,
        "fulltext": fulltext,
        "display_text": "display text",
        "coordinates": {"page": ordinal + 1},
        "metadata": {},
        "payload_refs": (),
        "content_signature": "c" * 64,
        "vector_text_hash": text_hash(vector_text),
        "fulltext_hash": text_hash(fulltext),
    }
    values.update(overrides)
    return AuditChunk(**values)


def processing_diagnostic(**overrides):
    values = {
        "diagnostic_id": "diag-1",
        "run_id": "run-1",
        "chunk_id": None,
        "payload_id": None,
        "level": "warning",
        "code": "SOURCE_WARNING",
        "message": "bounded diagnostic",
        "stage": "source",
        "details": {},
    }
    values.update(overrides)
    return ProcessingDiagnostic(**values)


def engine_input(
    *,
    status=RunStatus.SUCCESS,
    chunks=(),
    diagnostics=(),
    warning_count=0,
    error_count=0,
):
    run = AuditRun(
        run_id="run-1",
        logical_file_key="drive.files.1",
        status=status,
        source_content_hash="a" * 64,
        config_hash="b" * 64,
        operator_version="1.3.0",
        chunk_schema_version="chunk/v1",
        claimed_at=NOW,
        finished_at=NOW + timedelta(seconds=1),
        chunk_count=len(chunks),
        payload_count=0,
        warning_count=warning_count,
        error_count=error_count,
    )
    return AuditEngineInput(
        snapshot=AuditSnapshot(
            ruleset_version="audit/v1",
            run=run,
            chunks=chunks,
            payload_occurrences=(),
            processing_diagnostics=diagnostics,
        ),
        ruleset_version="audit/v1",
        token_facts=tuple(
            ChunkTokenFact(chunk.chunk_id, "fixture", 2, 100) for chunk in chunks
        ),
        payload_facts=(),
    )


def expected_counts(*, passed, finding=0, suppressed=0, not_applicable):
    return {
        "pass": passed,
        "finding": finding,
        "suppressed": suppressed,
        "not_applicable": not_applicable,
    }


def test_zero_chunks_and_payloads_emits_exact_22_result_matrix():
    result = run_audit(engine_input())

    assert len(result.results) == 22
    assert [item.rule_id for item in result.results] == [
        rule.rule_id for rule in AUDIT_V1_RULESET.rules
    ]
    assert [item.outcome for item in result.results[:3]] == [RuleOutcome.PASS] * 3
    for item, rule in zip(result.results[3:21], AUDIT_V1_RULESET.rules[3:21], strict=True):
        assert item.target == AuditTarget(rule.target_kind, EMPTY_DOMAIN_TARGET_ID)
        assert item.outcome is RuleOutcome.NOT_APPLICABLE
        projection = item.to_dict()
        assert all(
            projection[field] is None
            for field in ("severity", "diagnostic_key", "origin", "message", "suppression")
        )
    assert result.results[-1].outcome is RuleOutcome.PASS
    assert result.lifecycle.outcome is LifecycleOutcome.COMPLETED
    assert result.lifecycle.code == AUDIT_COMPLETED
    assert result.lifecycle.checked_rule_count == 22
    assert result.lifecycle.to_dict()["outcome_counts"] == expected_counts(
        passed=4, not_applicable=18
    )
    assert result.lifecycle.to_dict()["severity_counts"] == {
        severity.value: 0 for severity in Severity
    }


def test_one_ordinary_chunk_and_zero_payloads_emits_locked_matrix():
    result = run_audit(engine_input(chunks=(audit_chunk(),)))

    assert len(result.results) == 22
    assert result.lifecycle.to_dict()["outcome_counts"] == expected_counts(
        passed=11, not_applicable=11
    )
    payload_sentinels = result.results[10:17]
    assert len(payload_sentinels) == 7
    assert all(item.target.target_id == EMPTY_DOMAIN_TARGET_ID for item in payload_sentinels)
    transcript_results = result.results[17:21]
    assert all(item.target == AuditTarget("chunk", "chunk-1") for item in transcript_results)
    assert all(item.outcome is RuleOutcome.NOT_APPLICABLE for item in transcript_results)
    assert not [item for item in result.results if item.outcome is RuleOutcome.FINDING]


def test_all_missing_token_facts_complete_with_one_aggregate_finding():
    value = engine_input(
        chunks=(audit_chunk("chunk-1", 0), audit_chunk("chunk-2", 1)),
    )
    value = AuditEngineInput(
        snapshot=value.snapshot,
        ruleset_version=value.ruleset_version,
        token_facts=(),
        payload_facts=value.payload_facts,
    )

    result = run_audit(value)
    vector_results = [
        item for item in result.results if item.rule_id == "vector_hard_limit"
    ]

    assert result.lifecycle.outcome is LifecycleOutcome.COMPLETED
    assert len(vector_results) == 1
    assert vector_results[0].outcome is RuleOutcome.FINDING
    assert vector_results[0].target.target_id == EMPTY_DOMAIN_TARGET_ID


@pytest.mark.parametrize(
    "status,level",
    (
        (RunStatus.FAILED, "error"),
        (RunStatus.SKIPPED, "warning"),
        (RunStatus.STALE, "error"),
    ),
)
def test_non_success_statuses_execute_only_four_result_contract_rules(status, level):
    result = run_audit(
        engine_input(
            status=status,
            diagnostics=(processing_diagnostic(level=level),),
            warning_count=int(level == "warning"),
            error_count=int(level == "error"),
        )
    )

    assert [item.rule_id for item in result.results] == [
        "terminal_status",
        "result_presence",
        "processing_diagnostics",
        "lifecycle_contract",
    ]
    assert result.lifecycle.checked_rule_count == 4
    assert all(item.outcome is RuleOutcome.PASS for item in result.results)


def test_results_follow_catalog_then_target_id_order_and_repeat_as_identical_bytes():
    value = engine_input(
        chunks=(audit_chunk("chunk-z", 0), audit_chunk("chunk-a", 1)),
    )

    first = run_audit(value)
    second = run_audit(value)
    chunk_text_targets = [
        item.target.target_id for item in first.results if item.rule_id == "chunk_texts"
    ]

    assert chunk_text_targets == ["chunk-a", "chunk-z"]
    assert json.dumps(first.to_dict(), sort_keys=True, separators=(",", ":")) == json.dumps(
        second.to_dict(), sort_keys=True, separators=(",", ":")
    )


def test_engine_applies_exact_suppression_only_to_raw_findings():
    diagnostic = processing_diagnostic(
        chunk_id="chunk-1",
        code="empty_vector_text",
    )
    value = engine_input(
        chunks=(audit_chunk(vector_text=""),),
        diagnostics=(diagnostic,),
        warning_count=1,
    )

    result = run_audit(value)
    classified = next(item for item in result.results if item.rule_id == "chunk_texts")

    assert classified.outcome is RuleOutcome.SUPPRESSED
    assert classified.suppression.processing_diagnostic_ids == ("diag-1",)
    assert result.lifecycle.to_dict()["outcome_counts"]["suppressed"] == 1


@pytest.mark.parametrize(
    "malformed_ref",
    (
        {"payload_id": ["bad"], "kind": "table", "occurrence_ordinal": 0},
        {"payload_id": {"bad": "id"}, "kind": "table", "occurrence_ordinal": 0},
        {"payload_id": "payload-1", "kind": ["table"], "occurrence_ordinal": 0},
        {"payload_id": "payload-1", "kind": {"value": "table"}, "occurrence_ordinal": 0},
        {"payload_id": "payload-1", "kind": 1, "occurrence_ordinal": 0},
        {"payload_id": "payload-1", "kind": True, "occurrence_ordinal": 0},
        {"payload_id": "payload-1", "kind": "", "occurrence_ordinal": 0},
        {"payload_id": "payload-1", "kind": "x" * 257, "occurrence_ordinal": 0},
        {"payload_id": "payload-1", "kind": "table", "occurrence_ordinal": True},
        {"payload_id": "payload-1", "kind": "table", "occurrence_ordinal": -1},
        {"payload_id": "x" * 257, "kind": "table", "occurrence_ordinal": 0},
    ),
)
def test_malformed_payload_refs_become_bounded_findings(malformed_ref):
    value = engine_input(chunks=(audit_chunk(payload_refs=(malformed_ref,)),))

    result = run_audit(value)
    payload_result = next(
        item for item in result.results if item.rule_id == "payload_references"
    )
    defect_details = safe_json_to_dict(payload_result.details)

    assert result.lifecycle.outcome is LifecycleOutcome.COMPLETED
    assert payload_result.outcome is RuleOutcome.FINDING
    assert defect_details["defects"] == [{"code": "invalid_payload_ref"}]
    assert len(json.dumps(payload_result.to_dict())) < 2048


def pass_result(rule_id="terminal_status", kind="run", target_id="run-1"):
    return RuleResult(
        ruleset_version="audit/v1",
        rule_id=rule_id,
        outcome=RuleOutcome.PASS,
        target=AuditTarget(kind, target_id),
    )


def test_duplicate_evaluator_output_fails_closed_and_discards_partial_results(monkeypatch):
    registry = dict(engine_module._EVALUATORS)
    registry["chunk_texts"] = lambda _: (
        pass_result("chunk_texts", "chunk", "chunk-1"),
        pass_result("chunk_texts", "chunk", "chunk-1"),
    )
    monkeypatch.setattr(engine_module, "_EVALUATORS", registry)

    result = run_audit(engine_input(chunks=(audit_chunk(),)))

    assert result.results == ()
    assert result.lifecycle.outcome is LifecycleOutcome.FAILED
    assert result.lifecycle.code == AUDIT_FAILED


@pytest.mark.parametrize(
    ("chunks", "target_ids"),
    (
        ((audit_chunk("chunk-1", 0), audit_chunk("chunk-2", 1)), ("chunk-1",)),
        ((audit_chunk(),), ("chunk-1", "chunk-ghost")),
        ((audit_chunk(),), ("chunk-1", EMPTY_DOMAIN_TARGET_ID)),
        ((), ()),
    ),
)
def test_evaluator_target_domain_mismatch_fails_closed(monkeypatch, chunks, target_ids):
    registry = dict(engine_module._EVALUATORS)
    registry["chunk_texts"] = lambda _: tuple(
        pass_result("chunk_texts", "chunk", target_id) for target_id in target_ids
    )
    monkeypatch.setattr(engine_module, "_EVALUATORS", registry)

    result = run_audit(engine_input(chunks=chunks))

    assert result.results == ()
    assert result.lifecycle.outcome is LifecycleOutcome.FAILED
    assert result.lifecycle.to_dict()["diagnostic"]["details"]["failed_rule_id"] == (
        "chunk_texts"
    )


@pytest.mark.parametrize(
    "replacement",
    (
        lambda _: (pass_result("result_presence"),),
        lambda _: (pass_result("terminal_status", "chunk", "chunk-1"),),
    ),
)
def test_malformed_rule_or_target_output_fails_closed(monkeypatch, replacement):
    registry = dict(engine_module._EVALUATORS)
    registry["terminal_status"] = replacement
    monkeypatch.setattr(engine_module, "_EVALUATORS", registry)

    result = run_audit(engine_input())

    assert result.results == ()
    assert result.lifecycle.outcome is LifecycleOutcome.FAILED


def test_evaluator_exception_is_redacted_to_bounded_failure_facts(monkeypatch):
    class SecretClientFailure(RuntimeError):
        pass

    def throwing(_):
        raise SecretClientFailure("postgres://secret content connection")

    registry = dict(engine_module._EVALUATORS)
    registry["chunk_texts"] = throwing
    monkeypatch.setattr(engine_module, "_EVALUATORS", registry)

    result = run_audit(engine_input(chunks=(audit_chunk(),)))
    projection = result.lifecycle.to_dict()
    serialized = json.dumps(projection)

    assert result.results == ()
    assert projection["diagnostic"]["details"] == {
        "exception_class": "SecretClientFailure",
        "failed_rule_id": "chunk_texts",
        "ruleset_version": "audit/v1",
        "run_id": "run-1",
    }
    assert all(secret not in serialized for secret in ("postgres", "secret", "connection"))


def test_registry_parity_is_validated_on_every_invocation(monkeypatch):
    registry = dict(engine_module._EVALUATORS)
    registry.pop("chunk_texts")
    monkeypatch.setattr(engine_module, "_EVALUATORS", registry)

    result = run_audit(engine_input())

    assert result.results == ()
    assert result.lifecycle.to_dict()["diagnostic"]["details"]["failed_rule_id"] == (
        "registry_validation"
    )



def test_engine_imports_remain_inside_the_pure_audit_boundary():
    source = Path(engine_module.__file__).read_text()
    tree = ast.parse(source)
    imported_modules = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    forbidden_import_fragments = {
        "airflow.decorators",
        "airflow.hooks",
        "airflow.models",
        "airflow.operators",
        "boto3",
        "httpx",
        "openai",
        "psycopg",
        "requests",
        "socket",
        "sqlalchemy",
        "urllib",
    }

    assert not {
        imported
        for imported in imported_modules
        if any(fragment in imported for fragment in forbidden_import_fragments)
    }


def test_engine_source_has_no_runtime_persistence_or_model_behavior():
    source = Path(engine_module.__file__).read_text().casefold()
    forbidden_source = (
        "on conflict",
        "baseoperator",
        "get_current_context",
        "os.environ",
        "os.getenv",
        "repository",
        "sql execution",
        "tokenizer(",
        "requests.",
        "httpx.",
        "frontend",
        "model client",
        "ai client",
    )

    assert not [fragment for fragment in forbidden_source if fragment in source]


def test_test_01_phase_21_handoff_is_explicit_and_exclusive():
    """Phase 20 owns stable bytes/keys; Phase 21/AUOP owns operator retry and DB upsert."""

    value = engine_input(chunks=(audit_chunk(),))
    first = run_audit(value)
    second = run_audit(value)

    assert json.dumps(first.to_dict(), sort_keys=True, separators=(",", ":")) == json.dumps(
        second.to_dict(), sort_keys=True, separators=(",", ":")
    )
    assert [item.diagnostic_key for item in first.results] == [
        item.diagnostic_key for item in second.results
    ]
    assert "Phase 21/AUOP owns operator retry and DB upsert" in (
        test_test_01_phase_21_handoff_is_explicit_and_exclusive.__doc__ or ""
    )
