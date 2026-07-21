from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib

import pytest

from lore_audit.contracts import (
    AuditChunk,
    AuditPayloadOccurrence,
    AuditRun,
    AuditSnapshot,
    DiagnosticOrigin,
    ProcessingDiagnostic,
    RuleOutcome,
)
from lore_audit.engine_contracts import (
    AuditEngineInput,
    ChunkTokenFact,
    EMPTY_DOMAIN_TARGET_ID,
    PayloadResolutionFact,
)
from lore_audit.rules.chunks import (
    evaluate_chunk_coordinates,
    evaluate_chunk_ordinal,
    evaluate_chunk_texts,
    evaluate_chunk_type,
    evaluate_persisted_hashes,
    evaluate_vector_hard_limit,
)
from lore_audit.rules.run import (
    evaluate_processing_diagnostics,
    evaluate_result_presence,
    evaluate_terminal_status,
)
from lore_core_domain.run_status import RunStatus
from lore_core_domain.text import normalize_text

NOW = datetime(2026, 7, 15, 12, 30, tzinfo=UTC)


def audit_run(**overrides):
    values = {
        "run_id": "run-1",
        "logical_file_key": "drive:files:42",
        "status": RunStatus.SUCCESS,
        "source_content_hash": "a" * 64,
        "config_hash": "b" * 64,
        "operator_version": "1.3.0",
        "chunk_schema_version": "chunk/v1",
        "claimed_at": NOW,
        "finished_at": NOW + timedelta(seconds=5),
        "chunk_count": 1,
        "payload_count": 0,
        "warning_count": 0,
        "error_count": 0,
    }
    values.update(overrides)
    return AuditRun(**values)


def audit_chunk(ordinal=0, **overrides):
    values = {
        "chunk_id": f"chunk-{ordinal}",
        "run_id": "run-1",
        "ordinal": ordinal,
        "pipeline_type": "document",
        "chunk_type": "text",
        "vector_text": f"vector {ordinal}\n",
        "fulltext": f"full {ordinal}\n",
        "display_text": f"display {ordinal}\n",
        "coordinates": {"page": ordinal + 1},
        "metadata": {},
        "payload_refs": (),
        "content_signature": "c" * 64,
        "vector_text_hash": "d" * 64,
        "fulltext_hash": "e" * 64,
    }
    values.update(overrides)
    return AuditChunk(**values)


def payload_occurrence(**overrides):
    values = {
        "run_id": "run-1",
        "payload_id": "payload-1",
        "occurrence_ordinal": 0,
        "kind": "table",
        "storage_identity": "postgres:lore_toast.table_1",
        "content_hash": "f" * 64,
        "coordinates": {"sheet": "Data", "range": "A1:B2"},
        "metadata": {},
    }
    values.update(overrides)
    return AuditPayloadOccurrence(**values)


def payload_fact(**overrides):
    values = {
        "payload_id": "payload-1",
        "kind": "table",
        "registered": True,
        "occurrence_count": 1,
    }
    values.update(overrides)
    return PayloadResolutionFact(**values)


def processing_diagnostic(identifier="diag-1", **overrides):
    values = {
        "diagnostic_id": identifier,
        "run_id": "run-1",
        "chunk_id": None,
        "payload_id": None,
        "level": "warning",
        "code": "SOURCE_WARNING",
        "message": "safe warning",
        "stage": "persist",
        "details": {"nested": {"b": 2, "a": 1}},
    }
    values.update(overrides)
    return ProcessingDiagnostic(**values)


def engine_input(
    *,
    run=None,
    chunks=None,
    occurrences=(),
    diagnostics=(),
    token_facts=(),
    payload_facts=(),
):
    active_run = run or audit_run()
    active_chunks = (audit_chunk(),) if chunks is None else chunks
    return AuditEngineInput(
        snapshot=AuditSnapshot(
            ruleset_version="audit/v1",
            run=active_run,
            chunks=active_chunks,
            payload_occurrences=occurrences,
            processing_diagnostics=diagnostics,
        ),
        ruleset_version="audit/v1",
        token_facts=token_facts,
        payload_facts=payload_facts,
    )


