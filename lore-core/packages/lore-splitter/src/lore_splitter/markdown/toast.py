from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from lore_splitter.markdown.contracts import (
    TableData,
    TableProfile,
    ToastDecision,
)

CLASSIFICATION_INLINE = "inline"
CLASSIFICATION_TOAST = "toast"
CLASSIFICATION_SKIPPED = "skipped"
CLASSIFICATIONS = frozenset(
    {CLASSIFICATION_INLINE, CLASSIFICATION_TOAST, CLASSIFICATION_SKIPPED}
)


@dataclass(frozen=True)
class ToastThresholds:
    max_inline_markdown_bytes: int = 4096
    max_inline_rows: int = 40
    max_inline_columns: int = 8
    max_inline_cells: int = 240
    min_meaningful_density: float = 0.15
    min_meaningful_data_cells: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_inline_markdown_bytes": self.max_inline_markdown_bytes,
            "max_inline_rows": self.max_inline_rows,
            "max_inline_columns": self.max_inline_columns,
            "max_inline_cells": self.max_inline_cells,
            "min_meaningful_density": self.min_meaningful_density,
            "min_meaningful_data_cells": self.min_meaningful_data_cells,
        }


def classify_table(
    table_data: TableData,
    table_profile: TableProfile,
    thresholds: ToastThresholds | None = None,
) -> ToastDecision:
    active_thresholds = thresholds or ToastThresholds()
    signature = content_signature(table_data, table_profile)
    estimated_markdown_bytes = estimate_markdown_bytes(table_data)
    warnings = table_profile.warnings

    skip_reasons = _skip_reasons(table_data, table_profile, active_thresholds)
    if skip_reasons:
        return ToastDecision(
            classification=CLASSIFICATION_SKIPPED,
            toast_id=None,
            content_signature=signature,
            estimated_markdown_bytes=estimated_markdown_bytes,
            reasons=skip_reasons,
            warnings=warnings,
            thresholds=active_thresholds.to_dict(),
        )

    toast_reasons = _toast_reasons(table_profile, estimated_markdown_bytes, active_thresholds)
    classification = CLASSIFICATION_TOAST if toast_reasons else CLASSIFICATION_INLINE
    return ToastDecision(
        classification=classification,
        toast_id=toast_id(signature) if classification == CLASSIFICATION_TOAST else None,
        content_signature=signature,
        estimated_markdown_bytes=estimated_markdown_bytes,
        reasons=toast_reasons,
        warnings=warnings,
        thresholds=active_thresholds.to_dict(),
    )


def render_toast_reference(decision: ToastDecision) -> str:
    if decision.classification != CLASSIFICATION_TOAST or decision.toast_id is None:
        return ""
    return f"[TOAST: {decision.toast_id}]"


def estimate_markdown_bytes(table_data: TableData) -> int:
    lines: list[str] = []
    columns = tuple(_markdown_cell(column) for column in table_data.columns)
    if columns:
        lines.append(_markdown_row(columns))
        lines.append(_markdown_row(tuple("---" for _ in columns)))
    for row in table_data.rows[table_data.data_row_offset + 1 :]:
        values = tuple(
            _markdown_cell(row[index] if index < len(row) else None)
            for index in range(len(table_data.columns))
        )
        lines.append(_markdown_row(values))
    rendered = "\n".join(lines)
    return len(rendered.encode("utf-8"))


def content_signature(table_data: TableData, table_profile: TableProfile) -> str:
    payload = {
        "columns": list(table_data.columns),
        "rows": [
            [_normalize_cell(value) for value in row[: len(table_data.columns)]]
            for row in table_data.rows
        ],
        "shape": {
            "row_count": table_profile.row_count,
            "column_count": table_profile.column_count,
            "cell_count": table_profile.cell_count,
            "density": table_profile.density,
        },
        "profile": [
            {
                "name": column.name,
                "inferred_type": column.inferred_type,
                "semantic_hints": list(column.semantic_hints),
                "null_count": column.null_count,
                "non_null_count": column.non_null_count,
            }
            for column in table_profile.column_profiles
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def toast_id(signature: str) -> str:
    return f"toast_tbl_{signature[:20]}"


def _skip_reasons(
    table_data: TableData,
    table_profile: TableProfile,
    thresholds: ToastThresholds,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if "low_meaning_table" in table_profile.warnings:
        reasons.append("low-meaning-content")
    if table_profile.density < thresholds.min_meaningful_density:
        reasons.append("density")
    if _meaningful_data_cells(table_data) < thresholds.min_meaningful_data_cells:
        reasons.append("low-meaning-content")
    return tuple(dict.fromkeys(reasons))


def _toast_reasons(
    table_profile: TableProfile,
    estimated_markdown_bytes: int,
    thresholds: ToastThresholds,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if estimated_markdown_bytes > thresholds.max_inline_markdown_bytes:
        reasons.append("estimated-markdown")
    if table_profile.row_count > thresholds.max_inline_rows:
        reasons.append("row-count")
    if table_profile.column_count > thresholds.max_inline_columns:
        reasons.append("column-count")
    if table_profile.cell_count > thresholds.max_inline_cells:
        reasons.append("cell-count")
    return tuple(reasons)


def _meaningful_data_cells(table_data: TableData) -> int:
    return sum(
        1
        for row in table_data.rows[table_data.data_row_offset + 1 :]
        for value in row[: len(table_data.columns)]
        if not _is_blank(value)
    )


def _markdown_row(values: tuple[str, ...]) -> str:
    return "| " + " | ".join(values) + " |"


def _markdown_cell(value: Any) -> str:
    normalized = "" if _is_blank(value) else str(value)
    return normalized.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _normalize_cell(value: Any) -> dict[str, Any]:
    if _is_blank(value):
        return {"type": "blank", "value": None}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, int | float | Decimal) and not isinstance(value, bool):
        return {"type": "number", "value": _normalize_number(value)}
    if isinstance(value, datetime):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, date):
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, str):
        return {"type": "text", "value": value}
    return {"type": type(value).__name__, "value": str(value)}


def _normalize_number(value: int | float | Decimal) -> str:
    decimal = Decimal(str(value)).normalize()
    if decimal == decimal.to_integral():
        return str(decimal.quantize(Decimal(1)))
    return format(decimal, "f")


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")
