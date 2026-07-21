from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from lore_splitter.markdown.contracts import (
    ColumnProfile,
    TableData,
    TableProfile,
)

WARNING_ALL_BLANK_COLUMN = "all_blank_column"
WARNING_FORMULA_LIKE_TEXT = "formula_like_text"
WARNING_LOW_MEANING_TABLE = "low_meaning_table"
WARNING_MIXED_TYPES = "mixed_types"
_UNIQUE_LIMIT = 20


def profile_table(table_data: TableData) -> TableProfile:
    row_count = len(table_data.rows)
    column_count = len(table_data.columns)
    cell_count = row_count * column_count
    nonblank_cell_count = sum(
        1 for row in table_data.rows for value in row[:column_count] if not _is_blank(value)
    )
    density = round(nonblank_cell_count / cell_count, 6) if cell_count else 0.0
    data_rows = _data_rows(table_data)

    column_profiles = tuple(
        _profile_column(name, _column_values(data_rows, index))
        for index, name in enumerate(table_data.columns)
    )
    warnings = list(table_data.warnings)
    for column in column_profiles:
        warnings.extend(column.warnings)
    if _is_low_meaning(data_rows, column_count):
        warnings.append(WARNING_LOW_MEANING_TABLE)

    return TableProfile(
        source_file=table_data.source_file,
        source_kind=table_data.source_kind,
        source_checksum=table_data.source_checksum,
        table_index=table_data.table_index,
        columns=table_data.columns,
        row_count=row_count,
        column_count=column_count,
        cell_count=cell_count,
        density=density,
        column_profiles=column_profiles,
        warnings=tuple(dict.fromkeys(warnings)),
        xlsx=table_data.xlsx,
        markdown=table_data.markdown,
    )


def _profile_column(name: str, values: tuple[Any, ...]) -> ColumnProfile:
    nonblank_values = tuple(value for value in values if not _is_blank(value))
    type_names = {_primitive_type(value) for value in nonblank_values}
    warnings: list[str] = []

    if not nonblank_values:
        inferred_type = "blank"
        warnings.append(WARNING_ALL_BLANK_COLUMN)
    elif len(type_names) == 1:
        inferred_type = next(iter(type_names))
    else:
        inferred_type = "mixed"
        warnings.append(WARNING_MIXED_TYPES)

    if any(_is_formula_like(value) for value in nonblank_values):
        warnings.append(WARNING_FORMULA_LIKE_TEXT)

    min_value, max_value = _min_max(nonblank_values, inferred_type)
    return ColumnProfile(
        name=name,
        inferred_type=inferred_type,
        semantic_hints=_semantic_hints(name, inferred_type),
        null_count=len(values) - len(nonblank_values),
        non_null_count=len(nonblank_values),
        unique_values=_bounded_uniques(nonblank_values),
        min_value=min_value,
        max_value=max_value,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _data_rows(table_data: TableData) -> tuple[tuple[Any, ...], ...]:
    return table_data.rows[table_data.data_row_offset + 1 :]


def _column_values(rows: tuple[tuple[Any, ...], ...], index: int) -> tuple[Any, ...]:
    return tuple(row[index] if index < len(row) else None for row in rows)


def _primitive_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float | Decimal) and not isinstance(value, bool):
        return "number"
    if isinstance(value, date | datetime) or _parse_date(value) is not None:
        return "date"
    return "text"


def _bounded_uniques(values: tuple[Any, ...]) -> tuple[Any, ...]:
    uniques: list[Any] = []
    seen: set[str] = set()
    for value in values:
        serialized = _serialize_value(value)
        key = repr(serialized)
        if key in seen:
            continue
        seen.add(key)
        uniques.append(serialized)
        if len(uniques) >= _UNIQUE_LIMIT:
            break
    return tuple(uniques)


def _min_max(values: tuple[Any, ...], inferred_type: str) -> tuple[Any, Any]:
    if inferred_type == "number":
        numbers = tuple(_number_value(value) for value in values)
        return min(numbers), max(numbers)
    if inferred_type == "date":
        dates = tuple(_parse_date(value) for value in values)
        comparable = tuple(value for value in dates if value is not None)
        if not comparable:
            return None, None
        return min(comparable).isoformat(), max(comparable).isoformat()
    return None, None


def _semantic_hints(name: str, inferred_type: str) -> tuple[str, ...]:
    normalized = name.strip().lower()
    hints: list[str] = []
    if "id" in normalized or "identifier" in normalized or normalized.endswith("_id"):
        hints.extend(["identifier", "dimension"])
    elif inferred_type == "date" or "date" in normalized:
        hints.append("date")
    elif "%" in normalized or "percent" in normalized or "discount" in normalized:
        hints.extend(["measure", "percentage"])
    elif any(token in normalized for token in ("amount", "currency", "usd", "price", "cost")):
        hints.extend(["measure", "currency"])
    elif inferred_type == "number":
        hints.append("measure")
    elif inferred_type == "text":
        hints.append("dimension")
    return tuple(dict.fromkeys(hints))


def _is_low_meaning(rows: tuple[tuple[Any, ...], ...], column_count: int) -> bool:
    if not rows or column_count == 0:
        return True
    nonblank_data_cells = sum(
        1 for row in rows for value in row[:column_count] if not _is_blank(value)
    )
    return nonblank_data_cells <= 1


def _number_value(value: Any) -> int | float:
    if isinstance(value, Decimal):
        return float(value)
    return value


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


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _is_formula_like(value: Any) -> bool:
    return isinstance(value, str) and value.strip().startswith("=")


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")