def only_result(evaluator, value):
    results = evaluator(value)
    assert len(results) == 1
    result = results[0]
    assert result.target.to_dict() == {"kind": "run", "target_id": "run-1"}
    return result


@pytest.mark.parametrize(
    "status,counts",
    [
        (RunStatus.SUCCESS, (1, 0, 0, 0)),
        (RunStatus.FAILED, (0, 0, 0, 1)),
        (RunStatus.SKIPPED, (0, 0, 1, 0)),
        (RunStatus.STALE, (0, 0, 0, 1)),
    ],
)
def test_terminal_status_passes_internally_consistent_terminal_records(status, counts):
    chunk_count, payload_count, warning_count, error_count = counts
    value = engine_input(
        run=audit_run(
            status=status,
            chunk_count=chunk_count,
            payload_count=payload_count,
            warning_count=warning_count,
            error_count=error_count,
        ),
        chunks=(audit_chunk(),) if status is RunStatus.SUCCESS else (),
    )

    result = only_result(evaluate_terminal_status, value)

    assert result.outcome is RuleOutcome.PASS
    assert result.to_dict()["details"] == {}


@pytest.mark.parametrize(
    "status,counts,defect",
    [
        (RunStatus.SUCCESS, (1, 0, 0, 1), "success_has_errors"),
        (RunStatus.FAILED, (0, 0, 0, 0), "failed_without_errors"),
        (RunStatus.SKIPPED, (0, 0, 0, 1), "skipped_has_errors"),
        (RunStatus.STALE, (0, 0, 1, 0), "stale_without_errors"),
    ],
)
def test_terminal_status_finds_contradictory_status_counts(status, counts, defect):
    chunk_count, payload_count, warning_count, error_count = counts
    value = engine_input(
        run=audit_run(
            status=status,
            chunk_count=chunk_count,
            payload_count=payload_count,
            warning_count=warning_count,
            error_count=error_count,
        ),
        chunks=(audit_chunk(),) if chunk_count else (),
    )

    result = only_result(evaluate_terminal_status, value)

    assert result.outcome is RuleOutcome.FINDING
    assert result.origin is DiagnosticOrigin.AUDIT_RULE
    assert result.diagnostic_key == "audit/v1:run:run-1:terminal_status"
    details = result.to_dict()["details"]
    assert details["ruleset_version"] == "audit/v1"
    assert details["defects"][0]["code"] == defect


def test_result_presence_requires_success_counts_to_match_canonical_identities():
    passing = engine_input(
        run=audit_run(chunk_count=1, payload_count=1),
        occurrences=(payload_occurrence(),),
        payload_facts=(payload_fact(),),
    )
    failing = engine_input(
        run=audit_run(chunk_count=2, payload_count=2),
        occurrences=(payload_occurrence(),),
        payload_facts=(payload_fact(),),
    )

    assert only_result(evaluate_result_presence, passing).outcome is RuleOutcome.PASS
    result = only_result(evaluate_result_presence, failing)
    assert result.outcome is RuleOutcome.FINDING
    details = result.to_dict()["details"]
    assert [item["code"] for item in details["defects"]] == [
        "chunk_count_mismatch",
        "payload_count_mismatch",
    ]
    assert details["actual"] == {"chunk_count": 1, "payload_count": 1}


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.SKIPPED, RunStatus.STALE])
def test_result_presence_allows_absent_non_success_results(status):
    value = engine_input(
        run=audit_run(status=status, chunk_count=0, payload_count=0, error_count=1),
        chunks=(),
    )
    assert only_result(evaluate_result_presence, value).outcome is RuleOutcome.PASS


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.SKIPPED, RunStatus.STALE])
def test_result_presence_finds_non_success_success_shaped_results(status):
    value = engine_input(
        run=audit_run(status=status, chunk_count=1, payload_count=0, error_count=1),
        chunks=(audit_chunk(),),
    )
    result = only_result(evaluate_result_presence, value)
    assert result.outcome is RuleOutcome.FINDING
    assert result.to_dict()["details"]["defects"][0]["code"] == "non_success_has_results"


