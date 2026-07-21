from __future__ import annotations

import json
from datetime import UTC, datetime

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
    PayloadResolutionFact,
    PhysicalResolution,
)
from lore_audit.rules.payloads import (
    evaluate_image_metadata,
    evaluate_image_storage_identity,
    evaluate_payload_occurrences,
    evaluate_payload_references,
    evaluate_payload_resolution,
    evaluate_table_metadata,
    evaluate_table_storage_identity,
    evaluate_table_summary,
)
from lore_audit.rules.transcripts import (
    evaluate_transcript_intervals,
    evaluate_transcript_ordering,
    evaluate_transcript_source_splits,
    evaluate_transcript_speakers,
)
from lore_audit.validation import safe_json_to_dict
from lore_core_domain.run_status import RunStatus
from lore_core_domain.storage_contracts import (
    TableToastStoragePlan,
    TableToastStorageResult,
)

SHA = "a" * 64
EMPTY = "__audit_empty_domain__"


def run(**overrides):
    values = dict(
        run_id="run_1",
        logical_file_key="file_1",
        status=RunStatus.SUCCESS,
        source_content_hash=SHA,
        config_hash=SHA,
        operator_version="1",
        chunk_schema_version="chunk/v1",
        claimed_at=datetime(2026, 1, 1, tzinfo=UTC),
        finished_at=datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        chunk_count=1,
        payload_count=1,
        warning_count=0,
        error_count=0,
    )
    values.update(overrides)
    return AuditRun(**values)


def chunk(**overrides):
    values = dict(
        chunk_id="chunk_1",
        run_id="run_1",
        ordinal=0,
        pipeline_type="document",
        chunk_type="text",
        vector_text="text",
        fulltext="text",
        display_text="text",
        coordinates={},
        metadata={},
        payload_refs=({"payload_id": "table_1", "kind": "table", "occurrence_ordinal": 0},),
        content_signature=SHA,
        vector_text_hash=SHA,
        fulltext_hash=SHA,
    )
    values.update(overrides)
    return AuditChunk(**values)


def occurrence(**overrides):
    values = dict(
        run_id="run_1",
        payload_id="table_1",
        occurrence_ordinal=0,
        kind="table",
        storage_identity="lore_toast.table_1",
        content_hash=SHA,
        coordinates={"sheet": "Sheet1", "range": "A1:B3"},
        metadata={},
    )
    values.update(overrides)
    return AuditPayloadOccurrence(**values)


def table_fact(**overrides):
    values = dict(
        payload_id="table_1",
        kind="table",
        registered=True,
        occurrence_count=1,
        registration_identity={
            "schema_name": "lore_toast",
            "table_name": "table_1",
            "row_count": 2,
            "column_count": 2,
            "columns": [{"name": "name", "type": "text"}, {"name": "value", "type": "int"}],
            "source_kind": "xlsx",
            "source_checksum": SHA,
            "source_location": {"sheet": "Sheet1", "range": "A1:B3"},
            "profile_signature": SHA,
        },
        physical=PhysicalResolution(
            storage_kind="postgres",
            resolved=True,
            identity={"schema_name": "lore_toast", "table_name": "table_1"},
        ),
        metadata={
            "columns": [{"name": "name", "type": "text"}, {"name": "value", "type": "int"}],
            "row_count": 2,
            "column_count": 2,
            "source_kind": "xlsx",
            "source_checksum": SHA,
            "source_location": {"sheet": "Sheet1", "range": "A1:B3"},
            "sheet": "Sheet1",
            "range": "A1:B3",
        },
        summary={"profile_signature": SHA, "row_count": 2, "column_count": 2},
    )
    values.update(overrides)
    return PayloadResolutionFact(**values)


