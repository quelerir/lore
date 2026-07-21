from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from lore_splitter.contracts import ManifestDiagnostic, SourceFile


@dataclass(frozen=True)
class CellRange:
    min_row: int
    max_row: int
    min_column: int
    max_column: int
    a1_range: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_row": self.min_row,
            "max_row": self.max_row,
            "min_column": self.min_column,
            "max_column": self.max_column,
            "a1_range": self.a1_range,
        }


RegionKind = Literal["scalar", "table", "skipped"]


@dataclass(frozen=True)
class SheetRegion:
    """Ordered semantic region; cell rows stay internal to the pure lane."""

    semantic_kind: RegionKind
    sheet_name: str
    sheet_index: int
    source_bounds: CellRange
    text: str = ""
    rows: tuple[tuple[Any, ...], ...] = ()
    candidate: TableCandidate | None = None
    context: tuple[str, ...] = ()
    merged_ranges: tuple[CellRange, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.semantic_kind == "table" and self.candidate is None:
            raise ValueError("table_region_requires_candidate")

    @property
    def kind(self) -> RegionKind:
        return self.semantic_kind

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "semantic_kind": self.semantic_kind,
            "sheet_name": self.sheet_name,
            "sheet_index": self.sheet_index,
            "source_bounds": self.source_bounds.to_dict(),
            "text": self.text,
            "context": list(self.context),
            "merged_ranges": [item.to_dict() for item in self.merged_ranges],
            "warnings": list(self.warnings),
        }
        if self.candidate is not None:
            payload["candidate"] = self.candidate.to_dict()
        return payload


@dataclass(frozen=True)
class SheetExtraction:
    name: str
    index: int
    hidden: bool
    max_row: int
    max_column: int
    merged_ranges: tuple[CellRange, ...] = ()
    table_candidates: tuple[Any, ...] = ()
    regions: tuple[SheetRegion, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "index": self.index,
            "hidden": self.hidden,
            "max_row": self.max_row,
            "max_column": self.max_column,
            "merged_ranges": [cell_range.to_dict() for cell_range in self.merged_ranges],
            "table_candidates": [
                candidate.to_dict() if hasattr(candidate, "to_dict") else candidate
                for candidate in self.table_candidates
            ],
        }
        if self.regions:
            payload["regions"] = [region.to_dict() for region in self.regions]
        if self.warnings:
            payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class TableCandidate:
    workbook_checksum: str
    sheet_name: str
    sheet_index: int
    range: CellRange
    header_row: int
    columns: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "workbook_checksum": self.workbook_checksum,
            "sheet_name": self.sheet_name,
            "sheet_index": self.sheet_index,
            "range": self.range.to_dict(),
            "header_row": self.header_row,
            "columns": list(self.columns),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class WorkbookExtraction:
    source_file: SourceFile
    local_path: Path
    workbook_checksum: str
    sheets: tuple[SheetExtraction, ...] = ()

    @property
    def source_id(self) -> str:
        return self.source_file.source_id

    @property
    def stream(self) -> str:
        return self.source_file.stream

    @property
    def file_id(self) -> str:
        return self.source_file.file_id

    @property
    def source_path(self) -> str:
        return self.source_file.source_path

    @property
    def object_path(self) -> str:
        return self.source_file.object_path

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.source_file.identity_dict(),
            "local_path": str(self.local_path),
            "workbook_checksum": self.workbook_checksum,
            "sheets": [sheet.to_dict() for sheet in self.sheets],
        }


@dataclass(frozen=True)
class WorkbookExtractionResult:
    workbooks: tuple[WorkbookExtraction, ...] = ()
    diagnostics: tuple[ManifestDiagnostic, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workbooks": [workbook.to_dict() for workbook in self.workbooks],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }
