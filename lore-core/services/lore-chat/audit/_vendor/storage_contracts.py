from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class PayloadOccurrence:
    run_id: str
    file_id: str
    payload_id: str
    kind: str
    occurrence_ordinal: int
    checksum: str
    storage_identity: str
    coordinates: dict[str, Any]
    label: str = ""
    lane: str = ""

    def __post_init__(self) -> None:
        if self.occurrence_ordinal < 0 or len(self.checksum) != 64:
            raise StoragePlanError("invalid payload occurrence")

    def to_ref(self) -> dict[str, Any]:
        return {
            "payload_id": self.payload_id,
            "kind": self.kind,
            "occurrence_ordinal": self.occurrence_ordinal,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "file_id": self.file_id,
            **self.to_ref(),
            "checksum": self.checksum,
            "storage_identity": self.storage_identity,
            "coordinates": dict(self.coordinates),
            "label": self.label,
            "lane": self.lane,
        }


class StoragePlanError(ValueError):
    """Raised when a table TOAST cannot produce a safe storage plan."""


@dataclass(frozen=True)
class StorageColumn:
    logical_name: str
    sql_name: str
    inferred_type: str
    storage_type: str
    nullable: bool
    source_column_index: int
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_name": self.logical_name,
            "sql_name": self.sql_name,
            "inferred_type": self.inferred_type,
            "storage_type": self.storage_type,
            "nullable": self.nullable,
            "source_column_index": self.source_column_index,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class StorageRow:
    row_number: int
    source_row: int
    source_range: str
    values: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "source_row": self.source_row,
            "source_range": self.source_range,
            "values": dict(self.values),
        }


@dataclass(frozen=True)
class TableToastStoragePlan:
    toast_id: str
    schema_name: str
    table_name: str
    staging_table_name: str
    advisory_lock_key: int
    columns: tuple[StorageColumn, ...]
    rows: tuple[StorageRow, ...]
    source: dict[str, Any]
    workbook_checksum: str
    sheet: dict[str, Any]
    range: dict[str, Any]
    source_kind: str = "workbook"
    source_checksum: str = ""
    source_location: dict[str, Any] | None = None
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    content_signature: str = ""

    def __post_init__(self) -> None:
        if not self.source_checksum and self.workbook_checksum:
            object.__setattr__(self, "source_checksum", self.workbook_checksum)
        if self.source_location is None:
            location = {}
            if self.sheet or self.range:
                location = {
                    "xlsx": {
                        "workbook_checksum": self.workbook_checksum,
                        "sheet": dict(self.sheet),
                        "range": dict(self.range),
                    }
                }
            object.__setattr__(self, "source_location", location)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_constructor_dict(self) -> dict[str, Any]:
        return {
            "toast_id": self.toast_id,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "staging_table_name": self.staging_table_name,
            "advisory_lock_key": self.advisory_lock_key,
            "columns": self.columns,
            "rows": self.rows,
            "source": self.source,
            "workbook_checksum": self.workbook_checksum,
            "sheet": self.sheet,
            "range": self.range,
            "source_kind": self.source_kind,
            "source_checksum": self.source_checksum,
            "source_location": dict(self.source_location or {}),
            "warnings": self.warnings,
            "diagnostics": self.diagnostics,
            "content_signature": self.content_signature,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "toast_id": self.toast_id,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "staging_table_name": self.staging_table_name,
            "advisory_lock_key": self.advisory_lock_key,
            "columns": [column.to_dict() for column in self.columns],
            "rows": [row.to_dict() for row in self.rows],
            "source": dict(self.source),
            "workbook_checksum": self.workbook_checksum,
            "sheet": dict(self.sheet),
            "range": dict(self.range),
            "source_kind": self.source_kind,
            "source_checksum": self.source_checksum,
            "source_location": dict(self.source_location or {}),
            "warnings": list(self.warnings),
            "diagnostics": list(self.diagnostics),
            "content_signature": self.content_signature,
        }


