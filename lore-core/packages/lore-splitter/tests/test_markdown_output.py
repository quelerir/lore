from __future__ import annotations

import json

from lore_splitter.documents.contracts import (
    DocumentImageExtractionResult,
    DocumentMarkdownResult,
    ImageSkip,
    ImageSourceLocation,
    ImageToastCandidate,
    ImageToastOccurrence,
)
from lore_splitter.markdown import profile_table
from lore_splitter.markdown.output import (
    MetadataConfig,
    build_document_output_bundle,
    build_embedding_metadata,
    build_full_metadata,
    build_workbook_output_bundle,
    metadata_json_bytes,
    write_document_outputs,
    write_run_manifest,
    write_workbook_outputs,
)
from lore_splitter.markdown.table_markdown import extract_markdown_document_tables
from lore_splitter.markdown.toast import ToastThresholds, classify_table
from lore_core_domain.storage_contracts import (
    ImageToastStorageResult,
    TableToastStorageResult,
)
from tests.test_document_markdown_contracts import _document_artifact
from tests.test_markdown_render import _candidate, _sheet, _table_data, _workbook


def test_embedding_metadata_is_budgeted_and_full_metadata_is_complete(tmp_path) -> None:
    workbook = _workbook(
        sheets=(
            _sheet("Summary", 1, candidates=(_candidate("Summary", 1, "A1:E4"),)),
            _sheet("Decorative", 2, candidates=(_candidate("Decorative", 2, "A1:B2"),)),
        )
    )
    table = _table_data(
        "Summary",
        1,
        "A1:E4",
        rows=(
            ("Customer ID", "Region", "Amount USD", "Invoice Date", "Notes"),
            ("C-001", "North", 100.0, "2026-02-01", "priority"),
            ("C-002", "South", 250.5, "2026-02-02", "renewal"),
            ("C-003", "North", 75.0, "2026-02-03", "priority"),
        ),
    )
    skipped = _table_data(
        "Decorative",
        2,
        "A1:B2",
        rows=(("Column_1", "Column_2"), ("", None)),
    )
    tables = (table, skipped)
    profiles = tuple(profile_table(item) for item in tables)
    decisions = (
        classify_table(table, profiles[0], thresholds=ToastThresholds(max_inline_markdown_bytes=1)),
        classify_table(skipped, profiles[1]),
    )

    config = MetadataConfig(embedding_byte_budget=1800, max_embedding_unique_values=1)
    embedding = build_embedding_metadata(workbook, tables, profiles, decisions, config=config)
    full = build_full_metadata(workbook, tables, profiles, decisions)

    assert len(metadata_json_bytes(embedding)) <= config.embedding_byte_budget
    embedded_table = embedding["tables"][0]
    assert embedded_table["toast_id"] == decisions[0].toast_id
    assert embedded_table["source"] == workbook.source_file.identity_dict()
    assert embedded_table["workbook_checksum"] == workbook.workbook_checksum
    assert embedded_table["sheet"] == {"name": "Summary", "index": 1}
    assert embedded_table["range"]["a1_range"] == "A1:E4"
    assert embedded_table["dimensions"] == {"rows": 4, "columns": 5, "cells": 20}
    assert embedded_table["columns"] == [
        "Customer ID",
        "Region",
        "Amount USD",
        "Invoice Date",
        "Notes",
    ]
    assert "warnings" in embedded_table
    assert "column_details" not in embedded_table

    assert full["workbook"]["source_path"] == "Finance/report.xlsx"
    assert full["tables"][0]["decision"] == decisions[0].to_dict()
    assert full["tables"][0]["profile"]["column_profiles"][0]["semantic_hints"] == [
        "identifier",
        "dimension",
    ]
    assert full["tables"][0]["profile"]["column_profiles"][2]["min_value"] == 75.0
    assert full["tables"][0]["profile"]["column_profiles"][2]["max_value"] == 250.5
    assert full["tables"][0]["profile"]["column_profiles"][1]["unique_values"] == [
        "North",
        "South",
    ]
    assert full["tables"][1]["classification"] == "skipped"
    assert full["skipped_fragments"][0]["sheet"] == {"name": "Decorative", "index": 2}
    assert full["skipped_fragments"][0]["range"]["a1_range"] == "A1:B2"
    assert "low_meaning_table" in full["skipped_fragments"][0]["warnings"]
    assert full["diagnostics"][0]["reason"] == "skipped_fragment"
    assert not list(tmp_path.iterdir())


