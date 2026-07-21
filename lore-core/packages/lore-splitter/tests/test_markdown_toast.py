from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from lore_splitter.contracts import SourceFile
from lore_splitter.markdown import (
    MarkdownTableLocation,
    TableData,
    ToastThresholds,
    XlsxTableLocation,
    profile_table,
)
from lore_splitter.markdown.toast import (
    CLASSIFICATION_INLINE,
    CLASSIFICATION_SKIPPED,
    CLASSIFICATION_TOAST,
    CLASSIFICATIONS,
    classify_table,
    content_signature,
    render_toast_reference,
    toast_id,
)
from lore_splitter.xlsx import CellRange


def test_toast_thresholds_expose_conservative_internal_defaults() -> None:
    thresholds = ToastThresholds()

    assert thresholds.max_inline_markdown_bytes == 4096
    assert thresholds.max_inline_rows == 40
    assert thresholds.max_inline_columns == 8
    assert thresholds.max_inline_cells == 240
    assert thresholds.min_meaningful_density == 0.15
    assert thresholds.min_meaningful_data_cells == 2
    assert thresholds.to_dict() == {
        "max_inline_markdown_bytes": 4096,
        "max_inline_rows": 40,
        "max_inline_columns": 8,
        "max_inline_cells": 240,
        "min_meaningful_density": 0.15,
        "min_meaningful_data_cells": 2,
    }


def test_toast_classifications_are_limited_to_inline_toast_and_skipped() -> None:
    assert CLASSIFICATION_INLINE == "inline"
    assert CLASSIFICATION_TOAST == "toast"
    assert CLASSIFICATION_SKIPPED == "skipped"
    assert CLASSIFICATIONS == frozenset({"inline", "toast", "skipped"})


def test_content_signature_and_toast_id_are_deterministic() -> None:
    first = _table_data(
        rows=(
            ("Name", "Amount", "Active", "Updated", "Formula"),
            ("North", Decimal("10.50"), True, date(2026, 1, 15), "=SUM(B2:B2)"),
            ("South", 25, False, datetime(2026, 1, 16, 9, 30), None),
        )
    )
    second = _table_data(
        rows=(
            ("Name", "Amount", "Active", "Updated", "Formula"),
            ("North", Decimal("10.50"), True, date(2026, 1, 15), "=SUM(B2:B2)"),
            ("South", 25, False, datetime(2026, 1, 16, 9, 30), ""),
        )
    )

    first_signature = content_signature(first, profile_table(first))
    second_signature = content_signature(second, profile_table(second))

    assert first_signature == second_signature
    assert toast_id(first_signature) == toast_id(second_signature)
    assert re.fullmatch(r"toast_tbl_[0-9a-f]{20}", toast_id(first_signature))


def test_content_change_changes_signature_and_toast_id() -> None:
    original = _table_data(rows=(("Name", "Amount"), ("North", 10), ("South", 25)))
    changed = _table_data(rows=(("Name", "Amount"), ("North", 10), ("South", 26)))

    original_signature = content_signature(original, profile_table(original))
    changed_signature = content_signature(changed, profile_table(changed))

    assert original_signature != changed_signature
    assert toast_id(original_signature) != toast_id(changed_signature)


def test_lineage_only_changes_do_not_change_primary_signature_or_toast_id() -> None:
    original = _table_data(rows=(("Name", "Amount"), ("North", 10), ("South", 25)))
    relocated = _table_data(
        rows=(("Name", "Amount"), ("North", 10), ("South", 25)),
        source_path="Archive/report-renamed.xlsx",
        object_path="/staging/files/renamed__file-456.xlsx",
        workbook_checksum="b" * 64,
        sheet_name="Moved",
        sheet_index=3,
        cell_range=CellRange(7, 9, 4, 5, "D7:E9"),
    )

    original_signature = content_signature(original, profile_table(original))
    relocated_signature = content_signature(relocated, profile_table(relocated))

    assert original_signature == relocated_signature
    assert toast_id(original_signature) == toast_id(relocated_signature)


