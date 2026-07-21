from __future__ import annotations

from pathlib import Path

from lore_splitter.contracts import SourceFile
from lore_splitter.markdown import TableData, XlsxTableLocation, profile_table
from lore_splitter.markdown.render import render_workbook_markdown
from lore_splitter.markdown.toast import ToastThresholds, classify_table, toast_id
from lore_splitter.xlsx import (
    CellRange,
    SheetExtraction,
    TableCandidate,
    WorkbookExtraction,
)


def test_render_workbook_markdown_preserves_workbook_sheet_and_table_order() -> None:
    workbook = _workbook(
        sheets=(
            _sheet("Summary", 1, candidates=(_candidate("Summary", 1, "A2:B4"),)),
            _sheet("Lookup", 2, candidates=(_candidate("Lookup", 2, "A1:B3"),)),
        )
    )
    summary = _table_data("Summary", 1, "A2:B4")
    lookup = _table_data("Lookup", 2, "A1:B3", rows=(("Code", "Label"), ("A", "Active")))
    tables = (summary, lookup)
    profiles = tuple(profile_table(table) for table in tables)
    decisions = tuple(classify_table(table, profile) for table, profile in zip(tables, profiles))

    markdown = render_workbook_markdown(workbook, tables, profiles, decisions)

    assert markdown.index("# Workbook: Finance/report.xlsx") < markdown.index("## Sheet 1: Summary")
    assert markdown.index("## Sheet 1: Summary") < markdown.index("| Region | Amount |")
    assert markdown.index("| Region | Amount |") < markdown.index("## Sheet 2: Lookup")
    assert markdown.index("## Sheet 2: Lookup") < markdown.index("| Code | Label |")


def test_render_workbook_markdown_escapes_inline_pipe_tables_and_normalizes_newlines() -> None:
    workbook = _workbook(
        sheets=(_sheet("Summary", 1, candidates=(_candidate("Summary", 1, "A1:B3"),)),)
    )
    table = _table_data(
        "Summary",
        1,
        "A1:B3",
        rows=(
            ("Region", "Note"),
            ("North | East", "Line one\nLine two"),
            ("South", "plain"),
        ),
    )
    profile = profile_table(table)
    decision = classify_table(table, profile)

    markdown = render_workbook_markdown(workbook, (table,), (profile,), (decision,))

    assert "| Region | Note |" in markdown
    assert "| --- | --- |" in markdown
    assert "| North \\| East | Line one Line two |" in markdown
    assert "| South | plain |" in markdown


def test_render_workbook_markdown_uses_id_only_toast_references() -> None:
    workbook = _workbook(
        sheets=(_sheet("Summary", 1, candidates=(_candidate("Summary", 1, "A1:B3"),)),)
    )
    table = _table_data(
        "Summary",
        1,
        "A1:B3",
        rows=(
            ("Region", "Narrative"),
            ("North", "long narrative cell " * 6),
            ("South", "another long narrative cell " * 6),
        ),
    )
    profile = profile_table(table)
    decision = classify_table(
        table, profile, thresholds=ToastThresholds(max_inline_markdown_bytes=80)
    )

    markdown = render_workbook_markdown(workbook, (table,), (profile,), (decision,))

    assert decision.toast_id is not None
    assert f"[TOAST: {decision.toast_id}]" in markdown
    assert "A1:B3" not in markdown
    assert "3x2" not in markdown
    assert "Narrative" not in markdown


def test_render_workbook_markdown_omits_skipped_fragments() -> None:
    workbook = _workbook(
        sheets=(_sheet("Summary", 1, candidates=(_candidate("Summary", 1, "A1:B2"),)),)
    )
    table = _table_data(
        "Summary",
        1,
        "A1:B2",
        rows=(("Column_1", "Column_2"), ("", None)),
    )
    profile = profile_table(table)
    decision = classify_table(table, profile)

    markdown = render_workbook_markdown(workbook, (table,), (profile,), (decision,))

    assert decision.classification == "skipped"
    assert "Column_1" not in markdown
    assert "Column_2" not in markdown
    assert "[TOAST:" not in markdown


