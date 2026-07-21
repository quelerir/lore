from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from lore_core_domain.storage_contracts import (
    StorageColumn,
    StoragePlanError,
    StorageRow,
    TableToastStoragePlan,
)

if TYPE_CHECKING:
    from lore_splitter.markdown.contracts import (
        ColumnProfile,
        TableData,
        TableProfile,
        ToastDecision,
    )

DEFAULT_TOAST_SCHEMA = "splitter_toast"
TOAST_TABLE_RE = re.compile(r"^toast_tbl_[0-9a-f]{20}$")
_SQL_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_WARNING_DOWNGRADED = "storage_type_downgraded-to-text"


def validate_toast_table_name(name: str) -> str:
    if not TOAST_TABLE_RE.fullmatch(name):
        raise StoragePlanError(
            "invalid TOAST table name: expected internally generated "
            "toast_tbl_[0-9a-f]{20} table name"
        )
    return name


def validate_sql_identifier(name: str, *, label: str = "SQL identifier") -> str:
    if not _SQL_IDENTIFIER_RE.fullmatch(name):
        raise StoragePlanError(f"invalid {label}: expected a safe SQL identifier")
    return name


def validate_table_storage_plan(plan: TableToastStoragePlan) -> None:
    validate_toast_table_name(plan.toast_id)
    validate_toast_table_name(plan.table_name)
    if plan.table_name != plan.toast_id:
        raise StoragePlanError("plan table name must match TOAST id")
    validate_sql_identifier(plan.schema_name, label="schema name")
    expected_staging = _staging_table_name(plan.table_name, _plan_source_checksum(plan))
    if plan.staging_table_name != expected_staging:
        raise StoragePlanError(
            "invalid staging table name: expected deterministic TOAST staging table"
        )
    column_names = set()
    for column in plan.columns:
        validate_sql_identifier(column.sql_name, label=f"storage column name {column.sql_name!r}")
        column_names.add(column.sql_name)
    for row in plan.rows:
        unknown = set(row.values) - column_names
        if unknown:
            raise StoragePlanError(f"row contains values for unknown columns: {sorted(unknown)}")


def build_table_storage_plan(
    table: TableData,
    profile: TableProfile,
    decision: ToastDecision,
    *,
    schema_name: str = DEFAULT_TOAST_SCHEMA,
) -> TableToastStoragePlan:
    if decision.classification != "toast" or decision.toast_id is None:
        raise StoragePlanError("storage plans can only be built for toast decisions")
    table_name = validate_toast_table_name(decision.toast_id)
    schema = _validate_schema_name(schema_name)
    sql_names = _sql_column_names(table.columns)
    data_rows = _data_rows(table)

    columns: list[StorageColumn] = []
    warnings: list[str] = []
    for index, logical_name in enumerate(table.columns):
        profile_column = _profile_for_column(profile, logical_name, index)
        values = tuple(row[index] if index < len(row) else None for row in data_rows)
        storage_type, column_warnings = _storage_type_for_column(
            table_name,
            logical_name,
            profile_column,
            values,
        )
        warnings.extend(column_warnings)
        columns.append(
            StorageColumn(
                logical_name=logical_name,
                sql_name=sql_names[index],
                inferred_type=profile_column.inferred_type,
                storage_type=storage_type,
                nullable=profile_column.null_count > 0,
                source_column_index=index + 1,
                warnings=column_warnings,
            )
        )

    rows = tuple(_storage_rows(table, data_rows, tuple(columns)))
    diagnostics = (
        f"storage-plan-built:{table_name}:rows={len(rows)}:columns={len(columns)}",
    )
    return TableToastStoragePlan(
        toast_id=table_name,
        schema_name=schema,
        table_name=table_name,
        staging_table_name=_staging_table_name(table_name, table.source_checksum),
        advisory_lock_key=_advisory_lock_key(table_name),
        columns=tuple(columns),
        rows=rows,
        source=table.source_file.identity_dict(),
        workbook_checksum=table.xlsx.workbook_checksum if table.xlsx is not None else None,
        sheet={"name": table.xlsx.sheet_name, "index": table.xlsx.sheet_index}
        if table.xlsx is not None
        else {},
        range=table.xlsx.range.to_dict() if table.xlsx is not None else {},
        source_kind=table.source_kind,
        source_checksum=table.source_checksum,
        source_location=table.source_location_dict(),
        warnings=tuple(dict.fromkeys(warnings)),
        diagnostics=diagnostics,
        content_signature=decision.content_signature,
    )


def _validate_schema_name(name: str) -> str:
    return validate_sql_identifier(name, label="schema name")