def test_markdown_table_location_changes_do_not_change_primary_signature_or_toast_id() -> None:
    original = _markdown_table_data(
        rows=(("Name", "Amount"), ("North", 10), ("South", 25)),
        markdown=MarkdownTableLocation(table_index=1, line_start=4, line_end=7),
    )
    relocated = _markdown_table_data(
        rows=(("Name", "Amount"), ("North", 10), ("South", 25)),
        source_path="Archive/policy-renamed.md",
        object_path="/staging/files/policy-renamed__doc-456.md",
        source_checksum="e" * 64,
        markdown=MarkdownTableLocation(table_index=9, line_start=80, line_end=83),
    )

    original_signature = content_signature(original, profile_table(original))
    relocated_signature = content_signature(relocated, profile_table(relocated))

    assert original.source_kind == "markdown"
    assert original_signature == relocated_signature
    assert toast_id(original_signature) == toast_id(relocated_signature)


def test_small_meaningful_table_classifies_inline_with_content_signature() -> None:
    table = _table_data(rows=(("Region", "Amount"), ("North", 10), ("South", 25)))
    profile = profile_table(table)

    decision = classify_table(table, profile)

    assert decision.classification == "inline"
    assert decision.toast_id is None
    assert decision.content_signature == content_signature(table, profile)
    assert decision.estimated_markdown_bytes > 0
    assert decision.reasons == ()
    assert decision.thresholds == ToastThresholds().to_dict()


def test_large_estimated_markdown_classifies_toast_and_renders_id_only_reference() -> None:
    table = _table_data(
        rows=(
            ("Region", "Narrative"),
            ("North", "long narrative cell " * 6),
            ("South", "another long narrative cell " * 6),
        )
    )
    profile = profile_table(table)

    decision = classify_table(
        table,
        profile,
        thresholds=ToastThresholds(max_inline_markdown_bytes=80),
    )
    reference = render_toast_reference(decision)

    assert decision.classification == "toast"
    assert decision.toast_id is not None
    assert "estimated-markdown" in decision.reasons
    assert reference == f"[TOAST: {decision.toast_id}]"
    assert table.sheet_name not in reference
    assert table.range.a1_range not in reference
    assert "3x2" not in reference
    assert "Region" not in reference
    assert "Narrative" not in reference


def test_low_meaning_fragment_classifies_skipped_with_traceable_reason_and_warning() -> None:
    table = _table_data(rows=(("Column_1", "Column_2"), ("", None)))
    profile = profile_table(table)

    decision = classify_table(table, profile)

    assert decision.classification == "skipped"
    assert decision.toast_id is None
    assert "low-meaning-content" in decision.reasons
    assert "low_meaning_table" in decision.warnings
    assert render_toast_reference(decision) == ""


def _table_data(
    *,
    rows: tuple[tuple[object, ...], ...],
    columns: tuple[str, ...] | None = None,
    source_path: str = "Finance/report.xlsx",
    object_path: str = "/staging/files/report__file-123.xlsx",
    workbook_checksum: str = "a" * 64,
    sheet_name: str = "Summary",
    sheet_index: int = 1,
    cell_range: CellRange | None = None,
) -> TableData:
    resolved_columns = columns or tuple(str(value) for value in rows[0])
    resolved_range = cell_range or CellRange(
        1,
        len(rows),
        1,
        len(resolved_columns),
        f"A1:{chr(64 + len(resolved_columns))}{len(rows)}",
    )
    return TableData(
        source_file=SourceFile(
            source_id="google-drive",
            stream="regulations",
            file_id="file-123",
            source_path=source_path,
            object_path=object_path,
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=4096,
        ),
        local_path=Path("/tmp/materialized/staging/files/report__file-123.xlsx"),
        source_kind="workbook",
        source_checksum=workbook_checksum,
        table_index=1,
        columns=resolved_columns,
        rows=rows,
        xlsx=XlsxTableLocation(
            workbook_checksum=workbook_checksum,
            sheet_name=sheet_name,
            sheet_index=sheet_index,
            range=resolved_range,
            header_row=resolved_range.min_row,
        ),
    )


def _markdown_table_data(
    *,
    rows: tuple[tuple[object, ...], ...],
    source_path: str = "Finance/policy.md",
    object_path: str = "/staging/files/policy__doc-123.md",
    source_checksum: str = "d" * 64,
    markdown: MarkdownTableLocation,
) -> TableData:
    return TableData(
        source_file=SourceFile(
            source_id="google-drive",
            stream="regulations",
            file_id="doc-123",
            source_path=source_path,
            object_path=object_path,
            mime_type="text/markdown",
            size_bytes=2048,
        ),
        local_path=Path("/tmp/materialized/staging/files/policy__doc-123.md"),
        source_kind="markdown",
        source_checksum=source_checksum,
        table_index=markdown.table_index,
        columns=tuple(str(value) for value in rows[0]),
        rows=rows,
        markdown=markdown,
    )
