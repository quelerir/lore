from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from pathlib import Path

from fixtures.documents.generate_contract_fixtures import create_document_contract_fixtures
from fixtures.documents.generate_image_fixtures import create_image_contract_fixtures
from openpyxl import Workbook
from tests.test_xlsx_fixtures import (
    _manifest_record,
    _write_edge_case_workbook,
    _write_large_dense_workbook,
    _write_manifest,
)

_TESTS_DIR = Path(__file__).parent


def test_dry_run_pipeline_writes_artifacts_and_compact_summary(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    config = PipelineConfig(
        manifest_path=_TESTS_DIR / "fixtures" / "xlsx_manifest.jsonl",
        input_root=_TESTS_DIR / "fixtures",
        output_dir=tmp_path,
        storage_mode="dry_run",
        embedding_byte_budget=2048,
        max_embedding_unique_values=2,
        toast_min_rows=2,
        toast_min_columns=2,
        toast_min_cells=4,
    )

    result = run(config)
    summary = result.to_summary_dict()

    expected_keys = {
        "processed_files",
        "skipped_files",
        "workbook_count",
        "document_count",
        "extracted_table_count",
        "toast_table_count",
        "inline_table_count",
        "warning_count",
        "error_count",
        "storage_result_count",
        "failed_storage_result_count",
        "image_candidate_count",
        "image_toast_count",
        "skipped_image_count",
        "image_storage_result_count",
        "failed_image_storage_result_count",
        "artifact_paths",
    }
    assert set(summary) == expected_keys
    assert summary["processed_files"] == 1
    assert summary["skipped_files"] == 1
    assert summary["workbook_count"] == 1
    assert summary["document_count"] == 1
    assert summary["extracted_table_count"] == 3
    assert summary["toast_table_count"] >= 1
    assert summary["inline_table_count"] >= 0
    assert summary["warning_count"] >= 1
    assert summary["error_count"] >= 1
    assert summary["storage_result_count"] == result.toast_table_count
    assert summary["failed_storage_result_count"] == 0

    run_manifest_path = Path(summary["artifact_paths"]["run_manifest"])
    assert run_manifest_path.exists()
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    assert run_manifest["manifest_path"] == str(run_manifest_path)
    assert run_manifest["bundle_count"] == 2

    bundle = result.bundles[0]
    assert bundle.markdown_path.exists()
    assert bundle.embedding_metadata_path.exists()
    assert bundle.full_metadata_path.exists()
    assert summary["artifact_paths"]["workbooks"] == [bundle.to_dict()["paths"]]


def test_pipeline_config_thresholds_affect_metadata_and_toast_decisions(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    config = PipelineConfig(
        manifest_path=_TESTS_DIR / "fixtures" / "xlsx_manifest.jsonl",
        input_root=_TESTS_DIR / "fixtures",
        output_dir=tmp_path,
        storage_mode="dry_run",
        embedding_byte_budget=4096,
        max_embedding_unique_values=2,
        toast_min_rows=2,
        toast_min_columns=2,
        toast_min_cells=4,
    )

    result = run(config)
    full_metadata = result.bundles[0].full_metadata
    embedding_metadata = result.bundles[0].embedding_metadata

    assert any(table["classification"] == "toast" for table in full_metadata["tables"])
    toast_tables = [
        table for table in full_metadata["tables"] if table["classification"] == "toast"
    ]
    assert toast_tables
    for table in toast_tables:
        assert table["decision"]["thresholds"]["max_inline_rows"] == config.toast_min_rows
        assert table["decision"]["thresholds"]["max_inline_columns"] == config.toast_min_columns
        assert table["decision"]["thresholds"]["max_inline_cells"] == config.toast_min_cells

    embedded_tables = embedding_metadata["tables"]
    assert embedded_tables
    for table in embedded_tables:
        for column in table.get("column_details", []):
            assert len(column.get("unique_values", [])) <= config.max_embedding_unique_values


def test_importing_pipeline_does_not_import_airflow_or_psycopg() -> None:
    before = set(sys.modules)

    import lore_splitter.pipeline  # noqa: F401

    imported = set(sys.modules) - before
    assert "airflow" not in imported
    assert "psycopg" not in imported


def test_storage_backed_pipeline_uses_supplied_store_for_toast_tables(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run
    from lore_splitter.storage.fake import FakeTableToastStore

    store = FakeTableToastStore()
    config = PipelineConfig(
        manifest_path=_TESTS_DIR / "fixtures" / "xlsx_manifest.jsonl",
        input_root=_TESTS_DIR / "fixtures",
        output_dir=tmp_path,
        storage_mode="postgres",
        table_store=store,
        storage_schema="custom_toast",
        toast_min_rows=2,
        toast_min_columns=2,
        toast_min_cells=4,
    )

    result = run(config)
    run_manifest = json.loads(Path(result.artifact_paths["run_manifest"]).read_text())
    storage_entries = [
        entry
        for bundle in run_manifest["bundles"]
        for entry in bundle.get("storage", [])
    ]

    assert result.storage_results
    assert set(store.results_by_toast_id) == {result.toast_id for result in result.storage_results}
    assert result.toast_table_count == len(result.storage_results)
    assert result.storage_result_count == len(result.storage_results)
    assert result.failed_storage_result_count == 0
    assert all(result.schema_name == "custom_toast" for result in result.storage_results)
    assert [entry["schema"] for entry in storage_entries] == [
        result.schema_name for result in result.storage_results
    ]
    assert {entry["toast_id"] for entry in storage_entries} == set(store.results_by_toast_id)


def test_failed_storage_result_raises_after_writing_partial_diagnostics(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, PipelineRunError, run
    from lore_splitter.storage import (
        TableToastStoragePlan,
        TableToastStorageResult,
    )

    class FailingStore:
        def __init__(self) -> None:
            self.calls: list[TableToastStoragePlan] = []

        def store_table(self, plan: TableToastStoragePlan) -> TableToastStorageResult:
            self.calls.append(plan)
            return replace(
                TableToastStorageResult.from_plan(plan, action="failed"),
                row_count=0,
                diagnostics=(*plan.diagnostics, "postgres_storage_failed:boom"),
            )

    store = FailingStore()
    config = PipelineConfig(
        manifest_path=_TESTS_DIR / "fixtures" / "xlsx_manifest.jsonl",
        input_root=_TESTS_DIR / "fixtures",
        output_dir=tmp_path,
        storage_mode="postgres",
        table_store=store,
        toast_min_rows=2,
        toast_min_columns=2,
        toast_min_cells=4,
    )

    try:
        run(config)
    except PipelineRunError as exc:
        error = exc
    else:
        raise AssertionError("expected failed storage result to fail the pipeline")

    assert store.calls
    assert "storage failed" in str(error)
    assert error.result is not None
    assert error.result.failed_storage_result_count == error.result.toast_table_count
    assert error.result.error_count >= 1
    assert any(diagnostic.reason == "missing_local_file" for diagnostic in error.diagnostics)
    run_manifest_path = Path(error.result.artifact_paths["run_manifest"])
    assert run_manifest_path.exists()
    run_manifest = json.loads(run_manifest_path.read_text())
    storage_entries = [
        entry
        for bundle in run_manifest["bundles"]
        for entry in bundle.get("storage", [])
    ]
    assert storage_entries
    assert storage_entries[0]["action"] == "failed"
    assert any(
        "postgres_storage_failed:boom" in diagnostic
        for entry in storage_entries
        for diagnostic in entry["diagnostics"]
    )


def test_unreadable_only_supported_workbook_raises_with_partial_manifest(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, PipelineRunError, run

    input_root = tmp_path / "fixtures"
    corrupt_path = input_root / "staging" / "files" / "corrupt.xlsx"
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_bytes(b"not an xlsx file")
    manifest_path = _write_manifest(
        tmp_path,
        [_manifest_record("corrupt-workbook", corrupt_path)],
    )

    try:
        run(
            PipelineConfig(
                manifest_path=Path(manifest_path),
                input_root=input_root,
                output_dir=tmp_path / "out",
                storage_mode="dry_run",
            )
        )
    except PipelineRunError as exc:
        error = exc
    else:
        raise AssertionError("expected unreadable required workbook to fail the pipeline")

    assert "unreadable required input" in str(error)
    assert error.result is not None
    assert error.result.processed_files == 0
    assert error.result.error_count == 1
    assert any(diagnostic.reason == "unreadable_workbook" for diagnostic in error.diagnostics)
    assert Path(error.result.artifact_paths["run_manifest"]).exists()


def test_runner_veri_01_processes_all_required_workbook_shapes(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    input_root = tmp_path / "fixtures"
    edge_path = input_root / "staging" / "files" / "edge-cases.xlsx"
    sparse_path = input_root / "staging" / "files" / "sparse.xlsx"
    dense_path = input_root / "staging" / "files" / "large-dense.xlsx"
    _write_edge_case_workbook(edge_path)
    _write_sparse_sheet_workbook(sparse_path)
    _write_large_dense_workbook(dense_path)
    manifest_path = _write_manifest(
        tmp_path,
        [
            _manifest_record("edge-cases", edge_path),
            _manifest_record("sparse-sheet", sparse_path),
            _manifest_record("large-dense", dense_path),
        ],
    )

    result = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out",
            storage_mode="dry_run",
            embedding_byte_budget=4096,
            toast_min_rows=1,
            toast_min_columns=1,
            toast_min_cells=1,
        )
    )

    full_metadata_fragments = [
        fragment
        for bundle in result.bundles
        for metadata in (_read_json(bundle.full_metadata_path),)
        for fragment in [*metadata["tables"], *metadata["skipped_fragments"]]
    ]
    ranges_by_sheet: dict[str, list[str]] = {}
    warnings_by_sheet: dict[str, set[str]] = {}
    for fragment in full_metadata_fragments:
        sheet_name = fragment["sheet"]["name"]
        ranges_by_sheet.setdefault(sheet_name, []).append(fragment["range"]["a1_range"])
        warnings_by_sheet.setdefault(sheet_name, set()).update(fragment["warnings"])
    required_shapes = {
        "single-table": ("SingleTable", "A1:C3"),
        "title-plus-table": ("TitlePlusTable", "A3:C5"),
        "multiple tables": ("MultipleTables", "A1:B3"),
        "merged cells": ("MergedCells", "A1:C3"),
        "duplicate headers": ("DuplicateHeaders", "A1:C3"),
        "formulas": ("Formulas", "A1:B2"),
        "hidden sheets": ("HiddenLookup", "A1:B2"),
        "sparse sheet": ("SparseFallback", "A1:D4"),
        "large dense sheet": ("LargeDense", "A1:F80"),
    }

    assert result.workbook_count == 3
    assert result.extracted_table_count >= len(required_shapes)
    for _shape_label, (sheet_name, a1_range) in required_shapes.items():
        assert a1_range in ranges_by_sheet[sheet_name]
    assert "D1:E3" in ranges_by_sheet["MultipleTables"]
    assert "merged_cells_expanded" in warnings_by_sheet["MergedCells"]
    assert "duplicate_headers" in warnings_by_sheet["DuplicateHeaders"]
    assert "hidden_sheet" in warnings_by_sheet["HiddenLookup"]


def test_runner_veri_02_repeated_runs_write_identical_toast_ids_and_references(
    tmp_path,
) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    first = run(
        PipelineConfig(
            manifest_path=_TESTS_DIR / "fixtures" / "xlsx_manifest.jsonl",
            input_root=_TESTS_DIR / "fixtures",
            output_dir=tmp_path / "first",
            storage_mode="dry_run",
            toast_min_rows=1,
            toast_min_columns=1,
            toast_min_cells=1,
        )
    )
    second = run(
        PipelineConfig(
            manifest_path=_TESTS_DIR / "fixtures" / "xlsx_manifest.jsonl",
            input_root=_TESTS_DIR / "fixtures",
            output_dir=tmp_path / "second",
            storage_mode="dry_run",
            toast_min_rows=1,
            toast_min_columns=1,
            toast_min_cells=1,
        )
    )

    assert _toast_ids_from_full_metadata(first) == _toast_ids_from_full_metadata(second)
    assert _toast_references_from_markdown(first) == _toast_references_from_markdown(second)


def test_runner_veri_03_metadata_threshold_reads_generated_embedding_files(
    tmp_path,
) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    config = PipelineConfig(
        manifest_path=_TESTS_DIR / "fixtures" / "xlsx_manifest.jsonl",
        input_root=_TESTS_DIR / "fixtures",
        output_dir=tmp_path,
        storage_mode="dry_run",
        embedding_byte_budget=2048,
        max_embedding_unique_values=1,
        toast_min_rows=2,
        toast_min_columns=2,
        toast_min_cells=4,
    )

    result = run(config)

    for bundle in result.bundles:
        payload = bundle.embedding_metadata_path.read_bytes()
        assert len(payload) <= config.embedding_byte_budget
        assert json.loads(payload.decode("utf-8")) == bundle.embedding_metadata


def test_runner_veri_04_mixed_manifest_skips_unsupported_and_keeps_xlsx_output(
    tmp_path,
) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    result = run(
        PipelineConfig(
            manifest_path=_TESTS_DIR / "fixtures" / "xlsx_manifest.jsonl",
            input_root=_TESTS_DIR / "fixtures",
            output_dir=tmp_path,
            storage_mode="dry_run",
            toast_min_rows=2,
            toast_min_columns=2,
            toast_min_cells=4,
        )
    )

    assert any(diagnostic.reason == "missing_local_file" for diagnostic in result.diagnostics)
    assert any(diagnostic.reason == "unsupported_type" for diagnostic in result.diagnostics)
    assert result.skipped_files == 1
    assert result.workbook_count == 1
    assert result.document_count == 1
    assert result.bundles
    assert all(bundle.markdown_path.exists() for bundle in result.bundles)
    assert all(bundle.embedding_metadata_path.exists() for bundle in result.bundles)
    assert all(bundle.full_metadata_path.exists() for bundle in result.bundles)


def test_mixed_manifest_routes_documents_without_workbook_extraction(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    input_root = tmp_path / "fixtures"
    workbook_path = input_root / "staging" / "files" / "workbook.xlsx"
    _write_sparse_sheet_workbook(workbook_path)
    document_paths = [
        input_root / "staging" / "files" / "notes.md",
        input_root / "staging" / "files" / "brief.docx",
        input_root / "staging" / "files" / "slides.pptx",
        input_root / "staging" / "files" / "report.pdf",
    ]
    for path in document_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"fixture for {path.name}".encode())
    unsupported_path = input_root / "staging" / "files" / "archive.zip"
    unsupported_path.write_bytes(b"not supported")
    missing_pdf_path = input_root / "staging" / "files" / "missing.pdf"

    records = [_manifest_record("workbook", workbook_path)]
    records.extend(_document_manifest_record(path.stem, path) for path in document_paths)
    records.append(_document_manifest_record("unsupported", unsupported_path))
    records.append(_document_manifest_record("missing-pdf", missing_pdf_path))
    records.append({"source_id": "google-drive", "file_id": "invalid-record"})
    manifest_path = _write_manifest(tmp_path, records)

    result = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out",
            storage_mode="dry_run",
            toast_min_rows=1,
            toast_min_columns=1,
            toast_min_cells=1,
        )
    )

    assert result.workbook_count == 1
    assert result.document_count == 1
    assert result.skipped_files == 1
    assert any(diagnostic.reason == "unsupported_type" for diagnostic in result.diagnostics)
    assert any(diagnostic.reason == "missing_local_file" for diagnostic in result.diagnostics)
    assert any(diagnostic.reason == "invalid_record" for diagnostic in result.diagnostics)
    assert not any(
        diagnostic.reason == "unreadable_workbook"
        and diagnostic.file_id in {path.stem for path in document_paths}
        for diagnostic in result.diagnostics
    )

    assert Path(result.artifact_paths["document_inputs"]).exists()
    assert len(result.artifact_paths["documents"]) == 1
    document_payload = json.loads(
        Path(result.artifact_paths["document_inputs"]).read_text(encoding="utf-8")
    )
    assert [item["file_id"] for item in document_payload["documents"]] == [
        path.stem for path in document_paths
    ]
    for item, path in zip(document_payload["documents"], document_paths, strict=True):
        assert set(item) == {
            "source_id",
            "stream",
            "file_id",
            "source_path",
            "object_path",
            "mime_type",
            "size_bytes",
            "created_at",
            "updated_at",
            "source_url",
            "metadata",
            "raw_record",
            "local_path",
            "input_kind",
            "normalized_extension",
            "mime_family",
        }
        assert item["source_id"] == "google-drive"
        assert item["stream"] == "regulations"
        assert item["file_id"] == path.stem
        assert item["source_path"] == path.name
        assert item["object_path"] == f"/staging/files/{path.name}"
        assert item["size_bytes"] == path.stat().st_size
        assert item["source_url"] == f"https://drive.example/{path.stem}"
        assert item["metadata"] == {"fixture": "document"}
        assert item["raw_record"]["file_id"] == path.stem
        assert item["local_path"] == str(path)
        assert item["input_kind"] == "document"
        assert item["normalized_extension"] == path.suffix
        assert item["mime_family"] in {"markdown", "word-processing", "presentation", "pdf"}


def test_mixed_document_workbook_pipeline_writes_unified_output_bundles(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    input_root = tmp_path / "fixtures"
    workbook_path = input_root / "staging" / "files" / "workbook.xlsx"
    markdown_path = input_root / "staging" / "files" / "policy.md"
    _write_sparse_sheet_workbook(workbook_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        (_TESTS_DIR / "fixtures" / "documents" / "sample.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    document_fixtures = create_document_contract_fixtures(markdown_path.parent)
    records = [
        _manifest_record("workbook", workbook_path),
        _document_manifest_record("markdown-policy", markdown_path),
        _document_manifest_record("docx-policy", document_fixtures.docx),
        _document_manifest_record("slides-policy", document_fixtures.pptx),
        _document_manifest_record("pdf-policy", document_fixtures.pdf),
    ]
    manifest_path = _write_manifest(tmp_path, records)

    result = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out",
            storage_mode="dry_run",
            toast_min_rows=1,
            toast_min_columns=1,
            toast_min_cells=1,
        )
    )

    assert result.workbook_count == 1
    assert result.document_count == 4
    assert set(result.artifact_paths) >= {
        "run_manifest",
        "workbooks",
        "document_inputs",
        "documents",
    }
    assert Path(result.artifact_paths["document_inputs"]).exists()
    assert len(result.artifact_paths["workbooks"]) == 1
    assert len(result.artifact_paths["documents"]) == 4

    run_manifest = _read_json(Path(result.artifact_paths["run_manifest"]))
    entries_by_kind: dict[str, list[dict[str, object]]] = {}
    for entry in run_manifest["bundles"]:
        entries_by_kind.setdefault(entry["kind"], []).append(entry)
    assert len(entries_by_kind["workbook"]) == 1
    assert len(entries_by_kind["document"]) == 4
    assert {entry["document_format"] for entry in entries_by_kind["document"]} == {
        "markdown",
        "docx",
        "pptx",
        "pdf",
    }
    assert all(str(entry["bundle_id"]).startswith("doc_") for entry in entries_by_kind["document"])

    document_markdown = {
        entry["document_format"]: Path(entry["paths"]["markdown"]).read_text(encoding="utf-8")
        for entry in entries_by_kind["document"]
    }
    assert "Contract Policy" in document_markdown["docx"]
    assert "Deterministic DOCX body text" in document_markdown["docx"]
    assert "Slide" in document_markdown["pptx"]
    assert "Deterministic PPTX body text" in document_markdown["pptx"]
    assert "Contract Manual" in document_markdown["pdf"]
    assert "deterministic PDF text" in document_markdown["pdf"]


def test_markdown_document_pipeline_preserves_source_markdown_structure(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    input_root = tmp_path / "fixtures"
    markdown_path = input_root / "staging" / "files" / "sample.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    expected_markdown = (_TESTS_DIR / "fixtures" / "documents" / "sample.md").read_text(encoding="utf-8")
    markdown_path.write_text(expected_markdown.replace("\n", "\r\n"), encoding="utf-8")
    manifest_path = _write_manifest(
        tmp_path,
        [_document_manifest_record("sample-markdown", markdown_path)],
    )

    result = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out",
            storage_mode="dry_run",
        )
    )

    assert result.workbook_count == 0
    assert result.document_count == 1
    document_path = Path(result.artifact_paths["documents"][0]["markdown"])
    markdown = document_path.read_text(encoding="utf-8")
    assert markdown == expected_markdown
    assert "# Contract Policy" in markdown
    assert "- Preserve list items" in markdown
    assert "[links](https://example.com/policy)" in markdown
    assert "| Field | Value |" in markdown
    assert "![diagram](images/policy-flow.png)" in markdown


def test_pipeline_extracts_document_tables_before_output_and_stores_table_toasts(
    tmp_path,
) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    input_root = tmp_path / "fixtures"
    workbook_path = input_root / "staging" / "files" / "workbook.xlsx"
    markdown_path = input_root / "staging" / "files" / "policy.md"
    _write_sparse_sheet_workbook(workbook_path)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        (
            "# Policy\n\n"
            "| Region | Owner | Amount |\n"
            "| --- | --- | --- |\n"
            "| North | Ann | 100 |\n"
            "| South | Bob | 250 |\n\n"
            "<table><tr><th>A</th><th>B</th></tr><tr><td colspan=\"2\">bad</td></tr></table>\n"
        ),
        encoding="utf-8",
    )
    manifest_path = _write_manifest(
        tmp_path,
        [
            _manifest_record("workbook", workbook_path),
            _document_manifest_record("markdown-policy", markdown_path),
        ],
    )

    first = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out-first",
            storage_mode="dry_run",
            toast_min_rows=1,
            toast_min_columns=1,
            toast_min_cells=1,
        )
    )
    second = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out-second",
            storage_mode="dry_run",
            toast_min_rows=1,
            toast_min_columns=1,
            toast_min_cells=1,
        )
    )

    assert first.workbook_count == 1
    assert first.document_count == 1
    assert first.extracted_table_count >= 2
    assert first.toast_table_count >= 2
    assert first.storage_result_count == first.toast_table_count
    assert any(diagnostic.reason == "unsupported_html_table" for diagnostic in first.diagnostics)

    manifest = _read_json(Path(first.artifact_paths["run_manifest"]))
    document_entry = next(entry for entry in manifest["bundles"] if entry["kind"] == "document")
    document_markdown = Path(document_entry["paths"]["markdown"]).read_text(encoding="utf-8")
    document_full = _read_json(Path(document_entry["paths"]["full_metadata"]))
    document_storage = document_entry["storage"]

    assert re.search(r"\[TOAST: toast_tbl_[0-9a-f]{20}\]", document_markdown)
    assert "| Region | Owner | Amount |" not in document_markdown
    assert "[TABLE_SKIPPED: unsupported_html_table]" in document_markdown
    assert document_entry["classification_counts"] == {"toast": 1}
    assert document_full["tables"][0]["source_kind"] == "document"
    assert document_full["tables"][0]["locations"] == [
        {"table_index": 1, "line_start": 3, "line_end": 6}
    ]
    assert document_storage[0]["source_kind"] == "document"
    assert document_storage[0]["source_checksum"] == document_entry["document_checksum"]

    first_doc_toast_ids = document_entry["toast_ids"]
    second_manifest = _read_json(Path(second.artifact_paths["run_manifest"]))
    second_document_entry = next(
        entry for entry in second_manifest["bundles"] if entry["kind"] == "document"
    )
    assert second_document_entry["toast_ids"] == first_doc_toast_ids
    assert second_document_entry["content_signatures"] == document_entry["content_signatures"]