def test_metadata_json_ordering_and_contents_are_deterministic() -> None:
    workbook = _workbook(
        sheets=(_sheet("Summary", 1, candidates=(_candidate("Summary", 1, "A1:B3"),)),)
    )
    table = _table_data("Summary", 1, "A1:B3")
    profile = profile_table(table)
    decision = classify_table(
        table, profile, thresholds=ToastThresholds(max_inline_markdown_bytes=1)
    )

    first = build_full_metadata(workbook, (table,), (profile,), (decision,))
    second = build_full_metadata(workbook, (table,), (profile,), (decision,))

    assert metadata_json_bytes(first) == metadata_json_bytes(second)
    assert json.loads(metadata_json_bytes(first).decode("utf-8")) == first


def test_write_workbook_outputs_writes_stable_bundle_and_manifest(tmp_path) -> None:
    workbook = _workbook(
        sheets=(
            _sheet("Summary", 1, candidates=(_candidate("Summary", 1, "A1:B3"),)),
            _sheet("Decorative", 2, candidates=(_candidate("Decorative", 2, "A1:B2"),)),
        )
    )
    inline = _table_data("Summary", 1, "A1:B3")
    skipped = _table_data(
        "Decorative",
        2,
        "A1:B2",
        rows=(("Column_1", "Column_2"), ("", None)),
    )
    tables = (inline, skipped)
    profiles = tuple(profile_table(table) for table in tables)
    decisions = (
        classify_table(
            inline, profiles[0], thresholds=ToastThresholds(max_inline_markdown_bytes=1)
        ),
        classify_table(skipped, profiles[1]),
    )

    bundle = write_workbook_outputs(
        tmp_path,
        workbook,
        tables,
        profiles,
        decisions,
        sheet_scalar_text={"Summary": ("A1: Quarterly sales note",)},
    )
    manifest = write_run_manifest(tmp_path, (bundle,))

    assert bundle.markdown_path.exists()
    assert bundle.embedding_metadata_path.exists()
    assert bundle.full_metadata_path.exists()
    assert manifest.manifest_path.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        [
            bundle.embedding_metadata_path.name,
            bundle.full_metadata_path.name,
            bundle.markdown_path.name,
            manifest.manifest_path.name,
        ]
    )
    assert bundle.markdown_path.suffix == ".md"
    assert bundle.embedding_metadata_path.name.endswith(".embedding.json")
    assert bundle.full_metadata_path.name.endswith(".full.json")
    assert "report" not in bundle.markdown_path.name
    assert "Finance" not in bundle.markdown_path.name

    markdown = bundle.markdown_path.read_text(encoding="utf-8")
    assert "# Workbook: Finance/report.xlsx" in markdown
    assert decisions[0].toast_id is not None
    assert f"[TOAST: {decisions[0].toast_id}]" in markdown
    assert "Column_1" not in markdown

    embedding = json.loads(bundle.embedding_metadata_path.read_text(encoding="utf-8"))
    full = json.loads(bundle.full_metadata_path.read_text(encoding="utf-8"))
    run_manifest = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))

    assert full["workbook"]["source_path"] == "Finance/report.xlsx"
    assert run_manifest["bundle_count"] == 1
    assert run_manifest["bundles"][0]["paths"] == {
        "markdown": str(bundle.markdown_path),
        "embedding_metadata": str(bundle.embedding_metadata_path),
        "full_metadata": str(bundle.full_metadata_path),
    }
    assert run_manifest["bundles"][0]["source"] == workbook.source_file.identity_dict()
    assert run_manifest["bundles"][0]["workbook_checksum"] == workbook.workbook_checksum
    assert run_manifest["bundles"][0]["toast_ids"] == [decisions[0].toast_id]
    assert run_manifest["bundles"][0]["classification_counts"] == {"skipped": 1, "toast": 1}
    assert "low_meaning_table" in run_manifest["bundles"][0]["warnings"]
    assert run_manifest["bundles"][0]["diagnostics"][0]["reason"] == "skipped_fragment"
    assert run_manifest["bundles"][0]["content_signatures"] == [
        decisions[0].content_signature,
        decisions[1].content_signature,
    ]
    assert embedding == bundle.embedding_metadata
    assert full == bundle.full_metadata


