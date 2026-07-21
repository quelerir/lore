from __future__ import annotations

from pathlib import Path

import pytest
from lore_splitter.contracts import SourceFile
from lore_splitter.markdown import ToastDecision, ToastThresholds, profile_table
from lore_splitter.storage import (
    DEFAULT_TOAST_SCHEMA,
    StoragePlanError,
    build_table_storage_plan,
    validate_toast_table_name,
)
from lore_splitter.xlsx import CellRange
from tests.test_markdown_render import _table_data


def _toast_decision(toast_id: str = "toast_tbl_0123456789abcdefabcd") -> ToastDecision:
    return ToastDecision(
        classification="toast",
        toast_id=toast_id,
        content_signature="f" * 64,
        estimated_markdown_bytes=8192,
        reasons=("estimated-markdown",),
        thresholds=ToastThresholds(max_inline_markdown_bytes=1).to_dict(),
    )


def test_d01_d02_d04_storage_plan_reuses_phase3_toast_id_as_physical_table_name() -> None:
    table = _table_data("Summary", 1, "A1:B3")
    profile = profile_table(table)

    default_plan = build_table_storage_plan(table, profile, _toast_decision())
    custom_schema_plan = build_table_storage_plan(
        table,
        profile,
        _toast_decision(),
        schema_name="tenant_a",
    )

    assert default_plan.schema_name == DEFAULT_TOAST_SCHEMA
    assert default_plan.table_name == "toast_tbl_0123456789abcdefabcd"
    assert default_plan.content_signature == "f" * 64
    assert default_plan.to_dict()["content_signature"] == "f" * 64
    assert custom_schema_plan.schema_name == "tenant_a"
    assert custom_schema_plan.table_name == "toast_tbl_0123456789abcdefabcd"
    assert custom_schema_plan.staging_table_name.startswith(
        "toast_tbl_0123456789abcdefabcd_stg_"
    )
    assert custom_schema_plan.advisory_lock_key > 0


@pytest.mark.parametrize(
    "name",
    [
        "toast_tbl_0123456789ABCDEFabcd",
        "toast_tbl_0123456789abcdefabc",
        "toast_tbl_0123456789abcdefabcde",
        "toast_tbl_0123456789abcdefabc!",
        "public.toast_tbl_0123456789abcdefabcd",
        "customer_supplied_table",
        "toast_tbl_;drop_table_now",
    ],
)
def test_d04_invalid_toast_ids_are_rejected_before_store_calls(name: str) -> None:
    table = _table_data("Summary", 1, "A1:B3")
    profile = profile_table(table)

    with pytest.raises(StoragePlanError):
        validate_toast_table_name(name)
    with pytest.raises(StoragePlanError):
        build_table_storage_plan(table, profile, _toast_decision(name))


def test_non_toast_decisions_are_rejected_with_narrow_error() -> None:
    table = _table_data("Summary", 1, "A1:B3")
    profile = profile_table(table)
    decision = ToastDecision(
        classification="inline",
        toast_id=None,
        content_signature="f" * 64,
        estimated_markdown_bytes=256,
    )

    with pytest.raises(StoragePlanError, match="toast"):
        build_table_storage_plan(table, profile, decision)


def test_d05_d06_d07_d08_unsafe_inferred_columns_downgrade_to_text_with_warnings() -> None:
    table = _table_data(
        "Summary",
        1,
        "A1:C4",
        rows=(
            ("Region", "Amount", "Invoice Date"),
            ("North", 125.5, "2026-02-01"),
            ("South", "not a number", "not-a-date"),
            ("West", 50, "2026-02-03"),
        ),
    )
    profile = profile_table(table)

    plan = build_table_storage_plan(table, profile, _toast_decision())

    columns_by_logical_name = {column.logical_name: column for column in plan.columns}
    assert columns_by_logical_name["Region"].storage_type == "text"
    assert columns_by_logical_name["Amount"].inferred_type == "mixed"
    assert columns_by_logical_name["Amount"].storage_type == "text"
    assert columns_by_logical_name["Invoice Date"].storage_type == "text"
    assert plan.rows[1].values["amount"] == "not a number"
    assert plan.rows[1].values["invoice_date"] == "not-a-date"
    assert any(
        "toast_tbl_0123456789abcdefabcd" in warning
        and "Amount" in warning
        and "mixed" in warning
        and "downgraded-to-text" in warning
        for warning in plan.warnings
    )
    assert any(
        "Invoice Date" in warning and "mixed" in warning and "downgraded-to-text" in warning
        for warning in plan.warnings
    )


def test_d09_storage_rows_include_order_and_source_coordinate_metadata() -> None:
    table = _table_data(
        "Summary",
        1,
        "B4:C6",
        rows=(("Region", "Amount"), ("North", 10), ("South", 25)),
    )
    profile = profile_table(table)

    plan = build_table_storage_plan(table, profile, _toast_decision())

    assert [row.row_number for row in plan.rows] == [1, 2]
    assert [row.source_row for row in plan.rows] == [5, 6]
    assert [row.source_range for row in plan.rows] == ["B5:C5", "B6:C6"]
    assert plan.rows[0].values == {"region": "North", "amount": 10}


def test_sql_column_names_are_deterministic_and_safe_when_headers_duplicate_or_blank() -> None:
    source = SourceFile(
        source_id="source",
        stream="stream",
        file_id="file",
        source_path="book.xlsx",
        object_path="/staging/book.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=1,
    )
    table = _table_data(
        "Summary",
        1,
        "A1:D3",
        rows=(("Amount USD", "Amount USD", "", "100%"), ("1", "2", "x", "3")),
    ).__class__(
        source_file=source,
        local_path=Path("/tmp/book.xlsx"),
        workbook_checksum="a" * 64,
        sheet_name="Summary",
        sheet_index=1,
        range=CellRange(1, 3, 1, 4, "A1:D3"),
        header_row=1,
        columns=("Amount USD", "Amount USD", "", "100%"),
        rows=(("Amount USD", "Amount USD", "", "100%"), ("1", "2", "x", "3")),
    )
    profile = profile_table(table)

    plan = build_table_storage_plan(table, profile, _toast_decision())

    assert [column.sql_name for column in plan.columns] == [
        "amount_usd",
        "amount_usd_2",
        "column_3",
        "col_100",
    ]