def test_document_pipeline_failures_are_source_scoped_without_placeholder_bundles(
    tmp_path,
) -> None:
    from lore_splitter.pipeline import PipelineConfig, PipelineRunError, run

    input_root = tmp_path / "fixtures"
    workbook_path = input_root / "staging" / "files" / "workbook.xlsx"
    _write_sparse_sheet_workbook(workbook_path)
    document_fixtures = create_document_contract_fixtures(workbook_path.parent)
    manifest_path = _write_manifest(
        tmp_path,
        [
            _manifest_record("workbook", workbook_path),
            _document_manifest_record("empty-pdf", document_fixtures.empty_pdf),
            _document_manifest_record("corrupt-docx", document_fixtures.corrupt),
        ],
    )

    result = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out",
            storage_mode="dry_run",
        )
    )

    assert result.workbook_count == 1
    assert result.document_count == 0
    assert result.artifact_paths["documents"] == []
    assert {(diagnostic.reason, diagnostic.file_id) for diagnostic in result.diagnostics} >= {
        ("no_extractable_text", "empty-pdf"),
        ("document_conversion_failed", "corrupt-docx"),
    }
    run_manifest = _read_json(Path(result.artifact_paths["run_manifest"]))
    assert [entry["kind"] for entry in run_manifest["bundles"]] == ["workbook"]

    failed_only_root = tmp_path / "failed-only"
    failed_only_root.mkdir()
    only_failed_docs_manifest = _write_manifest(
        failed_only_root,
        [
            _document_manifest_record("empty-pdf", document_fixtures.empty_pdf),
            _document_manifest_record("corrupt-docx", document_fixtures.corrupt),
        ],
    )
    try:
        run(
            PipelineConfig(
                manifest_path=Path(only_failed_docs_manifest),
                input_root=input_root,
                output_dir=tmp_path / "failed-only-out",
                storage_mode="dry_run",
            )
        )
    except PipelineRunError as exc:
        error = exc
    else:
        raise AssertionError("expected all failed document inputs to fail the pipeline")

    assert "unreadable required input" in str(error)
    assert error.result is not None
    assert error.result.workbook_count == 0
    assert error.result.document_count == 0
    assert {(diagnostic.reason, diagnostic.file_id) for diagnostic in error.diagnostics} >= {
        ("no_extractable_text", "empty-pdf"),
        ("document_conversion_failed", "corrupt-docx"),
    }