def test_document_output_bundle_id_is_stable_path_safe_and_checksum_scoped(tmp_path) -> None:
    result = _document_result(markdown="# Policy\n\nBody\n", checksum="b" * 64)

    first = build_document_output_bundle(tmp_path, result)
    second = build_document_output_bundle(tmp_path, result)
    changed_source = build_document_output_bundle(
        tmp_path,
        _document_result(file_id="doc-456", checksum="b" * 64),
    )
    changed_content = build_document_output_bundle(
        tmp_path,
        _document_result(markdown="# Policy\n\nChanged\n", checksum="c" * 64),
    )

    assert first.bundle_id == second.bundle_id
    assert first.bundle_id.startswith("doc_")
    assert "source" not in first.bundle_id
    assert "Policies" not in first.markdown_path.name
    assert "doc-123" not in first.markdown_path.name
    assert changed_source.bundle_id != first.bundle_id
    assert changed_content.bundle_id != first.bundle_id


def test_write_document_outputs_writes_bundle_artifacts_and_manifest_entry(tmp_path) -> None:
    result = _document_result(
        markdown="# Policy\n\n## Scope\n\nBody\n",
        checksum="b" * 64,
        warnings=("weak_heading_structure",),
        structure_signals={"headings": ["Policy", "Scope"], "title": "Policy"},
    )

    bundle = write_document_outputs(tmp_path, result)
    manifest = write_run_manifest(tmp_path, (bundle,))

    assert bundle.markdown_path.exists()
    assert bundle.embedding_metadata_path.exists()
    assert bundle.full_metadata_path.exists()
    assert bundle.markdown_path.read_text(encoding="utf-8") == result.markdown
    assert bundle.embedding_metadata_path.name.endswith(".embedding.json")
    assert bundle.full_metadata_path.name.endswith(".full.json")

    embedding = json.loads(bundle.embedding_metadata_path.read_text(encoding="utf-8"))
    full = json.loads(bundle.full_metadata_path.read_text(encoding="utf-8"))
    run_manifest = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))

    assert "markdown" not in embedding
    assert embedding == {
        "document": {
            "source": result.source_identity,
            "document_format": "markdown",
            "document_checksum": "b" * 64,
            "title": "Policy",
            "headings": ["Policy", "Scope"],
            "warnings": ["weak_heading_structure"],
            "text_stats": {"characters": 24, "lines": 5},
        }
    }
    assert full["document"]["source"] == result.source.to_dict()
    assert full["document"]["local_path"] == result.local_path
    assert full["document"]["document_checksum"] == "b" * 64
    assert full["document"]["structure_signals"] == {
        "headings": ["Policy", "Scope"],
        "title": "Policy",
    }
    assert run_manifest["bundles"][0] == {
        "kind": "document",
        "bundle_id": bundle.bundle_id,
        "paths": {
            "markdown": str(bundle.markdown_path),
            "embedding_metadata": str(bundle.embedding_metadata_path),
            "full_metadata": str(bundle.full_metadata_path),
        },
        "source": result.source_identity,
        "document_checksum": "b" * 64,
        "document_format": "markdown",
        "warnings": ["weak_heading_structure"],
        "diagnostics": [],
        "metadata_paths": {
            "embedding": str(bundle.embedding_metadata_path),
            "full": str(bundle.full_metadata_path),
        },
    }