def test_render_workbook_markdown_includes_hidden_sheet_warning_context() -> None:
    workbook = _workbook(
        sheets=(
            _sheet("Visible", 1, candidates=(_candidate("Visible", 1, "A1:B3"),)),
            _sheet(
                "HiddenLookup", 2, hidden=True, candidates=(_candidate("HiddenLookup", 2, "A1:B3"),)
            ),
        )
    )
    visible = _table_data("Visible", 1, "A1:B3")
    hidden = _table_data("HiddenLookup", 2, "A1:B3", rows=(("Code", "Label"), ("A", "Active")))
    tables = (visible, hidden)
    profiles = tuple(profile_table(table) for table in tables)
    decisions = tuple(classify_table(table, profile) for table, profile in zip(tables, profiles))

    markdown = render_workbook_markdown(workbook, tables, profiles, decisions)

    assert markdown.index("## Sheet 1: Visible") < markdown.index(
        "## Sheet 2: HiddenLookup (hidden sheet)"
    )
    assert "> Warning: hidden sheet" in markdown


def test_render_workbook_markdown_preserves_available_scalar_sheet_text() -> None:
    workbook = _workbook(
        sheets=(
            _sheet("TitlePlusTable", 1, candidates=(_candidate("TitlePlusTable", 1, "A3:B5"),)),
        )
    )
    table = _table_data("TitlePlusTable", 1, "A3:B5")
    profile = profile_table(table)
    decision = classify_table(table, profile)

    markdown = render_workbook_markdown(
        workbook,
        (table,),
        (profile,),
        (decision,),
        sheet_scalar_text={"TitlePlusTable": ("A1: Quarterly sales note",)},
    )

    assert "A1: Quarterly sales note" in markdown
    assert markdown.index("A1: Quarterly sales note") < markdown.index("| Region | Amount |")


def test_render_workbook_fixture_contains_stable_toast_reference_shape() -> None:
    table = _table_data("Summary", 1, "A1:B3")
    profile = profile_table(table)
    decision = classify_table(
        table, profile, thresholds=ToastThresholds(max_inline_markdown_bytes=1)
    )

    assert decision.toast_id == toast_id(decision.content_signature)
    assert (
        render_workbook_markdown(
            _workbook(
                sheets=(_sheet("Summary", 1, candidates=(_candidate("Summary", 1, "A1:B3"),)),)
            ),
            (table,),
            (profile,),
            (decision,),
        ).count(f"[TOAST: {decision.toast_id}]")
        == 1
    )


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


def _workbook(*, sheets: tuple[SheetExtraction, ...]) -> WorkbookExtraction:
    return WorkbookExtraction(
        source_file=_source_file(),
        local_path=Path("/tmp/materialized/staging/files/report__file-123.xlsx"),
        workbook_checksum="a" * 64,
        sheets=sheets,
    )


def _sheet(
    name: str,
    index: int,
    *,
    hidden: bool = False,
    candidates: tuple[TableCandidate, ...],
) -> SheetExtraction:
    return SheetExtraction(
        name=name,
        index=index,
        hidden=hidden,
        max_row=5,
        max_column=2,
        table_candidates=candidates,
    )


def _candidate(sheet_name: str, sheet_index: int, a1_range: str) -> TableCandidate:
    cell_range = _range(a1_range)
    return TableCandidate(
        workbook_checksum="a" * 64,
        sheet_name=sheet_name,
        sheet_index=sheet_index,
        range=cell_range,
        header_row=cell_range.min_row,
        columns=("Region", "Amount"),
    )


def _table_data(
    sheet_name: str,
    sheet_index: int,
    a1_range: str,
    *,
    rows: tuple[tuple[object, ...], ...] = (("Region", "Amount"), ("North", 10), ("South", 25)),
) -> TableData:
    cell_range = _range(a1_range)
    return TableData(
        source_file=_source_file(),
        local_path=Path("/tmp/materialized/staging/files/report__file-123.xlsx"),
        source_kind="workbook",
        source_checksum="a" * 64,
        table_index=1,
        columns=tuple(str(value) for value in rows[0]),
        rows=rows,
        xlsx=XlsxTableLocation(
            workbook_checksum="a" * 64,
            sheet_name=sheet_name,
            sheet_index=sheet_index,
            range=cell_range,
            header_row=cell_range.min_row,
        ),
    )


def _range(a1_range: str) -> CellRange:
    start, end = a1_range.split(":")
    return CellRange(
        min_row=int(start[1:]),
        max_row=int(end[1:]),
        min_column=ord(start[0]) - 64,
        max_column=ord(end[0]) - 64,
        a1_range=a1_range,
    )
