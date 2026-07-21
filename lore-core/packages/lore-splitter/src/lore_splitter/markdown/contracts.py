from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lore_splitter.contracts import ManifestDiagnostic, SourceFile
from lore_splitter.xlsx.contracts import CellRange


@dataclass(frozen=True)
class XlsxTableLocation:
    workbook_checksum: str
    sheet_name: str
    sheet_index: int
    range: CellRange
    header_row: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "workbook_checksum": self.workbook_checksum,
            "sheet_name": self.sheet_name,
            "sheet_index": self.sheet_index,
            "range": self.range.to_dict(),
            "header_row": self.header_row,
        }


@dataclass(frozen=True)
class MarkdownTableLocation:
    table_index: int
    line_start: int
    line_end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "table_index": self.table_index,
            "line_start": self.line_start,
            "line_end": self.line_end,
        }


@dataclass(frozen=True, init=False)
class TableData:
    source_file: SourceFile
    local_path: Path
    source_kind: str
    source_checksum: str
    table_index: int
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...] = ()
    warnings: tuple[str, ...] = ()
    xlsx: XlsxTableLocation | None = None
    markdown: MarkdownTableLocation | None = None

    def __init__(
        self,
        *,
        source_file: SourceFile,
        local_path: Path,
        columns: tuple[str, ...],
        source_kind: str = "workbook",
        source_checksum: str | None = None,
        table_index: int = 1,
        rows: tuple[tuple[Any, ...], ...] = (),
        warnings: tuple[str, ...] = (),
        xlsx: XlsxTableLocation | None = None,
        markdown: MarkdownTableLocation | None = None,
        workbook_checksum: str | None = None,
        sheet_name: str | None = None,
        sheet_index: int | None = None,
        range: CellRange | None = None,
        header_row: int | None = None,
    ) -> None:
        resolved_xlsx = xlsx
        if resolved_xlsx is None and workbook_checksum is not None:
            if sheet_name is None or sheet_index is None or range is None or header_row is None:
                raise ValueError("workbook table data requires sheet, range, and header metadata")
            resolved_xlsx = XlsxTableLocation(
                workbook_checksum=workbook_checksum,
                sheet_name=sheet_name,
                sheet_index=sheet_index,
                range=range,
                header_row=header_row,
            )
        resolved_checksum = source_checksum
        if resolved_checksum is None and resolved_xlsx is not None:
            resolved_checksum = resolved_xlsx.workbook_checksum
        if resolved_checksum is None:
            raise ValueError("table data requires source_checksum")

        object.__setattr__(self, "source_file", source_file)
        object.__setattr__(self, "local_path", local_path)
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "source_checksum", resolved_checksum)
        object.__setattr__(self, "table_index", table_index)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "xlsx", resolved_xlsx)
        object.__setattr__(self, "markdown", markdown)

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

    @property
    def workbook_checksum(self) -> str:
        if self.xlsx is None:
            return self.source_checksum
        return self.xlsx.workbook_checksum

    @property
    def sheet_name(self) -> str:
        if self.xlsx is None:
            raise AttributeError("table has no XLSX sheet metadata")
        return self.xlsx.sheet_name

    @property
    def sheet_index(self) -> int:
        if self.xlsx is None:
            raise AttributeError("table has no XLSX sheet metadata")
        return self.xlsx.sheet_index

    @property
    def range(self) -> CellRange:
        if self.xlsx is None:
            raise AttributeError("table has no XLSX range metadata")
        return self.xlsx.range

    @property
    def header_row(self) -> int:
        if self.xlsx is None:
            return 0
        return self.xlsx.header_row

    @property
    def data_row_offset(self) -> int:
        if self.xlsx is None:
            return 0
        return max(0, self.xlsx.header_row - self.xlsx.range.min_row)

    def source_location_dict(self) -> dict[str, Any]:
        if self.xlsx is not None:
            return {"xlsx": self.xlsx.to_dict()}
        if self.markdown is not None:
            return {"markdown": self.markdown.to_dict()}
        return {}

    def to_dict(self) -> dict[str, Any]:
        payload = {
            **self.source_file.identity_dict(),
            "local_path": str(self.local_path),
            "source_kind": self.source_kind,
            "source_checksum": self.source_checksum,
            "table_index": self.table_index,
            "columns": list(self.columns),
            "rows": [list(row) for row in self.rows],
            "warnings": list(self.warnings),
        }
        if self.xlsx is not None:
            payload.update(self.xlsx.to_dict())
            payload["xlsx"] = self.xlsx.to_dict()
        if self.markdown is not None:
            payload["markdown"] = self.markdown.to_dict()
        return payload


@dataclass(frozen=True)
class TableDataExtractionResult:
    tables: tuple[TableData, ...] = ()
    diagnostics: tuple[ManifestDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "tables": [table.to_dict() for table in self.tables],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    inferred_type: str
    semantic_hints: tuple[str, ...] = ()
    null_count: int = 0
    non_null_count: int = 0
    unique_values: tuple[Any, ...] = ()
    min_value: Any = None
    max_value: Any = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "inferred_type": self.inferred_type,
            "semantic_hints": list(self.semantic_hints),
            "null_count": self.null_count,
            "non_null_count": self.non_null_count,
            "unique_values": list(self.unique_values),
            "min_value": self.min_value,
            "max_value": self.max_value,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, init=False)