def _data_rows(table: TableData) -> tuple[tuple[Any, ...], ...]:
    return table.rows[table.data_row_offset + 1 :]


def _profile_for_column(profile: TableProfile, logical_name: str, index: int) -> ColumnProfile:
    if index < len(profile.column_profiles):
        return profile.column_profiles[index]
    from lore_splitter.markdown.contracts import ColumnProfile

    return ColumnProfile(
        name=logical_name,
        inferred_type="text",
        null_count=profile.row_count,
    )


def _storage_type_for_column(
    table_name: str,
    logical_name: str,
    profile_column: ColumnProfile,
    values: tuple[Any, ...],
) -> tuple[str, tuple[str, ...]]:
    inferred_type = profile_column.inferred_type
    target_type = _storage_type_for_inferred_type(inferred_type)
    if target_type == "text":
        if inferred_type in {"mixed"}:
            return target_type, (
                _downgrade_warning(table_name, logical_name, inferred_type, "mixed-values"),
            )
        return target_type, ()
    invalid_reason = _first_invalid_reason(inferred_type, values)
    if invalid_reason is None:
        return target_type, ()
    return "text", (_downgrade_warning(table_name, logical_name, inferred_type, invalid_reason),)


def _storage_type_for_inferred_type(inferred_type: str) -> str:
    return {
        "boolean": "boolean",
        "date": "date",
        "number": "numeric",
    }.get(inferred_type, "text")


def _first_invalid_reason(inferred_type: str, values: tuple[Any, ...]) -> str | None:
    for value in values:
        if _is_blank(value):
            continue
        if inferred_type == "number" and not _is_number(value):
            return f"value {value!r} is not numeric"
        if inferred_type == "date" and _parse_date(value) is None:
            return f"value {value!r} is not date-like"
        if inferred_type == "boolean" and not isinstance(value, bool):
            return f"value {value!r} is not boolean"
    return None


def _downgrade_warning(
    table_name: str,
    logical_name: str,
    inferred_type: str,
    reason: str,
) -> str:
    return (
        f"{_WARNING_DOWNGRADED}:table={table_name}:column={logical_name}:"
        f"inferred_type={inferred_type}:reason={reason}"
    )


def _storage_rows(
    table: TableData,
    data_rows: tuple[tuple[Any, ...], ...],
    columns: tuple[StorageColumn, ...],
) -> tuple[StorageRow, ...]:
    first_data_row = _first_data_source_row(table)
    return tuple(
        StorageRow(
            row_number=index + 1,
            source_row=first_data_row + index,
            source_range=_source_row_range(table, first_data_row + index),
            values={
                column.sql_name: row[column.source_column_index - 1]
                if column.source_column_index - 1 < len(row)
                else None
                for column in columns
            },
        )
        for index, row in enumerate(data_rows)
    )


def _first_data_source_row(table: TableData) -> int:
    if table.xlsx is not None:
        return table.xlsx.header_row + 1
    if table.markdown is not None:
        return table.markdown.line_start + 2
    return 1


def _source_row_range(table: TableData, source_row: int) -> str:
    if table.xlsx is not None:
        return _row_range(
            table.xlsx.range.min_column,
            table.xlsx.range.max_column,
            source_row,
        )
    if table.markdown is not None:
        return f"L{source_row}"
    return str(source_row)


def _sql_column_names(columns: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, int] = {}
    names: list[str] = []
    for index, name in enumerate(columns, start=1):
        base = _sql_column_name(name, index)
        seen[base] = seen.get(base, 0) + 1
        names.append(base if seen[base] == 1 else f"{base}_{seen[base]}")
    return tuple(names)


def _sql_column_name(name: str, index: int) -> str:
    normalized = re.sub(r"[^0-9a-zA-Z]+", "_", name.strip().lower()).strip("_")
    if not normalized:
        return f"column_{index}"
    if normalized[0].isdigit():
        return f"col_{normalized}"
    return normalized


def _staging_table_name(table_name: str, workbook_checksum: str) -> str:
    suffix = hashlib.sha256(f"{table_name}:{workbook_checksum}".encode()).hexdigest()[:8]
    return f"{table_name}_stg_{suffix}"


def _plan_source_checksum(plan: TableToastStoragePlan) -> str:
    return plan.source_checksum or plan.workbook_checksum


def _advisory_lock_key(table_name: str) -> int:
    return int(hashlib.sha256(table_name.encode("utf-8")).hexdigest()[:15], 16)


def _row_range(min_column: int, max_column: int, row: int) -> str:
    return f"{_column_letter(min_column)}{row}:{_column_letter(max_column)}{row}"


def _column_letter(index: int) -> str:
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")