def test_pipeline_extracts_and_stores_document_images_with_fake_object_store(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run
    from lore_splitter.storage import FakeObjectToastStore

    input_root = tmp_path / "fixtures"
    fixtures = create_image_contract_fixtures(input_root / "staging" / "files")
    manifest_path = _write_manifest(
        tmp_path,
        [
            _document_manifest_record("docx-images", fixtures.docx),
            _document_manifest_record("pptx-images", fixtures.pptx),
            _document_manifest_record("pdf-images", fixtures.pdf),
            _document_manifest_record("scan-images", fixtures.scanned_pdf),
        ],
    )
    object_store = FakeObjectToastStore()

    result = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out",
            storage_mode="dry_run",
            object_store=object_store,
        )
    )

    assert result.document_count == 4
    assert result.image_candidate_count > result.image_toast_count >= 1
    assert result.skipped_image_count >= 2
    assert result.image_storage_result_count == result.image_toast_count
    assert result.failed_image_storage_result_count == 0
    assert result.image_extraction_result is not None
    assert result.image_storage_results
    assert set(object_store.payloads_by_toast_id) == {
        storage_result.toast_id for storage_result in result.image_storage_results
    }
    assert all("schema_name" not in item.to_dict() for item in result.image_storage_results)
    run_manifest = _read_json(Path(result.artifact_paths["run_manifest"]))
    assert "image_storage_results" not in run_manifest
    assert all("image_toasts" not in bundle for bundle in run_manifest["bundles"])


