from __future__ import annotations

from typing import Protocol, runtime_checkable

from lore_core_domain.storage_contracts import (
    ImageToastStoragePlan,
    ImageToastStorageResult,
    ObjectToastStore,
    StorageColumn,
    StorageRow,
    TableToastStoragePlan,
    TableToastStorageResult,
)


def test_storage_contracts_serialize_plan_and_result_for_manifest_traceability() -> None:
    column = StorageColumn(
        logical_name="Amount USD",
        sql_name="amount_usd",
        inferred_type="number",
        storage_type="numeric",
        nullable=False,
        source_column_index=2,
    )
    row = StorageRow(
        row_number=1,
        source_row=4,
        source_range="A4:C4",
        values={"amount_usd": 125.5},
    )
    plan = TableToastStoragePlan(
        toast_id="toast_tbl_0123456789abcdefabcd",
        schema_name="splitter_toast",
        table_name="toast_tbl_0123456789abcdefabcd",
        staging_table_name="toast_tbl_0123456789abcdefabcd_staging",
        advisory_lock_key=12345,
        columns=(column,),
        rows=(row,),
        source={"source_id": "google-drive"},
        workbook_checksum="a" * 64,
        sheet={"name": "Summary", "index": 1},
        range={"a1_range": "A1:C4"},
        warnings=("storage_type_downgrade:example",),
        diagnostics=("dry-run",),
    )
    result = TableToastStorageResult.from_plan(plan, action="dry_run_created")

    assert plan.to_dict()["columns"] == [column.to_dict()]
    assert plan.to_dict()["rows"] == [row.to_dict()]
    assert result.to_manifest_entry() == {
        "toast_id": "toast_tbl_0123456789abcdefabcd",
        "schema": "splitter_toast",
        "table_name": "toast_tbl_0123456789abcdefabcd",
        "row_count": 1,
        "action": "dry_run_created",
        "warnings": ["storage_type_downgrade:example"],
        "diagnostics": ["dry-run"],
        "source": {"source_id": "google-drive"},
        "source_kind": "workbook",
        "source_checksum": "a" * 64,
        "source_location": {
            "xlsx": {
                "workbook_checksum": "a" * 64,
                "sheet": {"name": "Summary", "index": 1},
                "range": {"a1_range": "A1:C4"},
            }
        },
        "workbook_checksum": "a" * 64,
        "sheet": {"name": "Summary", "index": 1},
        "range": {"a1_range": "A1:C4"},
    }


def test_storage_package_exports_only_stable_public_names_and_object_protocol_boundary() -> None:
    import lore_splitter.storage as storage

    assert set(storage.__all__) == {
        "DEFAULT_TOAST_SCHEMA",
        "FakeObjectToastStore",
        "FakeTableToastStore",
        "ImageToastStoragePlan",
        "ImageToastStorageResult",
        "ObjectToastStore",
        "StorageColumn",
        "StoragePlanError",
        "StorageRow",
        "TOAST_TABLE_RE",
        "TableToastStoragePlan",
        "TableToastStorageResult",
        "TableToastStore",
        "apply_migration",
        "build_table_storage_plan",
        "image_content_signature",
        "image_object_key",
        "image_toast_id",
        "validate_image_storage_plan",
        "validate_table_storage_plan",
        "validate_toast_table_name",
    }
    assert issubclass(ObjectToastStore, Protocol)
    assert not hasattr(storage, "MinioObjectToastStore")
    # Airflow hooks are deferred to Phase 3 — not present in portable package
    assert not hasattr(storage, "PostgresHookTableToastStoreFactory")
    assert not hasattr(storage, "S3HookObjectToastStore")


@runtime_checkable
class _ObjectStoreShape(Protocol):
    def store_object(self, plan: ImageToastStoragePlan) -> ImageToastStorageResult: ...


def test_object_toast_store_protocol_is_code_level_only() -> None:
    assert issubclass(ObjectToastStore, _ObjectStoreShape)