def image_fact(**overrides):
    values = dict(
        payload_id="image_1",
        kind="image",
        registered=True,
        occurrence_count=1,
        registration_identity={
            "bucket": "toast",
            "object_key": "images/image_1.png",
            "content_type": "image/png",
            "extension": ".png",
            "byte_size": 42,
            "checksum_sha256": SHA,
            "source_kind": "docx",
            "source_checksum": SHA,
            "source_location": {"paragraph": 3},
            "width": 10,
            "height": 20,
        },
        physical=PhysicalResolution(
            storage_kind="s3",
            resolved=True,
            identity={"bucket": "toast", "object_key": "images/image_1.png"},
            checksum_sha256=SHA,
            byte_size=42,
            content_type="image/png",
        ),
        metadata={
            "content_type": "image/png",
            "extension": ".png",
            "byte_size": 42,
            "checksum_sha256": SHA,
            "source_kind": "docx",
            "source_checksum": SHA,
            "source_location": {"paragraph": 3},
            "width": 10,
            "height": 20,
        },
    )
    values.update(overrides)
    return PayloadResolutionFact(**values)


def engine_input(*, chunks=None, occurrences=None, facts=None, diagnostics=()):
    chunks = (chunk(),) if chunks is None else tuple(chunks)
    occurrences = (occurrence(),) if occurrences is None else tuple(occurrences)
    facts = (table_fact(),) if facts is None else tuple(facts)
    snapshot = AuditSnapshot(
        ruleset_version="audit/v1",
        run=run(chunk_count=len(chunks), payload_count=len(facts)),
        chunks=chunks,
        payload_occurrences=occurrences,
        processing_diagnostics=tuple(diagnostics),
    )
    return AuditEngineInput(snapshot=snapshot, ruleset_version="audit/v1", payload_facts=facts)


def serialized(results):
    return json.dumps([item.to_dict() for item in results], sort_keys=True, separators=(",", ":"))


def details(result):
    return safe_json_to_dict(result.details)


def diagnostic(**overrides):
    values = dict(
        diagnostic_id="diag_1",
        run_id="run_1",
        chunk_id="chunk_1",
        payload_id=None,
        level="warning",
        code="TRAN-01-NO_RELIABLE_SLOTS",
        message="bounded parser diagnostic",
        stage="transcript_parse",
        details={"slot_ids": ["slot_0"]},
    )
    values.update(overrides)
    return ProcessingDiagnostic(**values)


PAYLOAD_EVALUATORS = (
    evaluate_payload_occurrences,
    evaluate_payload_resolution,
    evaluate_table_metadata,
    evaluate_table_summary,
    evaluate_table_storage_identity,
    evaluate_image_metadata,
    evaluate_image_storage_identity,
)


@pytest.mark.parametrize("evaluator", PAYLOAD_EVALUATORS)
def test_payload_empty_domains_return_one_stable_na(evaluator):
    value = engine_input(chunks=(), occurrences=(), facts=())
    first = evaluator(value)
    assert len(first) == 1
    assert first[0].target.to_dict() == {"kind": "payload", "target_id": EMPTY}
    assert first[0].outcome is RuleOutcome.NOT_APPLICABLE
    assert first[0].diagnostic_key is None
    assert first[0].severity is None
    assert serialized(first) == serialized(evaluator(value))


def test_payload_references_require_exact_triple_and_registration():
    valid = evaluate_payload_references(engine_input())
    assert valid[0].outcome is RuleOutcome.PASS
    missing_registration = engine_input(facts=())
    result = evaluate_payload_references(missing_registration)[0]
    assert result.outcome is RuleOutcome.FINDING
    assert result.origin is DiagnosticOrigin.AUDIT_RULE
    assert result.diagnostic_key == "audit/v1:chunk:chunk_1:payload_references"
    assert details(result)["defects"][0]["code"] == "unregistered_payload_ref"


def test_payload_reference_defects_are_bounded_sorted_and_repeatable():
    refs = tuple(
        {"payload_id": f"missing_{index:02d}", "kind": "table", "occurrence_ordinal": index}
        for index in reversed(range(10))
    )
    value = engine_input(chunks=(chunk(payload_refs=refs),), occurrences=(), facts=())

    first = evaluate_payload_references(value)[0]
    defect_details = details(first)

    assert first.outcome is RuleOutcome.FINDING
    assert len(defect_details["defects"]) == 8
    assert defect_details["total"] == 20
    assert defect_details["truncated"] is True
    assert serialized((first,)) == serialized(evaluate_payload_references(value))