@dataclass(frozen=True)
class TableToastStorageResult:
    toast_id: str
    schema_name: str
    table_name: str
    row_count: int
    action: str
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    source: dict[str, Any] | None = None
    source_kind: str | None = None
    source_checksum: str | None = None
    source_location: dict[str, Any] | None = None
    workbook_checksum: str | None = None
    sheet: dict[str, Any] | None = None
    range: dict[str, Any] | None = None

    @classmethod
    def from_plan(cls, plan: TableToastStoragePlan, *, action: str) -> TableToastStorageResult:
        return cls(
            toast_id=plan.toast_id,
            schema_name=plan.schema_name,
            table_name=plan.table_name,
            row_count=plan.row_count,
            action=action,
            warnings=plan.warnings,
            diagnostics=plan.diagnostics,
            source=plan.source,
            source_kind=plan.source_kind,
            source_checksum=plan.source_checksum,
            source_location=plan.source_location,
            workbook_checksum=plan.workbook_checksum,
            sheet=plan.sheet,
            range=plan.range,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "toast_id": self.toast_id,
            "schema_name": self.schema_name,
            "table_name": self.table_name,
            "row_count": self.row_count,
            "action": self.action,
            "warnings": list(self.warnings),
            "diagnostics": list(self.diagnostics),
            "source": dict(self.source or {}),
            "source_kind": self.source_kind,
            "source_checksum": self.source_checksum,
            "source_location": dict(self.source_location or {}),
            "workbook_checksum": self.workbook_checksum,
            "sheet": dict(self.sheet or {}),
            "range": dict(self.range or {}),
        }

    def to_manifest_entry(self) -> dict[str, Any]:
        return {
            "toast_id": self.toast_id,
            "schema": self.schema_name,
            "table_name": self.table_name,
            "row_count": self.row_count,
            "action": self.action,
            "warnings": list(self.warnings),
            "diagnostics": list(self.diagnostics),
            "source": dict(self.source or {}),
            "source_kind": self.source_kind,
            "source_checksum": self.source_checksum,
            "source_location": dict(self.source_location or {}),
            "workbook_checksum": self.workbook_checksum,
            "sheet": dict(self.sheet or {}),
            "range": dict(self.range or {}),
        }


@runtime_checkable
class TableToastStore(Protocol):
    def store_table(self, plan: TableToastStoragePlan) -> TableToastStorageResult: ...


@dataclass(frozen=True)
class ImageToastStoragePlan:
    toast_id: str
    bucket: str
    object_key: str
    content_type: str
    extension: str
    payload: bytes
    byte_size: int
    checksum_sha256: str
    source: dict[str, Any]
    source_kind: str
    source_checksum: str
    source_location: dict[str, Any]
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def to_constructor_dict(self) -> dict[str, Any]:
        return {
            "toast_id": self.toast_id,
            "bucket": self.bucket,
            "object_key": self.object_key,
            "content_type": self.content_type,
            "extension": self.extension,
            "payload": self.payload,
            "byte_size": self.byte_size,
            "checksum_sha256": self.checksum_sha256,
            "source": self.source,
            "source_kind": self.source_kind,
            "source_checksum": self.source_checksum,
            "source_location": self.source_location,
            "warnings": self.warnings,
            "diagnostics": self.diagnostics,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "toast_id": self.toast_id,
            "bucket": self.bucket,
            "object_key": self.object_key,
            "content_type": self.content_type,
            "extension": self.extension,
            "byte_size": self.byte_size,
            "checksum_sha256": self.checksum_sha256,
            "source": dict(self.source),
            "source_kind": self.source_kind,
            "source_checksum": self.source_checksum,
            "source_location": dict(self.source_location),
            "warnings": list(self.warnings),
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class ImageToastStorageResult:
    toast_id: str
    bucket: str
    object_key: str
    content_type: str
    extension: str
    byte_size: int
    checksum_sha256: str
    action: str
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    source: dict[str, Any] | None = None
    source_kind: str | None = None
    source_checksum: str | None = None
    source_location: dict[str, Any] | None = None

    @classmethod
    def from_plan(
        cls,
        plan: ImageToastStoragePlan,
        *,
        action: str,
        diagnostics: tuple[str, ...] | None = None,
    ) -> ImageToastStorageResult:
        return cls(
            toast_id=plan.toast_id,
            bucket=plan.bucket,
            object_key=plan.object_key,
            content_type=plan.content_type,
            extension=plan.extension,
            byte_size=plan.byte_size,
            checksum_sha256=plan.checksum_sha256,
            action=action,
            warnings=plan.warnings,
            diagnostics=diagnostics if diagnostics is not None else plan.diagnostics,
            source=plan.source,
            source_kind=plan.source_kind,
            source_checksum=plan.source_checksum,
            source_location=plan.source_location,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "toast_id": self.toast_id,
            "bucket": self.bucket,
            "object_key": self.object_key,
            "content_type": self.content_type,
            "extension": self.extension,
            "byte_size": self.byte_size,
            "checksum_sha256": self.checksum_sha256,
            "action": self.action,
            "warnings": list(self.warnings),
            "diagnostics": list(self.diagnostics),
            "source": dict(self.source or {}),
            "source_kind": self.source_kind,
            "source_checksum": self.source_checksum,
            "source_location": dict(self.source_location or {}),
        }


@runtime_checkable
class ObjectToastStore(Protocol):
    def store_object(self, plan: ImageToastStoragePlan) -> ImageToastStorageResult: ...