def test_processing_diagnostics_passes_clean_success_and_aggregates_exact_facts():
    clean = engine_input()
    with_diagnostics = engine_input(
        run=audit_run(warning_count=3, error_count=1),
        diagnostics=(
            processing_diagnostic("diag-3", code="DUPLICATE", level="warning"),
            processing_diagnostic("diag-1", code="DUPLICATE", level="warning"),
            processing_diagnostic("diag-2", code="OTHER", level="warning"),
            processing_diagnostic("diag-4", code="FAILURE", level="error"),
        ),
    )

    assert only_result(evaluate_processing_diagnostics, clean).outcome is RuleOutcome.PASS
    result = only_result(evaluate_processing_diagnostics, with_diagnostics)
    assert result.outcome is RuleOutcome.PASS
    details = result.to_dict()["details"]
    assert details["level_counts"] == {"error": 1, "warning": 3}
    assert details["code_counts"] == {
        "DUPLICATE": 2,
        "FAILURE": 1,
        "OTHER": 1,
    }
    assert details["diagnostics"] == [
        {"code": "DUPLICATE", "diagnostic_id": "diag-1"},
        {"code": "OTHER", "diagnostic_id": "diag-2"},
        {"code": "DUPLICATE", "diagnostic_id": "diag-3"},
        {"code": "FAILURE", "diagnostic_id": "diag-4"},
    ]
    assert details["total_count"] == 4
    assert details["truncated"] is False


@pytest.mark.parametrize("status", [RunStatus.FAILED, RunStatus.SKIPPED, RunStatus.STALE])
def test_processing_diagnostics_requires_exact_explaining_fact_for_non_success(status):
    value = engine_input(
        run=audit_run(status=status, chunk_count=0, error_count=1),
        chunks=(),
    )

    result = only_result(evaluate_processing_diagnostics, value)

    assert result.outcome is RuleOutcome.FINDING
    assert (
        result.to_dict()["details"]["defects"][0]["code"]
        == "missing_processing_diagnostic"
    )


def test_processing_diagnostics_finds_count_mismatch_and_bounds_evidence():
    diagnostics = tuple(
        processing_diagnostic(
            f"diag-{index:02d}",
            code="SAME" if index % 2 else "OTHER",
            level="warning",
        )
        for index in range(20)
    )
    value = engine_input(run=audit_run(warning_count=19), diagnostics=diagnostics)

    result = only_result(evaluate_processing_diagnostics, value)

    assert result.outcome is RuleOutcome.FINDING
    details = result.to_dict()["details"]
    assert details["defects"][0]["code"] == "diagnostic_count_mismatch"
    assert len(details["diagnostics"]) == 8
    assert details["total_count"] == 20
    assert details["truncated"] is True


def test_run_evaluators_are_identical_for_caller_order_and_nested_mapping_order():
    first_diagnostics = (
        processing_diagnostic("diag-2", code="B", details={"outer": {"b": 2, "a": 1}}),
        processing_diagnostic("diag-1", code="A", details={"outer": {"a": 1, "b": 2}}),
    )
    second_diagnostics = tuple(reversed(first_diagnostics))
    first = engine_input(run=audit_run(warning_count=2), diagnostics=first_diagnostics)
    second = engine_input(run=audit_run(warning_count=2), diagnostics=second_diagnostics)

    for evaluator in (
        evaluate_terminal_status,
        evaluate_result_presence,
        evaluate_processing_diagnostics,
    ):
        assert [item.to_dict() for item in evaluator(first)] == [
            item.to_dict() for item in evaluator(second)
        ]


def hashed_chunk(ordinal=0, **overrides):
    vector_text = overrides.pop("vector_text", f"vector {ordinal}\n")
    fulltext = overrides.pop("fulltext", f"full {ordinal}\n")
    return audit_chunk(
        ordinal,
        vector_text=vector_text,
        fulltext=fulltext,
        vector_text_hash=hashlib.sha256(normalize_text(vector_text).encode()).hexdigest(),
        fulltext_hash=hashlib.sha256(normalize_text(fulltext).encode()).hexdigest(),
        **overrides,
    )