def test_pipeline_writes_image_toast_references_and_manifest_ids(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    input_root = tmp_path / "fixtures"
    fixtures = create_image_contract_fixtures(input_root / "staging" / "files")
    manifest_path = _write_manifest(
        tmp_path,
        [_document_manifest_record("docx-images", fixtures.docx)],
    )

    result = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out",
            storage_mode="dry_run",
        )
    )

    assert result.document_count == 1
    assert result.image_toast_count >= 1
    run_manifest = _read_json(Path(result.artifact_paths["run_manifest"]))
    document_entry = next(entry for entry in run_manifest["bundles"] if entry["kind"] == "document")
    markdown = Path(document_entry["paths"]["markdown"]).read_text(encoding="utf-8")

    assert re.search(r"\[TOAST: toast_img_[0-9a-f]{20}\]", markdown)
    assert document_entry["image_toast_ids"] == [
        storage_result.toast_id for storage_result in result.image_storage_results
    ]
    assert document_entry["image_counts"]["stored"] == result.image_storage_result_count
    assert document_entry["image_counts"]["skipped"] == result.skipped_image_count
    assert "bucket" not in document_entry
    assert "object_key" not in document_entry


def test_pipeline_writes_bounded_and_full_image_metadata(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    input_root = tmp_path / "fixtures"
    fixtures = create_image_contract_fixtures(input_root / "staging" / "files")
    manifest_path = _write_manifest(
        tmp_path,
        [
            _document_manifest_record("docx-images", fixtures.docx),
            _document_manifest_record("scan-images", fixtures.scanned_pdf),
        ],
    )

    result = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out",
            storage_mode="dry_run",
        )
    )

    document_paths = result.artifact_paths["documents"]
    embedding_payloads = [_read_json(Path(paths["embedding_metadata"])) for paths in document_paths]
    full_payloads = [_read_json(Path(paths["full_metadata"])) for paths in document_paths]
    image_embedding_entries = [
        image for payload in embedding_payloads for image in payload.get("images", [])
    ]
    image_full_entries = [image for payload in full_payloads for image in payload.get("images", [])]
    skipped_images = [
        image for payload in full_payloads for image in payload.get("skipped_images", [])
    ]

    assert image_embedding_entries
    assert image_full_entries
    assert skipped_images
    assert all("bucket" not in image for image in image_embedding_entries)
    assert all("object_key" not in image for image in image_embedding_entries)
    assert all("payload" not in image for image in image_embedding_entries)
    assert all(image.get("storage", {}).get("bucket") for image in image_full_entries)
    assert all(image.get("storage", {}).get("object_key") for image in image_full_entries)
    assert {image["reason"] for image in skipped_images} >= {"full_page_raster"}