def test_write_run_manifest_accepts_workbook_and_document_bundles(tmp_path) -> None:
    workbook = _workbook(
        sheets=(_sheet("Summary", 1, candidates=(_candidate("Summary", 1, "A1:B3"),)),)
    )
    table = _table_data("Summary", 1, "A1:B3")
    profile = profile_table(table)
    decision = classify_table(table, profile)
    workbook_bundle = build_workbook_output_bundle(
        tmp_path,
        workbook,
        (table,),
        (profile,),
        (decision,),
    )
    document_bundle = build_document_output_bundle(tmp_path, _document_result(checksum="b" * 64))

    manifest = write_run_manifest(tmp_path, (workbook_bundle, document_bundle))
    payload = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))

    assert payload["bundle_count"] == 2
    assert payload["bundles"][0]["kind"] == "workbook"
    assert payload["bundles"][0]["workbook_checksum"] == workbook.workbook_checksum
    assert payload["bundles"][0]["classification_counts"] == {"inline": 1}
    assert payload["bundles"][1]["kind"] == "document"
    assert "workbook_checksum" not in payload["bundles"][1]
    assert "classification_counts" not in payload["bundles"][1]


def test_document_image_markers_are_inserted_for_each_occurrence(tmp_path) -> None:
    result = _document_result(
        markdown="# Policy\n\nHere is figure A.\n\nNext figure A.\n",
        checksum="e" * 64,
    )
    image = _image_candidate(
        result,
        locations=(
            ImageSourceLocation(
                source_format="docx",
                relationship_id="rId1",
                metadata={"inline_anchor": "Here is figure A."},
            ),
            ImageSourceLocation(
                source_format="docx",
                relationship_id="rId2",
                metadata={"inline_anchor": "Next figure A."},
            ),
        ),
    )
    extraction = DocumentImageExtractionResult(
        candidates=(image,),
        unique_candidates=(image,),
        occurrences=image.occurrences,
    )

    bundle = write_document_outputs(tmp_path, result, image_extraction=extraction)

    assert bundle.markdown.count(f"[TOAST: {image.toast_id}]") == 2
    assert "Here is figure A.\n\n[TOAST:" in bundle.markdown
    assert "Next figure A.\n\n[TOAST:" in bundle.markdown


def test_document_image_marker_falls_back_to_structural_location(tmp_path) -> None:
    result = _document_result(
        markdown="# Policy\n\n## Appendix\n\nImage context follows.\n",
        checksum="f" * 64,
    )
    image = _image_candidate(
        result,
        locations=(
            ImageSourceLocation(
                source_format="pdf",
                page_number=2,
                metadata={"heading": "Appendix", "inline_anchor": "missing anchor"},
            ),
        ),
    )
    extraction = DocumentImageExtractionResult(
        candidates=(image,),
        unique_candidates=(image,),
        occurrences=image.occurrences,
    )

    bundle = write_document_outputs(tmp_path, result, image_extraction=extraction)

    assert "## Appendix\n\n[TOAST: " in bundle.markdown
    assert bundle.markdown.count(f"[TOAST: {image.toast_id}]") == 1


