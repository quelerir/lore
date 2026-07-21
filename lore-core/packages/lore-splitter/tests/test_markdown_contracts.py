from pathlib import Path

from lore_splitter.contracts import SourceFile
from lore_splitter.markdown import (
    ColumnProfile,
    DocumentOutputBundle,
    MarkdownTableLocation,
    RunOutputManifest,
    TableData,
    TableProfile,
    ToastDecision,
    WorkbookOutputBundle,
    XlsxTableLocation,
)
from lore_splitter.xlsx import CellRange


def _source_file() -> SourceFile:
    return SourceFile(
        source_id="google-drive",
        stream="regulations",
        file_id="file-123",
        source_path="Finance/report.xlsx",
        object_path="/staging/files/report__file-123.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=4096,
    )


def test_table_data_serializes_source_identity_range_columns_rows_and_warnings() -> None:
    table_data = TableData(
        source_file=_source_file(),
        local_path=Path("/tmp/materialized/staging/files/report__file-123.xlsx"),
        workbook_checksum="a" * 64,
        sheet_name="Summary",
        sheet_index=1,
        range=CellRange(2, 4, 1, 3, "A2:C4"),
        header_row=2,
        columns=("Region", "Amount", "Updated"),
        rows=(
            ("Region", "Amount", "Updated"),
            ("North", 125.5, "2026-01-15"),
            ("South", None, "2026-01-16"),
        ),
        warnings=("merged_cells_expanded", "duplicate_headers"),
    )

    assert table_data.to_dict() == {
        "source_id": "google-drive",
        "stream": "regulations",
        "file_id": "file-123",
        "source_path": "Finance/report.xlsx",
        "object_path": "/staging/files/report__file-123.xlsx",
        "local_path": "/tmp/materialized/staging/files/report__file-123.xlsx",
        "source_kind": "workbook",
        "source_checksum": "a" * 64,
        "table_index": 1,
        "workbook_checksum": "a" * 64,
        "sheet_name": "Summary",
        "sheet_index": 1,
        "range": {
            "min_row": 2,
            "max_row": 4,
            "min_column": 1,
            "max_column": 3,
            "a1_range": "A2:C4",
        },
        "header_row": 2,
        "columns": ["Region", "Amount", "Updated"],
        "rows": [
            ["Region", "Amount", "Updated"],
            ["North", 125.5, "2026-01-15"],
            ["South", None, "2026-01-16"],
        ],
        "xlsx": {
            "workbook_checksum": "a" * 64,
            "sheet_name": "Summary",
            "sheet_index": 1,
            "range": {
                "min_row": 2,
                "max_row": 4,
                "min_column": 1,
                "max_column": 3,
                "a1_range": "A2:C4",
            },
            "header_row": 2,
        },
        "warnings": ["merged_cells_expanded", "duplicate_headers"],
    }


def test_table_location_contracts_serialize_typed_source_specific_metadata() -> None:
    xlsx = XlsxTableLocation(
        workbook_checksum="a" * 64,
        sheet_name="Summary",
        sheet_index=1,
        range=CellRange(2, 4, 1, 3, "A2:C4"),
        header_row=2,
    )
    markdown = MarkdownTableLocation(table_index=3, line_start=12, line_end=16)

    assert xlsx.to_dict() == {
        "workbook_checksum": "a" * 64,
        "sheet_name": "Summary",
        "sheet_index": 1,
        "range": {
            "min_row": 2,
            "max_row": 4,
            "min_column": 1,
            "max_column": 3,
            "a1_range": "A2:C4",
        },
        "header_row": 2,
    }
    assert markdown.to_dict() == {"table_index": 3, "line_start": 12, "line_end": 16}


def test_column_profile_serializes_inference_counts_aggregates_hints_and_warnings() -> None:
    profile = ColumnProfile(
        name="Amount",
        inferred_type="number",
        semantic_hints=("measure", "currency"),
        null_count=1,
        non_null_count=2,
        unique_values=("$10.00", "$25.50"),
        min_value=10.0,
        max_value=25.5,
        warnings=("formula_like_text",),
    )

    assert profile.to_dict() == {
        "name": "Amount",
        "inferred_type": "number",
        "semantic_hints": ["measure", "currency"],
        "null_count": 1,
        "non_null_count": 2,
        "unique_values": ["$10.00", "$25.50"],
        "min_value": 10.0,
        "max_value": 25.5,
        "warnings": ["formula_like_text"],
    }


def test_table_profile_serializes_dimensions_density_profiles_and_lineage() -> None:
    column_profile = ColumnProfile(
        name="Region",
        inferred_type="text",
        semantic_hints=("dimension",),
        null_count=0,
        non_null_count=2,
        unique_values=("North", "South"),
    )
    profile = TableProfile(
        source_file=_source_file(),
        workbook_checksum="a" * 64,
        sheet_name="Summary",
        sheet_index=1,
        range=CellRange(2, 4, 1, 2, "A2:B4"),
        header_row=2,
        columns=("Region", "Amount"),
        row_count=3,
        column_count=2,
        cell_count=6,
        density=0.833333,
        column_profiles=(column_profile,),
        warnings=("duplicate_headers", "merged_cells_expanded"),
    )

    assert profile.to_dict() == {
        "source_id": "google-drive",
        "stream": "regulations",
        "file_id": "file-123",
        "source_path": "Finance/report.xlsx",
        "object_path": "/staging/files/report__file-123.xlsx",
        "source_kind": "workbook",
        "source_checksum": "a" * 64,
        "table_index": 1,
        "workbook_checksum": "a" * 64,
        "sheet_name": "Summary",
        "sheet_index": 1,
        "range": {
            "min_row": 2,
            "max_row": 4,
            "min_column": 1,
            "max_column": 2,
            "a1_range": "A2:B4",
        },
        "header_row": 2,
        "columns": ["Region", "Amount"],
        "row_count": 3,
        "column_count": 2,
        "cell_count": 6,
        "density": 0.833333,
        "column_profiles": [column_profile.to_dict()],
        "xlsx": {
            "workbook_checksum": "a" * 64,
            "sheet_name": "Summary",
            "sheet_index": 1,
            "range": {
                "min_row": 2,
                "max_row": 4,
                "min_column": 1,
                "max_column": 2,
                "a1_range": "A2:B4",
            },
            "header_row": 2,
        },
        "warnings": ["duplicate_headers", "merged_cells_expanded"],
    }