def chunk_results(evaluator, value):
    results = evaluator(value)
    assert [item.target.target_id for item in results] == sorted(
        item.target.target_id for item in results
    )
    assert all(item.target.kind == "chunk" for item in results)
    return results


@pytest.mark.parametrize(
    "chunk",
    [
        hashed_chunk(),
        hashed_chunk(
            pipeline_type="workbook",
            chunk_type="table",
            coordinates={"sheet": "Data", "range": "A1:B2"},
        ),
        hashed_chunk(
            pipeline_type="transcript",
            chunk_type="transcript_topic",
            coordinates={"start_ms": 1000, "end_ms": 2000},
        ),
    ],
)
def test_chunk_shape_rules_pass_valid_text_workbook_and_transcript_chunks(chunk):
    value = engine_input(chunks=(chunk,))
    for evaluator in (
        evaluate_chunk_texts,
        evaluate_chunk_type,
        evaluate_chunk_ordinal,
        evaluate_chunk_coordinates,
        evaluate_persisted_hashes,
    ):
        assert chunk_results(evaluator, value)[0].outcome is RuleOutcome.PASS


def test_chunk_texts_aggregates_empty_and_oversized_defects_with_bounded_excerpt():
    chunk = hashed_chunk(
        display_text="",
        vector_text="v" * 8001,
        fulltext="",
    )
    result = chunk_results(evaluate_chunk_texts, engine_input(chunks=(chunk,)))[0]

    assert result.outcome is RuleOutcome.FINDING
    details = result.to_dict()["details"]
    assert [item["code"] for item in details["defects"]] == [
        "empty_display_text",
        "budget_vector_text",
        "empty_fulltext",
    ]
    assert details["defects"][1]["actual_length"] == 8001
    assert len(details["excerpt"]) <= 80


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"pipeline_type": "unknown", "chunk_type": "text"}, "unsupported_pipeline_type"),
        ({"pipeline_type": "document", "chunk_type": "mystery"}, "unsupported_chunk_type"),
        (
            {
                "pipeline_type": "transcript",
                "chunk_type": "transcript_topic",
                "coordinates": {"page": 1},
            },
            "incompatible_chunk_coordinates",
        ),
    ],
)
def test_chunk_type_finds_unsupported_or_incompatible_types(overrides, code):
    result = chunk_results(
        evaluate_chunk_type,
        engine_input(chunks=(hashed_chunk(**overrides),)),
    )[0]
    assert result.to_dict()["details"]["defects"][0]["code"] == code


def test_chunk_ordinal_reports_expected_contiguous_position_per_chunk():
    value = engine_input(chunks=(hashed_chunk(2), hashed_chunk(0)))
    results = chunk_results(evaluate_chunk_ordinal, value)
    by_id = {result.target.target_id: result for result in results}

    assert by_id["chunk-0"].outcome is RuleOutcome.PASS
    gap = by_id["chunk-2"]
    assert gap.outcome is RuleOutcome.FINDING
    assert gap.to_dict()["details"]["defects"] == [
        {"actual": 2, "code": "invalid_ordinal", "expected": 1}
    ]


@pytest.mark.parametrize(
    "coordinates,code",
    [
        ({"page": -1}, "negative_coordinate"),
        ({"page_start": 3, "page_end": 2}, "inverted_coordinate_range"),
        ({"start_ms": 2000, "end_ms": 1000}, "inverted_coordinate_range"),
        ({"slide": "one"}, "invalid_coordinate_type"),
    ],
)
def test_chunk_coordinates_aggregates_structural_range_defects(coordinates, code):
    result = chunk_results(
        evaluate_chunk_coordinates,
        engine_input(chunks=(hashed_chunk(coordinates=coordinates),)),
    )[0]
    assert result.to_dict()["details"]["defects"][0]["code"] == code