def test_document_image_metadata_is_bounded_in_embedding_and_detailed_in_full(
    tmp_path,
) -> None:
    result = _document_result(markdown="# Policy\n\nHere is figure A.\n", checksum="1" * 64)
    image = _image_candidate(
        result,
        payload=b"not-for-retrieval",
        locations=(
            ImageSourceLocation(
                source_format="docx",
                relationship_id="rId1",
                metadata={"inline_anchor": "Here is figure A."},
            ),
            ImageSourceLocation(
                source_format="docx",
                relationship_id="rId2",
                metadata={"inline_anchor": "Here is figure A.", "paragraph_index": 3},
            ),
        ),
        warnings=("low_contrast",),
        diagnostics=("kept_content_image",),
    )
    skipped = _image_candidate(
        result,
        suffix="skip",
        locations=(
            ImageSourceLocation(
                source_format="docx",
                relationship_id="rId3",
                metadata={"image_role": "icon"},
            ),
        ),
    )
    extraction = DocumentImageExtractionResult(
        candidates=(image, skipped),
        unique_candidates=(image,),
        occurrences=image.occurrences,
        skips=(ImageSkip(candidate=skipped, reason="icon_candidate", diagnostics=("icon",)),),
        warnings=("image_filter_warning",),
    )
    storage_result = ImageToastStorageResult(
        toast_id=image.toast_id,
        bucket="splitter-image-toast",
        object_key=f"images/{image.toast_id}.png",
        content_type=image.content_type,
        extension=image.extension,
        byte_size=image.byte_size,
        checksum_sha256=image.checksum_sha256,
        action="stored",
        warnings=("object-warning",),
        diagnostics=("stored-ok",),
        source=result.source_identity,
        source_kind="document",
        source_checksum=result.document_checksum,
        source_location=image.source_location.to_dict(),
    )

    bundle = write_document_outputs(
        tmp_path,
        result,
        image_extraction=extraction,
        image_storage_results=(storage_result,),
    )
    embedding = json.loads(bundle.embedding_metadata_path.read_text(encoding="utf-8"))
    full = json.loads(bundle.full_metadata_path.read_text(encoding="utf-8"))

    embedded_image = embedding["images"][0]
    assert embedded_image == {
        "toast_id": image.toast_id,
        "source_kind": "document",
        "source_checksum": result.document_checksum,
        "first_location": image.occurrences[0].source_location.to_dict(),
        "occurrence_count": 2,
        "dimensions": {"width_px": 120, "height_px": 80},
        "content_type": "image/png",
        "warnings": ["low_contrast"],
    }
    assert "payload" not in json.dumps(embedding)
    assert "not-for-retrieval" not in json.dumps(embedding)
    assert "bucket" not in json.dumps(embedding)
    assert "object_key" not in json.dumps(embedding)

    assert len(full["images"]) == 1
    full_image = full["images"][0]
    assert full_image["toast_id"] == image.toast_id
    assert full_image["storage"]["bucket"] == "splitter-image-toast"
    assert full_image["storage"]["object_key"] == f"images/{image.toast_id}.png"
    assert full_image["storage"]["action"] == "stored"
    assert full_image["locations"] == [
        image.occurrences[0].to_dict(),
        image.occurrences[1].to_dict(),
    ]
    assert full["skipped_images"][0]["reason"] == "icon_candidate"
    assert full["image_warnings"] == ["image_filter_warning"]


def test_document_full_metadata_preserves_failed_image_storage_results(tmp_path) -> None:
    result = _document_result(checksum="2" * 64)
    image = _image_candidate(result)
    extraction = DocumentImageExtractionResult(
        candidates=(image,),
        unique_candidates=(image,),
        occurrences=image.occurrences,
    )
    failed = ImageToastStorageResult(
        toast_id=image.toast_id,
        bucket="splitter-image-toast",
        object_key=f"images/{image.toast_id}.png",
        content_type=image.content_type,
        extension=image.extension,
        byte_size=image.byte_size,
        checksum_sha256=image.checksum_sha256,
        action="failed",
        diagnostics=("s3 timeout",),
        source=result.source_identity,
        source_kind="document",
        source_checksum=result.document_checksum,
        source_location=image.source_location.to_dict(),
    )

    bundle = build_document_output_bundle(
        tmp_path,
        result,
        image_extraction=extraction,
        image_storage_results=(failed,),
    )

    full_image = bundle.full_metadata["images"][0]
    assert full_image["storage"]["action"] == "failed"
    assert full_image["storage"]["diagnostics"] == ["s3 timeout"]


