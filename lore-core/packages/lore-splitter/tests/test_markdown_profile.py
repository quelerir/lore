from __future__ import annotations

from datetime import date
from pathlib import Path

from lore_splitter.contracts import SourceFile
from lore_splitter.markdown import (
    MarkdownTableLocation,
    TableData,
    XlsxTableLocation,
    profile_table,
)
from lore_splitter.xlsx import CellRange


def test_profile_table_infers_types_counts_uniques_min_max_and_density() -> None:
    table = _table_data(
        columns=("Name", "Amount", "Active", "Updated", "Notes"),
        rows=(
            ("Name", "Amount", "Active", "Updated", "Notes"),
            ("North", 10.5, True, date(2026, 1, 15), "ok"),
            ("South", 25, False, date(2026, 1, 16), ""),
            ("North", None, True, None, None),
        ),
    )

    profile = profile_table(table)

    assert profile.row_count == 4
    assert profile.column_count == 5
    assert profile.cell_count == 20
    assert profile.density == 0.8
    assert [column.inferred_type for column in profile.column_profiles] == [
        "text",
        "number",
        "boolean",
        "date",
        "text",
    ]
    assert profile.column_profiles[0].unique_values == ("North", "South")
    assert profile.column_profiles[1].null_count == 1
    assert profile.column_profiles[1].non_null_count == 2
    assert profile.column_profiles[1].min_value == 10.5
    assert profile.column_profiles[1].max_value == 25
    assert profile.column_profiles[3].min_value == "2026-01-15"
    assert profile.column_profiles[3].max_value == "2026-01-16"


def test_profile_table_infers_blank_and_mixed_columns_with_warnings() -> None:
    table = _table_data(
        columns=("Blank", "Mixed", "Formula"),
        rows=(
            ("Blank", "Mixed", "Formula"),
            (None, "10", "=SUM(A1:A2)"),
            ("", 20, "literal"),
            (None, "text", None),
        ),
    )

    profile = profile_table(table)

    assert [column.inferred_type for column in profile.column_profiles] == [
        "blank",
        "mixed",
        "text",
    ]
    assert "all_blank_column" in profile.column_profiles[0].warnings
    assert "mixed_types" in profile.column_profiles[1].warnings
    assert "formula_like_text" in profile.column_profiles[2].warnings
    assert "all_blank_column" in profile.warnings
    assert "mixed_types" in profile.warnings
    assert "formula_like_text" in profile.warnings


def test_profile_table_preserves_header_and_merged_warnings_and_detects_low_meaning() -> None:
    table = _table_data(
        columns=("Column_1", "Column_2"),
        rows=(
            ("Column_1", "Column_2"),
            ("", None),
        ),
        warnings=("generated_headers", "merged_cells_expanded"),
    )

    profile = profile_table(table)

    assert profile.warnings == (
        "generated_headers",
        "merged_cells_expanded",
        "all_blank_column",
        "low_meaning_table",
    )


def test_profile_table_emits_deterministic_semantic_hints() -> None:
    table = _table_data(
        columns=("Customer ID", "Region", "Amount USD", "Discount %", "Invoice Date"),
        rows=(
            ("Customer ID", "Region", "Amount USD", "Discount %", "Invoice Date"),
            ("C-001", "North", 100.0, 0.10, "2026-02-01"),
            ("C-002", "South", 250.5, 0.05, "2026-02-02"),
        ),
    )

    profile = profile_table(table)

    hints = {column.name: column.semantic_hints for column in profile.column_profiles}
    assert hints == {
        "Customer ID": ("identifier", "dimension"),
        "Region": ("dimension",),
        "Amount USD": ("measure", "currency"),
        "Discount %": ("measure", "percentage"),
        "Invoice Date": ("date",),
    }


def test_profile_table_accepts_shared_markdown_table_contract_without_fake_xlsx_metadata() -> None:
    table = TableData(
        source_file=SourceFile(
            source_id="google-drive",
            stream="regulations",
            file_id="doc-123",
            source_path="Finance/policy.md",
            object_path="/staging/files/policy__doc-123.md",
            mime_type="text/markdown",
            size_bytes=2048,
        ),
        local_path=Path("/tmp/materialized/staging/files/policy__doc-123.md"),
        source_kind="markdown",
        source_checksum="d" * 64,
        table_index=2,
        columns=("Name", "Amount"),
        rows=(("Name", "Amount"), ("North", 10), ("South", 25)),
        markdown=MarkdownTableLocation(table_index=2, line_start=8, line_end=11),
    )

    profile = profile_table(table)
    payload = table.to_dict()
    profile_payload = profile.to_dict()

    assert table.source_kind == "markdown"
    assert table.source_checksum == "d" * 64
    assert table.table_index == 2
    assert table.xlsx is None
    assert payload["source_kind"] == "markdown"
    assert payload["markdown"] == {"table_index": 2, "line_start": 8, "line_end": 11}
    assert "sheet_name" not in payload
    assert "range" not in payload
    assert profile.source_kind == "markdown"
    assert profile.source_checksum == "d" * 64
    assert profile.markdown == table.markdown
    assert "sheet_name" not in profile_payload
    assert "range" not in profile_payload
    assert profile.row_count == 3
    assert profile.column_count == 2


def _table_data(
    *,
    columns: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
    warnings: tuple[str, ...] = (),
) -> TableData:
    return TableData(
        source_file=SourceFile(
            source_id="google-drive",
            stream="regulations",
            file_id="file-123",
            source_path="Finance/report.xlsx",
            object_path="/staging/files/report__file-123.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=4096,
        ),
        local_path=Path("/tmp/materialized/staging/files/report__file-123.xlsx"),
        source_kind="workbook",
        source_checksum="a" * 64,
        table_index=1,
        columns=columns,
        rows=rows,
        xlsx=XlsxTableLocation(
            workbook_checksum="a" * 64,
            sheet_name="Summary",
            sheet_index=1,
            range=CellRange(
                1,
                len(rows),
                1,
                len(columns),
                f"A1:{chr(64 + len(columns))}{len(rows)}",
            ),
            header_row=1,
        ),
        warnings=warnings,
    )