def test_pipeline_summary_includes_image_and_table_counters(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    input_root = tmp_path / "fixtures"
    workbook_path = input_root / "staging" / "files" / "workbook.xlsx"
    _write_sparse_sheet_workbook(workbook_path)
    fixtures = create_image_contract_fixtures(input_root / "staging" / "files")
    manifest_path = _write_manifest(
        tmp_path,
        [
            _manifest_record("workbook", workbook_path),
            _document_manifest_record("docx-images", fixtures.docx),
            _document_manifest_record("scan-images", fixtures.scanned_pdf),
        ],
    )

    result = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out",
            storage_mode="dry_run",
            toast_min_rows=1,
            toast_min_columns=1,
            toast_min_cells=1,
        )
    )
    summary = result.to_summary_dict()

    assert summary["document_count"] == 2
    assert summary["image_candidate_count"] == result.image_candidate_count
    assert summary["image_toast_count"] == result.image_toast_count
    assert summary["skipped_image_count"] == result.skipped_image_count
    assert summary["image_storage_result_count"] == result.image_storage_result_count
    assert (
        summary["failed_image_storage_result_count"]
        == result.failed_image_storage_result_count
        == 0
    )
    assert summary["toast_table_count"] == result.toast_table_count
    assert summary["storage_result_count"] == result.storage_result_count
    assert summary["failed_storage_result_count"] == 0