def test_payload_occurrences_aggregate_gaps_and_fact_count_mismatch():
    occurrences = (occurrence(occurrence_ordinal=1), occurrence(occurrence_ordinal=3))
    value = engine_input(occurrences=occurrences, facts=(table_fact(occurrence_count=2),))
    result = evaluate_payload_occurrences(value)[0]
    assert result.outcome is RuleOutcome.FINDING
    assert {item["code"] for item in details(result)["defects"]} == {"occurrence_ordinal_gap"}


def test_payload_resolution_needs_registered_resolved_matching_physical_fact():
    unresolved = table_fact(
        registered=False,
        registration_identity={},
        physical=None,
    )
    result = evaluate_payload_resolution(engine_input(facts=(unresolved,)))[0]
    assert result.outcome is RuleOutcome.FINDING
    assert {item["code"] for item in details(result)["defects"]} == {
        "payload_not_registered",
        "payload_not_resolved",
    }

    shaped_occurrence_only = engine_input(facts=())
    result = evaluate_payload_resolution(shaped_occurrence_only)[0]
    assert [item["code"] for item in details(result)["defects"]] == [
        "missing_payload_resolution_fact"
    ]


def test_complete_table_summary_passes():
    result = evaluate_table_summary(engine_input(facts=(table_fact(),)))[0]

    assert result.outcome is RuleOutcome.PASS


@pytest.mark.parametrize(
    ("evaluator", "fact", "expected"),
    [
        (evaluate_table_metadata, table_fact(metadata={}), "missing_table_metadata"),
        (
            evaluate_table_metadata,
            table_fact(
                metadata={
                    **safe_json_to_dict(table_fact().metadata),
                    "column_count": 3,
                }
            ),
            "table_metadata_mismatch",
        ),
        (evaluate_table_summary, table_fact(summary={}), "missing_table_summary"),
        (
            evaluate_table_storage_identity,
            table_fact(
                physical=PhysicalResolution(
                    storage_kind="postgres",
                    resolved=True,
                    identity={"schema_name": "wrong", "table_name": "wrong"},
                )
            ),
            "table_storage_identity_mismatch",
        ),
        (evaluate_image_metadata, image_fact(metadata={}), "missing_image_metadata"),
        (
            evaluate_image_metadata,
            image_fact(
                metadata={
                    **safe_json_to_dict(image_fact().metadata),
                    "content_type": "image/jpeg",
                }
            ),
            "image_metadata_mismatch",
        ),
        (
            evaluate_image_storage_identity,
            image_fact(
                physical=PhysicalResolution(
                    storage_kind="s3",
                    resolved=True,
                    identity={"bucket": "wrong", "object_key": "wrong"},
                    checksum_sha256="b" * 64,
                    byte_size=1,
                    content_type="image/jpeg",
                )
            ),
            "image_storage_identity_mismatch",
        ),
    ],
)
def test_payload_metadata_and_storage_mutations_are_findings(evaluator, fact, expected):
    occurrence_value = occurrence(payload_id=fact.payload_id, kind=fact.kind)
    result = evaluator(engine_input(occurrences=(occurrence_value,), facts=(fact,)))[0]
    assert result.outcome is RuleOutcome.FINDING
    assert any(item["code"] == expected for item in details(result)["defects"])


@pytest.mark.parametrize(
    ("updates", "invalid_fields"),
    [
        ({"row_count": -1}, ["row_count"]),
        ({"column_count": True}, ["column_count"]),
        ({"column_count": 1}, ["column_count"]),
        ({"columns": [{"name": 1, "type": 2}, {"name": "value", "type": "int"}]}, ["columns"]),
        ({"source_kind": 7}, ["source_kind"]),
        ({"source_location": 0}, ["source_location"]),
        ({"source_location": {}}, ["source_location"]),
        ({"source_location": {f"key_{index}": index for index in range(17)}}, ["source_location"]),
        ({"source_location": {"xlsx": {"sheet_name": []}}}, ["source_location"]),
    ],
)
def test_table_metadata_rejects_matching_impossible_shapes(updates, invalid_fields):
    registration = safe_json_to_dict(table_fact().registration_identity)
    metadata = safe_json_to_dict(table_fact().metadata)
    registration.update(updates)
    metadata.update(updates)
    fact = table_fact(registration_identity=registration, metadata=metadata)

    result = evaluate_table_metadata(engine_input(facts=(fact,)))[0]

    assert result.outcome is RuleOutcome.FINDING
    assert {item["code"] for item in details(result)["defects"]} >= {
        "invalid_table_metadata"
    }
    invalid = next(
        item for item in details(result)["defects"] if item["code"] == "invalid_table_metadata"
    )
    assert invalid["fields"] == invalid_fields


