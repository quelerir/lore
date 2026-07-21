"""Markdown render helpers shared by storage tests.

NOTE(task-2): This module provides _table_data/_range helpers needed by storage tests.
Full render tests (render_workbook_markdown, etc.) will be added in Task 3.
"""
from __future__ import annotations

from pathlib import Path

from lore_splitter.contracts import SourceFile
from lore_splitter.markdown.contracts import TableData, XlsxTableLocation
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