def test_pipeline_image_bucket_and_prefix_configure_storage_plans(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, run
    from lore_splitter.storage import (
        ImageToastStoragePlan,
        ImageToastStorageResult,
    )

    class CapturingObjectStore:
        def __init__(self) -> None:
            self.plans: list[ImageToastStoragePlan] = []

        def store_object(self, plan: ImageToastStoragePlan) -> ImageToastStorageResult:
            self.plans.append(plan)
            return ImageToastStorageResult.from_plan(plan, action="created")

    input_root = tmp_path / "fixtures"
    fixtures = create_image_contract_fixtures(input_root / "staging" / "files")
    manifest_path = _write_manifest(
        tmp_path,
        [_document_manifest_record("docx-images", fixtures.docx)],
    )
    store = CapturingObjectStore()

    result = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "out",
            storage_mode="dry_run",
            object_store=store,
            image_toast_bucket="operator-image-toast",
            image_toast_prefix="operator-prefix",
        )
    )

    assert store.plans
    assert {plan.bucket for plan in store.plans} == {"operator-image-toast"}
    assert all(plan.object_key.startswith("operator-prefix/") for plan in store.plans)
    full_metadata = [
        _read_json(Path(paths["full_metadata"]))
        for paths in result.artifact_paths["documents"]
    ]
    storage_entries = [
        image["storage"]
        for payload in full_metadata
        for image in payload.get("images", [])
    ]
    assert storage_entries
    assert {entry["bucket"] for entry in storage_entries} == {"operator-image-toast"}
    assert all(entry["object_key"].startswith("operator-prefix/") for entry in storage_entries)