class TableProfile:
    source_file: SourceFile
    source_kind: str
    source_checksum: str
    table_index: int
    columns: tuple[str, ...]
    row_count: int
    column_count: int
    cell_count: int
    density: float
    column_profiles: tuple[ColumnProfile, ...] = ()
    warnings: tuple[str, ...] = ()
    xlsx: XlsxTableLocation | None = None
    markdown: MarkdownTableLocation | None = None

    def __init__(
        self,
        *,
        source_file: SourceFile,
        columns: tuple[str, ...],
        row_count: int,
        column_count: int,
        cell_count: int,
        density: float,
        source_kind: str = "workbook",
        source_checksum: str | None = None,
        table_index: int = 1,
        column_profiles: tuple[ColumnProfile, ...] = (),
        warnings: tuple[str, ...] = (),
        xlsx: XlsxTableLocation | None = None,
        markdown: MarkdownTableLocation | None = None,
        workbook_checksum: str | None = None,
        sheet_name: str | None = None,
        sheet_index: int | None = None,
        range: CellRange | None = None,
        header_row: int | None = None,
    ) -> None:
        resolved_xlsx = xlsx
        if resolved_xlsx is None and workbook_checksum is not None:
            if sheet_name is None or sheet_index is None or range is None or header_row is None:
                raise ValueError(
                    "workbook table profile requires sheet, range, and header metadata"
                )
            resolved_xlsx = XlsxTableLocation(
                workbook_checksum=workbook_checksum,
                sheet_name=sheet_name,
                sheet_index=sheet_index,
                range=range,
                header_row=header_row,
            )
        resolved_checksum = source_checksum
        if resolved_checksum is None and resolved_xlsx is not None:
            resolved_checksum = resolved_xlsx.workbook_checksum
        if resolved_checksum is None:
            raise ValueError("table profile requires source_checksum")

        object.__setattr__(self, "source_file", source_file)
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "source_checksum", resolved_checksum)
        object.__setattr__(self, "table_index", table_index)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "row_count", row_count)
        object.__setattr__(self, "column_count", column_count)
        object.__setattr__(self, "cell_count", cell_count)
        object.__setattr__(self, "density", density)
        object.__setattr__(self, "column_profiles", column_profiles)
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(self, "xlsx", resolved_xlsx)
        object.__setattr__(self, "markdown", markdown)

    @property
    def workbook_checksum(self) -> str:
        if self.xlsx is None:
            return self.source_checksum
        return self.xlsx.workbook_checksum

    @property
    def sheet_name(self) -> str:
        if self.xlsx is None:
            raise AttributeError("profile has no XLSX sheet metadata")
        return self.xlsx.sheet_name

    @property
    def sheet_index(self) -> int:
        if self.xlsx is None:
            raise AttributeError("profile has no XLSX sheet metadata")
        return self.xlsx.sheet_index

    @property
    def range(self) -> CellRange:
        if self.xlsx is None:
            raise AttributeError("profile has no XLSX range metadata")
        return self.xlsx.range

    @property
    def header_row(self) -> int:
        if self.xlsx is None:
            return 0
        return self.xlsx.header_row

    def to_dict(self) -> dict[str, Any]:
        payload = {
            **self.source_file.identity_dict(),
            "source_kind": self.source_kind,
            "source_checksum": self.source_checksum,
            "table_index": self.table_index,
            "columns": list(self.columns),
            "row_count": self.row_count,
            "column_count": self.column_count,
            "cell_count": self.cell_count,
            "density": self.density,
            "column_profiles": [profile.to_dict() for profile in self.column_profiles],
            "warnings": list(self.warnings),
        }
        if self.xlsx is not None:
            payload.update(self.xlsx.to_dict())
            payload["xlsx"] = self.xlsx.to_dict()
        if self.markdown is not None:
            payload["markdown"] = self.markdown.to_dict()
        return payload


@dataclass(frozen=True)
class ToastDecision:
    classification: str
    toast_id: str | None
    content_signature: str
    estimated_markdown_bytes: int
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    thresholds: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "toast_id": self.toast_id,
            "content_signature": self.content_signature,
            "estimated_markdown_bytes": self.estimated_markdown_bytes,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "thresholds": dict(self.thresholds or {}),
        }


@dataclass(frozen=True)
class WorkbookOutputBundle:
    bundle_id: str
    markdown_path: Path
    embedding_metadata_path: Path
    full_metadata_path: Path
    markdown: str
    embedding_metadata: dict[str, Any]
    full_metadata: dict[str, Any]

    @property
    def kind(self) -> str:
        return "workbook"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "paths": {
                "markdown": str(self.markdown_path),
                "embedding_metadata": str(self.embedding_metadata_path),
                "full_metadata": str(self.full_metadata_path),
            },
            "markdown": self.markdown,
            "embedding_metadata": self.embedding_metadata,
            "full_metadata": self.full_metadata,
        }


@dataclass(frozen=True)
class DocumentOutputBundle:
    bundle_id: str
    markdown_path: Path
    embedding_metadata_path: Path
    full_metadata_path: Path
    markdown: str
    embedding_metadata: dict[str, Any]
    full_metadata: dict[str, Any]

    @property
    def kind(self) -> str:
        return "document"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "paths": {
                "markdown": str(self.markdown_path),
                "embedding_metadata": str(self.embedding_metadata_path),
                "full_metadata": str(self.full_metadata_path),
            },
            "markdown": self.markdown,
            "embedding_metadata": self.embedding_metadata,
            "full_metadata": self.full_metadata,
        }


@dataclass(frozen=True)
class RunOutputManifest:
    manifest_path: Path
    bundles: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_path": str(self.manifest_path),
            "bundle_count": len(self.bundles),
            "bundles": list(self.bundles),
        }