def test_document_manifest_uses_typed_table_and_image_fields(tmp_path) -> None:
    result = _document_result(
        markdown=(
            "# Policy\n\n"
            "Here is figure A.\n\n"
            "| Region | Owner | Amount |\n"
            "| --- | --- | --- |\n"
            "| North | Ann | 100 |\n"
            "| South | Bob | 250 |\n"
        ),
        checksum="3" * 64,
    )
    extraction = extract_markdown_document_tables(
        (result,),
        thresholds=ToastThresholds(max_inline_markdown_bytes=1),
    )
    table_decision = next(
        decision for decision in extraction.decisions if decision.toast_id is not None
    )
    image = _image_candidate(
        result,
        locations=(
            ImageSourceLocation(
                source_format="docx",
                relationship_id="rId1",
                metadata={"inline_anchor": "Here is figure A."},
            ),
        ),
    )
    image_extraction = DocumentImageExtractionResult(
        candidates=(image,),
        unique_candidates=(image,),
        occurrences=image.occurrences,
        skips=(
            ImageSkip(
                candidate=_image_candidate(result, suffix="skip"),
                reason="decorative_tiny",
            ),
        ),
        warnings=("image-warning",),
    )
    image_storage = ImageToastStorageResult(
        toast_id=image.toast_id,
        bucket="splitter-image-toast",
        object_key=f"images/{image.toast_id}.png",
        content_type=image.content_type,
        extension=image.extension,
        byte_size=image.byte_size,
        checksum_sha256=image.checksum_sha256,
        action="stored",
        source=result.source_identity,
        source_kind="document",
        source_checksum=result.document_checksum,
        source_location=image.source_location.to_dict(),
    )
    bundle = write_document_outputs(
        tmp_path,
        extraction.documents[0],
        tables=extraction.tables,
        profiles=extraction.profiles,
        decisions=extraction.decisions,
        occurrences=extraction.occurrences,
        image_extraction=image_extraction,
        image_storage_results=(image_storage,),
    )
    manifest = write_run_manifest(tmp_path, (bundle,), image_storage_results=(image_storage,))
    payload = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))

    entry = payload["bundles"][0]
    assert entry["table_toast_ids"] == [table_decision.toast_id]
    assert entry["toast_ids"] == [table_decision.toast_id]
    assert entry["image_toast_ids"] == [image.toast_id]
    assert entry["table_counts"] == {"toast": 1}
    assert entry["image_counts"] == {
        "stored": 1,
        "failed_storage": 0,
        "skipped": 1,
        "unique": 1,
        "occurrences": 1,
    }
    assert entry["skipped_image_reasons"] == {"decorative_tiny": 1}
    assert "image_storage" not in entry


def test_document_image_output_bundle_rerun_is_deterministic(tmp_path) -> None:
    result = _document_result(
        markdown="# Policy\n\nHere is figure A.\n",
        checksum="4" * 64,
    )
    image = _image_candidate(
        result,
        locations=(
            ImageSourceLocation(
                source_format="docx",
                relationship_id="rId1",
                metadata={"inline_anchor": "Here is figure A."},
            ),
        ),
    )
    extraction = DocumentImageExtractionResult(
        candidates=(image,),
        unique_candidates=(image,),
        occurrences=image.occurrences,
    )
    storage_result = ImageToastStorageResult(
        toast_id=image.toast_id,
        bucket="splitter-image-toast",
        object_key=f"images/{image.toast_id}.png",
        content_type=image.content_type,
        extension=image.extension,
        byte_size=image.byte_size,
        checksum_sha256=image.checksum_sha256,
        action="stored",
        source=result.source_identity,
        source_kind="document",
        source_checksum=result.document_checksum,
        source_location=image.source_location.to_dict(),
    )

    first = write_document_outputs(
        tmp_path,
        result,
        image_extraction=extraction,
        image_storage_results=(storage_result,),
    )
    first_manifest = write_run_manifest(tmp_path, (first,), image_storage_results=(storage_result,))
    first_payloads = {
        "markdown": first.markdown_path.read_text(encoding="utf-8"),
        "embedding": first.embedding_metadata_path.read_text(encoding="utf-8"),
        "full": first.full_metadata_path.read_text(encoding="utf-8"),
        "manifest": first_manifest.manifest_path.read_text(encoding="utf-8"),
    }

    second = write_document_outputs(
        tmp_path,
        result,
        image_extraction=extraction,
        image_storage_results=(storage_result,),
    )
    second_manifest = write_run_manifest(
        tmp_path,
        (second,),
        image_storage_results=(storage_result,),
    )

    assert second.markdown_path.read_text(encoding="utf-8") == first_payloads["markdown"]
    assert second.embedding_metadata_path.read_text(encoding="utf-8") == first_payloads["embedding"]
    assert second.full_metadata_path.read_text(encoding="utf-8") == first_payloads["full"]
    assert second_manifest.manifest_path.read_text(encoding="utf-8") == first_payloads["manifest"]


