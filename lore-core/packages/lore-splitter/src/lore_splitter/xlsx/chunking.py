"""Airflow-independent workbook region to retrieval-chunk composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lore_splitter.chunks import (
    Chunk,
    ChunkBudget,
    ChunkCoordinates,
    PayloadRef,
    build_chunk,
)
from lore_splitter.markdown.contracts import TableData, XlsxTableLocation
from lore_splitter.markdown.profile import profile_table
from lore_splitter.markdown.toast import (
    CLASSIFICATION_SKIPPED,
    CLASSIFICATION_TOAST,
    classify_table,
)
from lore_splitter.storage import build_table_storage_plan
from lore_splitter.xlsx.contracts import SheetRegion, WorkbookExtraction


@dataclass(frozen=True)
class WorkbookChunkResult:
    chunks: tuple[Chunk, ...]
    payload_plans: tuple[Any, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()


def build_workbook_chunks(
    *,
    run_id: str,
    file_id: str,
    workbook: WorkbookExtraction,
    pipeline_type: str = "workbook",
    budget: ChunkBudget | None = None,
) -> WorkbookChunkResult:
    """Convert ordered workbook regions into validated chunks and payload plans."""
    active_budget = budget or ChunkBudget()
    chunks: list[Chunk] = []
    payload_plans: list[Any] = []
    diagnostics: list[dict[str, Any]] = []
    occurrences: dict[str, int] = {}
    plans_by_payload: dict[str, Any] = {}
    ordinal = 0

    for sheet in sorted(workbook.sheets, key=lambda item: item.index):
        for region in sorted(sheet.regions, key=lambda item: _region_key(item)):
            if region.semantic_kind == "skipped":
                diagnostics.append(_diagnostic(sheet.name, region))
                continue
            coordinates = ChunkCoordinates(
                sheet=sheet.name,
                cell_range=region.source_bounds.a1_range,
            )
            if region.semantic_kind == "table":
                table = _table_data(workbook, region)
                profile = profile_table(table)
                decision = classify_table(table, profile)
                if decision.classification == CLASSIFICATION_SKIPPED:
                    diagnostics.append({
                        "code": "low_meaning_table",
                        "sheet": sheet.name,
                        "range": region.source_bounds.a1_range,
                        "reasons": list(decision.reasons),
                    })
                    continue
                if decision.classification == CLASSIFICATION_TOAST and decision.toast_id:
                    payload_id = decision.toast_id
                    if payload_id not in plans_by_payload:
                        plan = build_table_storage_plan(table, profile, decision)
                        plans_by_payload[payload_id] = plan
                        payload_plans.append(plan)
                    occurrence = occurrences.get(payload_id, 0)
                    occurrences[payload_id] = occurrence + 1
                    ref = PayloadRef(payload_id, "table", occurrence)
                    text = _payload_text(sheet.name, region, table, ref)
                    built = build_chunk(
                        run_id=run_id, file_id=file_id, ordinal=ordinal,
                        pipeline_type=pipeline_type, chunk_type="table_payload",
                        display_text=text, vector_text=text, fulltext=text,
                        coordinates=coordinates, payload_refs=(ref,), budget=active_budget,
                    )
                    new_chunks = _as_chunks(built)
                    chunks.extend(new_chunks)
                    ordinal += len(new_chunks)
                    continue
                text = _inline_table(table)
            else:
                text = region.text
            if not text.strip():
                continue
            text = _with_context(region, text)
            built = build_chunk(
                run_id=run_id, file_id=file_id, ordinal=ordinal,
                pipeline_type=pipeline_type,
                chunk_type="table" if region.semantic_kind == "table" else "text",
                display_text=text, vector_text=text, fulltext=text,
                coordinates=coordinates, budget=active_budget,
            )
            new_chunks = _as_chunks(built)
            chunks.extend(new_chunks)
            ordinal += len(new_chunks)
    return WorkbookChunkResult(tuple(chunks), tuple(payload_plans), tuple(diagnostics))


def _table_data(workbook: WorkbookExtraction, region: SheetRegion) -> TableData:
    candidate = region.candidate
    if candidate is None:
        raise ValueError("table_region_requires_candidate")
    return TableData(
        source_file=workbook.source_file,
        local_path=workbook.local_path,
        source_kind="workbook",
        source_checksum=workbook.workbook_checksum,
        table_index=candidate.sheet_index,
        columns=candidate.columns,
        rows=region.rows,
        xlsx=XlsxTableLocation(
            workbook_checksum=workbook.workbook_checksum,
            sheet_name=candidate.sheet_name,
            sheet_index=candidate.sheet_index,
            range=candidate.range,
            header_row=candidate.header_row,
        ),
        warnings=region.warnings,
    )


def _inline_table(table: TableData) -> str:
    lines = [
        "| " + " | ".join(table.columns) + " |",
        "| " + " | ".join("---" for _ in table.columns) + " |",
    ]
    for row in table.rows[table.data_row_offset + 1 :]:
        lines.append("| " + " | ".join("" if value is None else str(value) for value in row) + " |")
    return "\n".join(lines)


def _payload_text(sheet: str, region: SheetRegion, table: TableData, ref: PayloadRef) -> str:
    return (
        f"Table payload: {sheet} {region.source_bounds.a1_range}\n"
        f"Columns: {', '.join(table.columns)}\n"
        f"Rows: {max(0, len(table.rows) - 1)}\n{ref.compact()}"
    )


def _with_context(region: SheetRegion, text: str) -> str:
    return "\n".join((*region.context, text)) if region.context else text


def _diagnostic(sheet: str, region: SheetRegion) -> dict[str, Any]:
    return {
        "code": "low_meaning_fragment",
        "sheet": sheet,
        "range": region.source_bounds.a1_range,
        "warnings": list(region.warnings),
    }


def _region_key(region: SheetRegion) -> tuple[int, int, int, int]:
    bounds = region.source_bounds
    return bounds.min_row, bounds.min_column, bounds.max_row, bounds.max_column


def _as_chunks(value: Chunk | list[Chunk]) -> list[Chunk]:
    return value if isinstance(value, list) else [value]