def test_repeated_image_pipeline_runs_write_identical_references_and_manifest(
    tmp_path,
) -> None:
    from lore_splitter.pipeline import PipelineConfig, run

    input_root = tmp_path / "fixtures"
    fixtures = create_image_contract_fixtures(input_root / "staging" / "files")
    manifest_path = _write_manifest(
        tmp_path,
        [_document_manifest_record("docx-images", fixtures.docx)],
    )

    first = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "first",
            storage_mode="dry_run",
        )
    )
    second = run(
        PipelineConfig(
            manifest_path=Path(manifest_path),
            input_root=input_root,
            output_dir=tmp_path / "second",
            storage_mode="dry_run",
        )
    )

    assert _image_toast_references_from_documents(first) == _image_toast_references_from_documents(
        second
    )
    assert _manifest_without_output_root(first) == _manifest_without_output_root(second)


def test_pipeline_object_store_failure_raises_with_partial_image_result(tmp_path) -> None:
    from lore_splitter.pipeline import PipelineConfig, PipelineRunError, run
    from lore_splitter.storage import (
        ImageToastStoragePlan,
        ImageToastStorageResult,
    )

    class FailingObjectStore:
        def __init__(self) -> None:
            self.calls: list[ImageToastStoragePlan] = []

        def store_object(self, plan: ImageToastStoragePlan) -> ImageToastStorageResult:
            self.calls.append(plan)
            return ImageToastStorageResult.from_plan(
                plan,
                action="failed",
                diagnostics=(*plan.diagnostics, "fake_object_store_failure:boom"),
            )

    input_root = tmp_path / "fixtures"
    fixtures = create_image_contract_fixtures(input_root / "staging" / "files")
    manifest_path = _write_manifest(
        tmp_path,
        [_document_manifest_record("docx-images", fixtures.docx)],
    )
    object_store = FailingObjectStore()

    try:
        run(
            PipelineConfig(
                manifest_path=Path(manifest_path),
                input_root=input_root,
                output_dir=tmp_path / "out",
                storage_mode="dry_run",
                object_store=object_store,
            )
        )
    except PipelineRunError as exc:
        error = exc
    else:
        raise AssertionError("expected failed image storage to fail the pipeline")

    assert object_store.calls
    assert "image storage failed" in str(error)
    assert error.result is not None
    assert error.result.image_extraction_result is not None
    assert error.result.failed_image_storage_result_count == len(error.result.image_storage_results)
    assert error.result.error_count >= 1
    assert all(
        "table_name" not in storage_result.to_dict()
        for storage_result in error.result.image_storage_results
    )