def test_document_table_metadata_bounds_locations_and_manifest_storage(tmp_path) -> None:
    result = _document_result(
        markdown=(
            "# Policy\n\n"
            "| Region | Owner | Amount |\n"
            "| --- | --- | --- |\n"
            "| North | Ann | 100 |\n"
            "| South | Bob | 250 |\n\n"
            "Repeat table:\n\n"
            "| Region | Owner | Amount |\n"
            "| --- | --- | --- |\n"
            "| North | Ann | 100 |\n"
            "| South | Bob | 250 |\n"
        ),
        checksum="d" * 64,
    )
    extraction = extract_markdown_document_tables(
        (result,),
        thresholds=ToastThresholds(max_inline_markdown_bytes=1),
    )
    decision = next(decision for decision in extraction.decisions if decision.toast_id is not None)
    storage_result = TableToastStorageResult(
        toast_id=decision.toast_id,
        schema_name="splitter_toast",
        table_name=decision.toast_id,
        row_count=2,
        action="created",
        source_kind="document",
        source_checksum=result.document_checksum,
        source_location={"markdown": {"table_index": 1, "line_start": 3, "line_end": 6}},
    )

    bundle = write_document_outputs(
        tmp_path,
        extraction.documents[0],
        tables=extraction.tables,
        profiles=extraction.profiles,
        decisions=extraction.decisions,
        occurrences=extraction.occurrences,
    )
    manifest = write_run_manifest(
        tmp_path,
        (bundle,),
        storage_results_by_toast_id={decision.toast_id: storage_result},
    )

    assert bundle.markdown.count(f"[TOAST: {decision.toast_id}]") == 2
    assert "| Region | Owner | Amount |" not in bundle.markdown

    embedding = json.loads(bundle.embedding_metadata_path.read_text(encoding="utf-8"))
    full = json.loads(bundle.full_metadata_path.read_text(encoding="utf-8"))
    run_manifest = json.loads(manifest.manifest_path.read_text(encoding="utf-8"))

    assert len(full["tables"]) == 1
    full_table = full["tables"][0]
    assert full_table["source_kind"] == "document"
    assert full_table["source_checksum"] == result.document_checksum
    assert full_table["locations"] == [
        {"table_index": 1, "line_start": 3, "line_end": 6},
        {"table_index": 2, "line_start": 10, "line_end": 13},
    ]
    assert full_table["decision"] == decision.to_dict()

    embedded_table = embedding["tables"][0]
    assert embedded_table["occurrence_count"] == 2
    assert embedded_table["first_location"] == {
        "table_index": 1,
        "line_start": 3,
        "line_end": 6,
    }
    assert "locations" not in embedded_table
    assert embedded_table["classification"] == "toast"
    assert embedded_table["toast_id"] == decision.toast_id

    manifest_entry = run_manifest["bundles"][0]
    assert manifest_entry["toast_ids"] == [decision.toast_id]
    assert manifest_entry["classification_counts"] == {"toast": 1}
    assert manifest_entry["content_signatures"] == [decision.content_signature]
    assert manifest_entry["storage"][0]["source_kind"] == "document"
    assert manifest_entry["storage"][0]["toast_id"] == decision.toast_id
    assert "locations" not in manifest_entry


