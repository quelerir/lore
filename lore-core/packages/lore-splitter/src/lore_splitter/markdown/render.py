from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lore_splitter.markdown.contracts import (
    TableData,
    TableProfile,
    ToastDecision,
)
from lore_splitter.markdown.toast import (
    CLASSIFICATION_INLINE,
    CLASSIFICATION_SKIPPED,
    CLASSIFICATION_TOAST,
    render_toast_reference,
)
from lore_splitter.xlsx.contracts import WorkbookExtraction


def render_workbook_markdown(
    workbook: WorkbookExtraction,
    tables: Sequence[TableData],
    profiles: Sequence[TableProfile],
    decisions: Sequence[ToastDecision],
    *,
    sheet_scalar_text: Mapping[str, Sequence[str]] | None = None,
) -> str:
    table_entries = _table_entries(tables, profiles, decisions)
    scalar_text = sheet_scalar_text or {}
    lines: list[str] = [f"# Workbook: {workbook.source_path}", ""]

    for sheet in workbook.sheets:
        heading = f"## Sheet {sheet.index}: {sheet.name}"
        if sheet.hidden:
            heading += " (hidden sheet)"
        lines.extend([heading, ""])
        if sheet.hidden:
            lines.extend(["> Warning: hidden sheet", ""])

        for text in scalar_text.get(sheet.name, ()):
            normalized = _normalize_text(text)
            if normalized:
                lines.extend([normalized, ""])

        for candidate in sheet.table_candidates:
            entry = table_entries.get((sheet.index, candidate.range.a1_range))
            if entry is None:
                continue
            table, _profile, decision = entry
            if decision.classification == CLASSIFICATION_SKIPPED:
                continue
            if decision.classification == CLASSIFICATION_TOAST:
                reference = render_toast_reference(decision)
                if reference:
                    lines.extend([reference, ""])
                continue
            if decision.classification == CLASSIFICATION_INLINE:
                lines.extend(_render_pipe_table(table))
                lines.append("")

    return _trim_markdown(lines)


def _table_entries(
    tables: Sequence[TableData],
    profiles: Sequence[TableProfile],
    decisions: Sequence[ToastDecision],
) -> dict[tuple[int, str], tuple[TableData, TableProfile, ToastDecision]]:
    entries: dict[tuple[int, str], tuple[TableData, TableProfile, ToastDecision]] = {}
    for table, profile, decision in zip(tables, profiles, decisions, strict=True):
        if table.xlsx is None:
            continue
        entries[(table.xlsx.sheet_index, table.xlsx.range.a1_range)] = (table, profile, decision)
    return entries


def _render_pipe_table(table: TableData) -> list[str]:
    columns = tuple(_markdown_cell(column) for column in table.columns)
    lines = [_markdown_row(columns), _markdown_row(tuple("---" for _ in columns))]
    for row in _data_rows(table):
        values = tuple(
            _markdown_cell(row[index] if index < len(row) else None)
            for index in range(len(table.columns))
        )
        lines.append(_markdown_row(values))
    return lines


def _data_rows(table: TableData) -> tuple[tuple[Any, ...], ...]:
    return table.rows[table.data_row_offset + 1 :]


def _markdown_row(values: tuple[str, ...]) -> str:
    return "| " + " | ".join(values) + " |"


def _markdown_cell(value: Any) -> str:
    normalized = "" if _is_blank(value) else str(value)
    return _normalize_text(normalized).replace("\\", "\\\\").replace("|", "\\|")


def _normalize_text(value: str) -> str:
    return " ".join(str(value).replace("\r\n", "\n").replace("\r", "\n").splitlines()).strip()


def _trim_markdown(lines: list[str]) -> str:
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")