def test_runner_veri_05_internal2_fixture_declares_222_records_and_3_22gb() -> None:
    rows = [
        json.loads(line)
        for line in (_TESTS_DIR / "fixtures" / "internal2_manifest.jsonl").read_text().splitlines()
        if line.strip()
    ]
    declared_bytes = sum(
        int(row.get("bytes") or row.get("size_bytes") or row.get("file_size") or 0)
        for row in rows
    )

    assert len(rows) == 222
    assert declared_bytes >= 3_220_000_000


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_sparse_sheet_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "SparseFallback"
    sheet["A1"] = "Sparse workbook"
    sheet["D1"] = "context"
    sheet["B3"] = "important note"
    sheet["D4"] = "owner"
    workbook.save(path)
    workbook.close()


def _document_manifest_record(file_id: str, path: Path) -> dict[str, object]:
    mime_type_by_suffix = {
        ".md": "text/markdown",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pdf": "application/pdf",
        ".zip": "application/zip",
    }
    size_bytes = path.stat().st_size if path.exists() else 100
    return {
        "source_id": "google-drive",
        "stream": "regulations",
        "file_id": file_id,
        "source_path": path.name,
        "object_path": f"/staging/files/{path.name}",
        "mime_type": mime_type_by_suffix[path.suffix],
        "size_bytes": size_bytes,
        "source_url": f"https://drive.example/{file_id}",
        "metadata": {"fixture": "document"},
    }


def _toast_ids_from_full_metadata(result) -> list[str]:
    return [
        table["toast_id"]
        for bundle in result.bundles
        for table in _read_json(bundle.full_metadata_path)["tables"]
        if table["classification"] == "toast"
    ]


def _toast_references_from_markdown(result) -> list[str]:
    return [
        reference
        for bundle in result.bundles
        for reference in re.findall(
            r"\[TOAST: toast_tbl_[0-9a-f]{20}\]",
            bundle.markdown_path.read_text(encoding="utf-8"),
        )
    ]


def _image_toast_references_from_documents(result) -> list[str]:
    return [
        reference
        for paths in result.artifact_paths["documents"]
        for reference in re.findall(
            r"\[TOAST: toast_img_[0-9a-f]{20}\]",
            Path(paths["markdown"]).read_text(encoding="utf-8"),
        )
    ]


def _manifest_without_output_root(result) -> dict[str, object]:
    manifest = _read_json(Path(result.artifact_paths["run_manifest"]))
    for entry in manifest["bundles"]:
        entry["paths"] = {key: Path(value).name for key, value in entry["paths"].items()}
        entry["metadata_paths"] = {
            key: Path(value).name for key, value in entry["metadata_paths"].items()
        }
    manifest["manifest_path"] = Path(manifest["manifest_path"]).name
    return manifest