def test_workbook_output_bundle_rerun_is_deterministic(tmp_path) -> None:
    workbook = _workbook(
        sheets=(_sheet("Summary", 1, candidates=(_candidate("Summary", 1, "A1:B3"),)),)
    )
    table = _table_data("Summary", 1, "A1:B3")
    profile = profile_table(table)
    decision = classify_table(
        table, profile, thresholds=ToastThresholds(max_inline_markdown_bytes=1)
    )

    first = write_workbook_outputs(tmp_path, workbook, (table,), (profile,), (decision,))
    first_manifest = write_run_manifest(tmp_path, (first,))
    first_payloads = {
        "markdown": first.markdown_path.read_text(encoding="utf-8"),
        "embedding": first.embedding_metadata_path.read_text(encoding="utf-8"),
        "full": first.full_metadata_path.read_text(encoding="utf-8"),
        "manifest": first_manifest.manifest_path.read_text(encoding="utf-8"),
    }

    second = write_workbook_outputs(tmp_path, workbook, (table,), (profile,), (decision,))
    second_manifest = write_run_manifest(tmp_path, (second,))

    assert second.to_dict() == first.to_dict()
    assert second.markdown_path.read_text(encoding="utf-8") == first_payloads["markdown"]
    assert second.embedding_metadata_path.read_text(encoding="utf-8") == first_payloads["embedding"]
    assert second.full_metadata_path.read_text(encoding="utf-8") == first_payloads["full"]
    assert second_manifest.manifest_path.read_text(encoding="utf-8") == first_payloads["manifest"]


def test_output_layer_does_not_add_forbidden_surfaces(tmp_path) -> None:
    workbook = _workbook(
        sheets=(_sheet("Summary", 1, candidates=(_candidate("Summary", 1, "A1:B3"),)),)
    )
    table = _table_data("Summary", 1, "A1:B3")
    profile = profile_table(table)
    decision = classify_table(
        table, profile, thresholds=ToastThresholds(max_inline_markdown_bytes=1)
    )

    bundle = build_workbook_output_bundle(tmp_path, workbook, (table,), (profile,), (decision,))

    assert not any(path.suffix in {".csv", ".jsonl"} for path in tmp_path.iterdir())
    assert not any("payload" in path.name or "rows" in path.name for path in tmp_path.iterdir())
    assert not hasattr(bundle, "postgres")
    assert not hasattr(bundle, "cli_command")


def _document_result(
    *,
    file_id: str = "doc-123",
    markdown: str = "# Policy\n\nBody\n",
    checksum: str = "b" * 64,
    warnings: tuple[str, ...] = (),
    structure_signals: dict[str, object] | None = None,
) -> DocumentMarkdownResult:
    return DocumentMarkdownResult(
        source=_document_artifact(file_id=file_id),
        document_format="markdown",
        markdown=markdown,
        document_checksum=checksum,
        warnings=warnings,
        structure_signals=structure_signals or {"headings": ["Policy"], "title": "Policy"},
    )


def _image_candidate(
    document: DocumentMarkdownResult,
    *,
    suffix: str = "image",
    payload: bytes | None = None,
    locations: tuple[ImageSourceLocation, ...] | None = None,
    warnings: tuple[str, ...] = (),
    diagnostics: tuple[str, ...] = (),
) -> ImageToastCandidate:
    candidate_payload = payload or f"payload-{suffix}".encode()
    checksum = f"{suffix:0<64}"[:64]
    active_locations = locations or (
        ImageSourceLocation(
            source_format="docx",
            relationship_id=f"rId-{suffix}",
            metadata={"inline_anchor": "Body"},
        ),
    )
    occurrences = tuple(
        ImageToastOccurrence(
            source_identity=document.source_identity,
            source_location=location,
        )
        for location in active_locations
    )
    return ImageToastCandidate(
        payload=candidate_payload,
        content_type="image/png",
        extension=".png",
        byte_size=len(candidate_payload),
        checksum_sha256=checksum,
        width_px=120,
        height_px=80,
        source_identity=document.source_identity,
        source_location=active_locations[0],
        occurrences=occurrences,
        warnings=warnings,
        diagnostics=diagnostics,
    )