@pytest.mark.parametrize(
    ("updates", "invalid_fields"),
    [
        ({"byte_size": -1}, ["byte_size"]),
        ({"width": 0}, ["width"]),
        ({"height": True}, ["height"]),
        ({"content_type": 7}, ["content_type"]),
        ({"checksum_sha256": "bad"}, ["checksum_sha256"]),
        ({"source_location": 0}, ["source_location"]),
        ({"source_location": {}}, ["source_location"]),
        ({"source_location": {f"key_{index}": index for index in range(17)}}, ["source_location"]),
        ({"source_location": {"pdf": {"page": []}}}, ["source_location"]),
    ],
)
def test_image_metadata_rejects_matching_impossible_shapes(updates, invalid_fields):
    registration = safe_json_to_dict(image_fact().registration_identity)
    metadata = safe_json_to_dict(image_fact().metadata)
    registration.update(updates)
    metadata.update(updates)
    fact = image_fact(registration_identity=registration, metadata=metadata)

    result = evaluate_image_metadata(
        engine_input(
            occurrences=(occurrence(payload_id="image_1", kind="image"),),
            facts=(fact,),
        )
    )[0]

    assert result.outcome is RuleOutcome.FINDING
    invalid = next(
        item for item in details(result)["defects"] if item["code"] == "invalid_image_metadata"
    )
    assert invalid["fields"] == invalid_fields


def test_source_specific_table_and_image_locations_are_not_universally_constrained():
    table_location = {
        "xlsx": {
            "workbook_checksum": SHA,
            "sheet_name": "Sheet1",
            "sheet_index": 1,
            "range": {
                "a1_range": "A1:B3",
                "min_row": 1,
                "max_row": 3,
                "min_column": 1,
                "max_column": 2,
            },
            "header_row": 1,
        }
    }
    image_location = {"pdf": {"page": 1, "bbox": [0.0, 1.0, 2.0, 3.0]}}
    table_registration = safe_json_to_dict(table_fact().registration_identity)
    table_metadata = safe_json_to_dict(table_fact().metadata)
    table_registration["source_location"] = table_location
    table_metadata["source_location"] = table_location
    image_registration = safe_json_to_dict(image_fact().registration_identity)
    image_metadata = safe_json_to_dict(image_fact().metadata)
    image_registration["source_location"] = image_location
    image_metadata["source_location"] = image_location

    assert evaluate_table_metadata(
        engine_input(facts=(table_fact(registration_identity=table_registration, metadata=table_metadata),))
    )[0].outcome is RuleOutcome.PASS
    assert evaluate_image_metadata(
        engine_input(
            occurrences=(occurrence(payload_id="image_1", kind="image"),),
            facts=(image_fact(registration_identity=image_registration, metadata=image_metadata),),
        )
    )[0].outcome is RuleOutcome.PASS


def test_table_metadata_accepts_persisted_storage_result_xlsx_location():
    plan = TableToastStoragePlan(
        toast_id="table_1",
        schema_name="lore_toast",
        table_name="table_1",
        staging_table_name="table_1_staging",
        advisory_lock_key=1,
        columns=(),
        rows=(),
        source={"source_id": "source_1"},
        workbook_checksum=SHA,
        sheet={"name": "Summary", "index": 1},
        range={"a1_range": "A1:B3"},
    )
    location = TableToastStorageResult.from_plan(
        plan, action="dry_run_created"
    ).to_dict()["source_location"]
    registration = safe_json_to_dict(table_fact().registration_identity)
    metadata = safe_json_to_dict(table_fact().metadata)
    registration["source_location"] = location
    metadata["source_location"] = location

    result = evaluate_table_metadata(
        engine_input(facts=(table_fact(registration_identity=registration, metadata=metadata),))
    )[0]

    assert result.outcome is RuleOutcome.PASS