def test_vector_hard_limit_uses_only_explicit_token_facts():
    chunk = hashed_chunk()
    missing = chunk_results(
        evaluate_vector_hard_limit,
        engine_input(chunks=(chunk,)),
    )[0]
    passing = chunk_results(
        evaluate_vector_hard_limit,
        engine_input(
            chunks=(chunk,),
            token_facts=(ChunkTokenFact("chunk-0", "cl100k", 1024, 1024),),
        ),
    )[0]
    over = chunk_results(
        evaluate_vector_hard_limit,
        engine_input(
            chunks=(chunk,),
            token_facts=(ChunkTokenFact("chunk-0", "cl100k", 1025, 1024),),
        ),
    )[0]

    assert missing.to_dict()["details"]["defects"][0]["code"] == "missing_token_fact"
    assert passing.outcome is RuleOutcome.PASS
    over_details = over.to_dict()["details"]
    assert over_details["defects"][0]["code"] == "vector_token_hard_limit"
    assert over_details["counter_id"] == "cl100k"
    assert over_details["observed_count"] == 1025
    assert over_details["hard_limit"] == 1024


def test_vector_hard_limit_aggregates_when_all_token_facts_are_unavailable():
    results = chunk_results(
        evaluate_vector_hard_limit,
        engine_input(chunks=(hashed_chunk(0), hashed_chunk(1), hashed_chunk(2))),
    )

    assert len(results) == 1
    finding = results[0]
    assert finding.outcome is RuleOutcome.FINDING
    assert finding.target.target_id == EMPTY_DOMAIN_TARGET_ID
    assert finding.to_dict()["details"] == {
        "chunk_count": 3,
        "defects": [{"code": "missing_token_fact"}],
        "ruleset_version": "audit/v1",
    }


def test_vector_hard_limit_keeps_partial_token_evidence_per_chunk():
    results = chunk_results(
        evaluate_vector_hard_limit,
        engine_input(
            chunks=(hashed_chunk(0), hashed_chunk(1)),
            token_facts=(ChunkTokenFact("chunk-0", "cl100k", 100, 1024),),
        ),
    )
    by_target = {result.target.target_id: result for result in results}

    assert by_target["chunk-0"].outcome is RuleOutcome.PASS
    assert (
        by_target["chunk-1"].to_dict()["details"]["defects"][0]["code"]
        == "missing_token_fact"
    )


def test_persisted_hashes_use_exact_splitter_normalization_and_aggregate_mismatches():
    vector = "e\u0301  x\r\ny"
    fulltext = "body\rfinal\n\n"
    valid = hashed_chunk(vector_text=vector, fulltext=fulltext)
    invalid = audit_chunk(
        vector_text=vector,
        fulltext=fulltext,
        vector_text_hash="0" * 64,
        fulltext_hash="1" * 64,
    )

    assert chunk_results(
        evaluate_persisted_hashes, engine_input(chunks=(valid,))
    )[0].outcome is RuleOutcome.PASS
    result = chunk_results(
        evaluate_persisted_hashes, engine_input(chunks=(invalid,))
    )[0]
    assert [item["code"] for item in result.to_dict()["details"]["defects"]] == [
        "vector_text_hash_mismatch",
        "fulltext_hash_mismatch",
    ]


def test_chunk_rule_results_are_stable_for_chunk_and_token_caller_order():
    chunks = (hashed_chunk(1), hashed_chunk(0))
    facts = (
        ChunkTokenFact("chunk-1", "cl100k", 10, 100),
        ChunkTokenFact("chunk-0", "cl100k", 20, 100),
    )
    first = engine_input(
        run=audit_run(chunk_count=2),
        chunks=chunks,
        token_facts=facts,
    )
    second = engine_input(
        run=audit_run(chunk_count=2),
        chunks=tuple(reversed(chunks)),
        token_facts=tuple(reversed(facts)),
    )

    for evaluator in (
        evaluate_chunk_texts,
        evaluate_chunk_type,
        evaluate_chunk_ordinal,
        evaluate_chunk_coordinates,
        evaluate_vector_hard_limit,
        evaluate_persisted_hashes,
    ):
        assert [item.to_dict() for item in evaluator(first)] == [
            item.to_dict() for item in evaluator(second)
        ]
