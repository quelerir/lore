from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from defusedxml import ElementTree
from openpyxl.utils.cell import range_boundaries

from lore_splitter.xlsx.contracts import CellRange

_SPREADSHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def extract_merged_ranges(workbook_path: str | Path, sheet_name: str) -> tuple[CellRange, ...]:
    """Read merged-cell metadata directly from XLSX XML without loading cell data."""
    with ZipFile(workbook_path) as archive:
        worksheet_path = _worksheet_path_for_sheet(archive, sheet_name)
        if worksheet_path is None:
            return ()

        worksheet = ElementTree.fromstring(archive.read(worksheet_path))

    ranges: list[CellRange] = []
    for merge_cell in worksheet.findall(f".//{{{_SPREADSHEET_NS}}}mergeCell"):
        a1_range = merge_cell.attrib.get("ref")
        if not a1_range:
            continue
        min_column, min_row, max_column, max_row = range_boundaries(a1_range)
        ranges.append(
            CellRange(
                min_row=min_row,
                max_row=max_row,
                min_column=min_column,
                max_column=max_column,
                a1_range=a1_range,
            )
        )
    return tuple(ranges)


def expand_merged_values(
    rows: Sequence[Sequence[Any]],
    merged_ranges: Sequence[CellRange],
) -> tuple[list[list[Any]], bool]:
    width = max((len(row) for row in rows), default=0)
    expanded = [list(row) + [None] * (width - len(row)) for row in rows]
    changed = False

    for merged_range in merged_ranges:
        if merged_range.min_row < 1 or merged_range.min_column < 1:
            continue
        if merged_range.min_row > len(expanded) or merged_range.min_column > width:
            continue

        top_left = expanded[merged_range.min_row - 1][merged_range.min_column - 1]
        for row_index in range(merged_range.min_row, min(merged_range.max_row, len(expanded)) + 1):
            for column_index in range(
                merged_range.min_column,
                min(merged_range.max_column, width) + 1,
            ):
                if row_index == merged_range.min_row and column_index == merged_range.min_column:
                    continue
                if expanded[row_index - 1][column_index - 1] != top_left:
                    expanded[row_index - 1][column_index - 1] = top_left
                    changed = True

    return expanded, changed


def _worksheet_path_for_sheet(archive: ZipFile, sheet_name: str) -> str | None:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationship_targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall(f"{{{_REL_NS}}}Relationship")
        if "Id" in relationship.attrib and "Target" in relationship.attrib
    }

    for sheet in workbook.findall(f".//{{{_SPREADSHEET_NS}}}sheet"):
        if sheet.attrib.get("name") != sheet_name:
            continue
        relationship_id = sheet.attrib.get(f"{{{_OFFICE_REL_NS}}}id")
        if relationship_id is None:
            return None
        target = relationship_targets.get(relationship_id)
        if target is None:
            return None
        return _normalize_worksheet_target(target)
    return None


def _normalize_worksheet_target(target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    if target.startswith("xl/"):
        return target
    return f"xl/{target}"