@pytest.mark.parametrize(
    "xlsx_location",
    [
        {
            "workbook_checksum": "A" * 64,
            "sheet": {"name": "Summary", "index": 1},
            "range": {"a1_range": "A1:B3"},
        },
        {
            "workbook_checksum": SHA,
            "sheet": {"name": "Summary", "index": 0},
            "range": {"a1_range": "A1:B3"},
        },
        {
            "workbook_checksum": "A" * 64,
            "sheet_name": "Summary",
            "sheet_index": 1,
            "range": {
                "a1_range": "A1:B3",
                "min_row": 1,
                "max_row": 3,
                "min_column": 1,
                "max_column": 2,
            },
            "header_row": 1,
        },
        {
            "workbook_checksum": SHA,
            "sheet_name": "Summary",
            "sheet_index": 0,
            "range": {
                "a1_range": "A1:B3",
                "min_row": 1,
                "max_row": 3,
                "min_column": 1,
                "max_column": 2,
            },
            "header_row": 1,
        },
    ],
)
def test_table_metadata_rejects_malformed_persisted_and_candidate_xlsx_locations(
    xlsx_location,
):
    location = {"xlsx": xlsx_location}
    registration = safe_json_to_dict(table_fact().registration_identity)
    metadata = safe_json_to_dict(table_fact().metadata)
    registration["source_location"] = location
    metadata["source_location"] = location

    result = evaluate_table_metadata(
        engine_input(facts=(table_fact(registration_identity=registration, metadata=metadata),))
    )[0]

    assert result.outcome is RuleOutcome.FINDING
    invalid = next(
        item for item in details(result)["defects"] if item["code"] == "invalid_table_metadata"
    )
    assert invalid["fields"] == ["source_location"]


def test_table_and_image_families_return_na_for_other_concrete_kind():
    table_input = engine_input()
    image_input = engine_input(
        occurrences=(occurrence(payload_id="image_1", kind="image"),), facts=(image_fact(),)
    )
    assert evaluate_image_metadata(table_input)[0].outcome is RuleOutcome.NOT_APPLICABLE
    assert evaluate_table_metadata(image_input)[0].outcome is RuleOutcome.NOT_APPLICABLE


def test_payload_results_are_stable_across_caller_order():
    occurrences = (
        occurrence(),
        occurrence(payload_id="image_1", kind="image"),
    )
    facts = (table_fact(), image_fact())
    first = engine_input(occurrences=occurrences, facts=facts)
    second = engine_input(occurrences=reversed(occurrences), facts=reversed(facts))

    for evaluator in PAYLOAD_EVALUATORS:
        assert serialized(evaluator(first)) == serialized(evaluator(second))


def transcript_chunk(**coordinate_overrides):
    boundaries = [
        json.dumps({"slot_id": "slot_0", "ordinal": 0, "speaker": "Alice", "start_ms": 0, "end_ms": 10}, sort_keys=True),
        json.dumps({"slot_id": "slot_1", "ordinal": 1, "speaker": "Bob", "start_ms": 10, "end_ms": 20}, sort_keys=True),
    ]
    coordinates = {
        "speaker": "Alice",
        "speakers": ["Alice", "Bob"],
        "start_ms": 0,
        "end_ms": 20,
        "slot_boundaries": boundaries,
        "internal_boundaries": ["slot_0:0:10", "slot_1:10:20"],
        "continuation_lineage": [],
    }
    coordinates.update(coordinate_overrides)
    return chunk(
        pipeline_type="transcript",
        chunk_type="transcript_topic",
        payload_refs=(),
        coordinates=coordinates,
    )


TRANSCRIPT_EVALUATORS = (
    evaluate_transcript_speakers,
    evaluate_transcript_intervals,
    evaluate_transcript_ordering,
    evaluate_transcript_source_splits,
)