def test_toast_decision_serializes_classification_signature_thresholds_and_reasons() -> None:
    decision = ToastDecision(
        classification="toast",
        toast_id="toast_tbl_0123456789abcdef",
        content_signature="f" * 64,
        estimated_markdown_bytes=4608,
        reasons=("estimated-markdown", "row-count"),
        warnings=("low_density",),
        thresholds={
            "max_inline_markdown_bytes": 4096,
            "max_inline_rows": 40,
            "max_inline_columns": 8,
            "max_inline_cells": 240,
            "min_meaningful_density": 0.15,
            "min_meaningful_data_cells": 2,
        },
    )

    assert decision.to_dict() == {
        "classification": "toast",
        "toast_id": "toast_tbl_0123456789abcdef",
        "content_signature": "f" * 64,
        "estimated_markdown_bytes": 4608,
        "reasons": ["estimated-markdown", "row-count"],
        "warnings": ["low_density"],
        "thresholds": {
            "max_inline_markdown_bytes": 4096,
            "max_inline_rows": 40,
            "max_inline_columns": 8,
            "max_inline_cells": 240,
            "min_meaningful_density": 0.15,
            "min_meaningful_data_cells": 2,
        },
    }


def test_output_bundle_and_run_manifest_serialize_paths_and_payloads() -> None:
    bundle = WorkbookOutputBundle(
        bundle_id="wb_0123456789abcdefabcd",
        markdown_path=Path("/tmp/out/wb_0123456789abcdefabcd.md"),
        embedding_metadata_path=Path("/tmp/out/wb_0123456789abcdefabcd.embedding.json"),
        full_metadata_path=Path("/tmp/out/wb_0123456789abcdefabcd.full.json"),
        markdown="# Workbook: Finance/report.xlsx\n",
        embedding_metadata={"workbook": {"workbook_checksum": "a" * 64}},
        full_metadata={"tables": []},
    )
    manifest = RunOutputManifest(
        manifest_path=Path("/tmp/out/run_manifest.json"),
        bundles=({"bundle_id": bundle.bundle_id},),
    )

    assert bundle.to_dict()["paths"] == {
        "markdown": "/tmp/out/wb_0123456789abcdefabcd.md",
        "embedding_metadata": "/tmp/out/wb_0123456789abcdefabcd.embedding.json",
        "full_metadata": "/tmp/out/wb_0123456789abcdefabcd.full.json",
    }
    assert manifest.to_dict() == {
        "manifest_path": "/tmp/out/run_manifest.json",
        "bundle_count": 1,
        "bundles": [{"bundle_id": "wb_0123456789abcdefabcd"}],
    }


def test_document_output_bundle_serializes_paths_kind_and_metadata_payloads() -> None:
    bundle = DocumentOutputBundle(
        bundle_id="doc_0123456789abcdefabcd",
        markdown_path=Path("/tmp/out/doc_0123456789abcdefabcd.md"),
        embedding_metadata_path=Path("/tmp/out/doc_0123456789abcdefabcd.embedding.json"),
        full_metadata_path=Path("/tmp/out/doc_0123456789abcdefabcd.full.json"),
        markdown="# Policy\n",
        embedding_metadata={"document": {"document_checksum": "b" * 64}},
        full_metadata={"document": {"warnings": []}},
    )

    assert bundle.kind == "document"
    assert bundle.to_dict()["paths"] == {
        "markdown": "/tmp/out/doc_0123456789abcdefabcd.md",
        "embedding_metadata": "/tmp/out/doc_0123456789abcdefabcd.embedding.json",
        "full_metadata": "/tmp/out/doc_0123456789abcdefabcd.full.json",
    }
    assert bundle.to_dict()["embedding_metadata"] == {
        "document": {"document_checksum": "b" * 64}
    }


def test_markdown_package_exports_only_stable_contract_symbols() -> None:
    import lore_splitter.markdown as markdown

    assert set(markdown.__all__) == {
        "ColumnProfile",
        "DocumentOutputBundle",
        "MarkdownTableLocation",
        "MarkdownTableExtractionResult",
        "MarkdownTableOccurrence",
        "MetadataConfig",
        "RunOutputManifest",
        "TableData",
        "TableDataExtractionResult",
        "TableProfile",
        "ToastDecision",
        "ToastThresholds",
        "WorkbookOutputBundle",
        "XlsxTableLocation",
        "build_document_output_bundle",
        "build_embedding_metadata",
        "build_full_metadata",
        "build_workbook_output_bundle",
        "classify_table",
        "content_signature",
        "extract_markdown_document_tables",
        "extract_table_data",
        "metadata_json_bytes",
        "profile_table",
        "render_workbook_markdown",
        "render_toast_reference",
        "toast_id",
        "write_document_outputs",
        "write_run_manifest",
        "write_workbook_outputs",
    }
    assert not any(name.startswith("_") for name in markdown.__all__)