@pytest.mark.parametrize("evaluator", TRANSCRIPT_EVALUATORS)
def test_transcript_valid_non_transcript_and_empty_domains(evaluator):
    valid = engine_input(chunks=(transcript_chunk(),), occurrences=(), facts=())
    assert evaluator(valid)[0].outcome is RuleOutcome.PASS
    ordinary = engine_input(chunks=(chunk(payload_refs=()),), occurrences=(), facts=())
    assert evaluator(ordinary)[0].outcome is RuleOutcome.NOT_APPLICABLE
    empty = engine_input(chunks=(), occurrences=(), facts=())
    result = evaluator(empty)
    assert result[0].target.target_id == EMPTY
    assert result[0].target.kind == "chunk"
    assert result[0].outcome is RuleOutcome.NOT_APPLICABLE
    assert result[0].diagnostic_key is None
    assert result[0].severity is None
    assert serialized(result) == serialized(evaluator(empty))


@pytest.mark.parametrize(
    ("evaluator", "coordinates", "code"),
    [
        (evaluate_transcript_speakers, {"speaker": "", "speakers": []}, "missing_transcript_speaker"),
        (evaluate_transcript_intervals, {"start_ms": 20, "end_ms": 10}, "invalid_transcript_interval"),
        (
            evaluate_transcript_ordering,
            {"slot_boundaries": [json.dumps({"slot_id": "x", "ordinal": 1, "speaker": "A", "start_ms": 10, "end_ms": 20}), json.dumps({"slot_id": "x", "ordinal": 0, "speaker": "A", "start_ms": 0, "end_ms": 10})]},
            "duplicate_slot_id",
        ),
        (
            evaluate_transcript_source_splits,
            {"continuation_lineage": ["slot_9:split:0"]},
            "broken_continuation_lineage",
        ),
        (
            evaluate_transcript_source_splits,
            {"internal_boundaries": ["slot_0:0:9", "slot_1:10:20"]},
            "noncontiguous_source_split",
        ),
        (evaluate_transcript_ordering, {"slot_boundaries": ["not-json"]}, "malformed_slot_boundary"),
    ],
)
def test_transcript_mutations_aggregate_into_findings(evaluator, coordinates, code):
    value = engine_input(chunks=(transcript_chunk(**coordinates),), occurrences=(), facts=())
    result = evaluator(value)[0]
    assert result.outcome is RuleOutcome.FINDING
    assert any(item["code"] == code for item in details(result)["defects"])


def test_transcript_speakers_accept_renderer_shaped_plural_coordinates():
    value = engine_input(
        chunks=(transcript_chunk(speaker=None),), occurrences=(), facts=()
    )

    assert evaluate_transcript_speakers(value)[0].outcome is RuleOutcome.PASS


def test_transcript_source_splits_accept_bounded_oversized_lineage():
    value = engine_input(
        chunks=(
            transcript_chunk(continuation_lineage=["slot_0:split:0", "slot_0:split:1"]),
        ),
        occurrences=(),
        facts=(),
    )

    assert evaluate_transcript_source_splits(value)[0].outcome is RuleOutcome.PASS


def test_transcript_multiple_malformed_boundaries_are_bounded_and_repeatable():
    value = engine_input(
        chunks=(transcript_chunk(slot_boundaries=["bad"] * 12),),
        occurrences=(),
        facts=(),
    )

    first = evaluate_transcript_ordering(value)[0]
    defect_details = details(first)

    assert first.diagnostic_key == "audit/v1:chunk:chunk_1:transcript_ordering"
    assert len(defect_details["defects"]) == 8
    assert defect_details["total"] == 12
    assert defect_details["truncated"] is True
    assert serialized((first,)) == serialized(evaluate_transcript_ordering(value))


@pytest.mark.parametrize(
    "diagnostic_details",
    [
        {"slot_ids": ["slot_0", "slot_1"]},
        {"slot_ids": ["slot_0"]},
    ],
)
def test_transcript_evaluator_leaves_full_and_partial_explanations_for_plan_04(
    diagnostic_details,
):
    value = engine_input(
        chunks=(transcript_chunk(slot_boundaries=["bad", "also-bad"]),),
        occurrences=(),
        facts=(),
        diagnostics=(diagnostic(details=diagnostic_details),),
    )

    result = evaluate_transcript_ordering(value)[0]

    assert result.outcome is RuleOutcome.FINDING
    assert result.suppression is None
    assert details(result)["total"] == 2
