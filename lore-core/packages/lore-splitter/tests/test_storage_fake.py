from __future__ import annotations

from lore_splitter.markdown import ToastThresholds, classify_table, profile_table
from lore_splitter.storage import (
    FakeObjectToastStore,
    FakeTableToastStore,
    ImageToastStoragePlan,
    StoragePlanError,
    build_table_storage_plan,
    image_content_signature,
    image_object_key,
    image_toast_id,
)
from tests.test_markdown_render import _table_data


def test_d18_d19_fake_store_validates_and_keeps_rows_in_memory_without_payload_files(
    tmp_path,
) -> None:
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
    decision = classify_table(
        table,
        profile,
        thresholds=ToastThresholds(max_inline_markdown_bytes=1),
    )
    plan = build_table_storage_plan(table, profile, decision)
    store = FakeTableToastStore()

    result = store.store_table(plan)

    assert plan.source_kind == "workbook"
    assert plan.source_checksum == table.source_checksum
    assert plan.source_location == {"xlsx": table.xlsx.to_dict()}
    assert plan.to_dict()["source_kind"] == "workbook"
    assert plan.to_dict()["source_checksum"] == table.source_checksum
    assert plan.to_dict()["source_location"] == {"xlsx": table.xlsx.to_dict()}
    assert result.action == "dry_run_created"
    assert result.row_count == 3
    assert result.source_kind == plan.source_kind
    assert result.source_checksum == plan.source_checksum
    assert result.source_location == plan.source_location
    assert result.to_manifest_entry()["source_kind"] == "workbook"
    assert result.to_manifest_entry()["source_checksum"] == table.source_checksum
    assert result.to_manifest_entry()["source_location"] == {"xlsx": table.xlsx.to_dict()}
    assert store.results_by_toast_id[plan.toast_id] == result
    assert store.plans_by_toast_id[plan.toast_id] == plan
    assert store.rows_by_table_name[plan.table_name] == plan.rows
    assert result.to_manifest_entry()["table_name"] == plan.table_name
    assert any("Amount" in warning for warning in result.warnings)
    assert not list(tmp_path.iterdir())


def test_fake_store_rejects_tampered_plan_table_names() -> None:
    table = _table_data("Summary", 1, "A1:B3")
    profile = profile_table(table)
    decision = classify_table(
        table,
        profile,
        thresholds=ToastThresholds(max_inline_markdown_bytes=1),
    )
    plan = build_table_storage_plan(table, profile, decision)
    tampered = plan.__class__(
        **{
            **plan.to_constructor_dict(),
            "table_name": "customer_supplied_table",
        }
    )

    store = FakeTableToastStore()

    try:
        store.store_table(tampered)
    except StoragePlanError as exc:
        assert "table name" in str(exc)
    else:
        raise AssertionError("expected tampered plan to be rejected")


def test_fake_store_replaces_existing_table_on_same_toast_id() -> None:
    table = _table_data("Summary", 1, "A1:B3")
    profile = profile_table(table)
    decision = classify_table(
        table,
        profile,
        thresholds=ToastThresholds(max_inline_markdown_bytes=1),
    )
    plan = build_table_storage_plan(table, profile, decision)
    store = FakeTableToastStore()

    first = store.store_table(plan)
    second = store.store_table(plan)

    assert first.action == "dry_run_created"
    assert second.action == "dry_run_replaced"
    assert store.results_by_toast_id[plan.toast_id] == second


def _image_plan(payload: bytes = b"image-payload") -> ImageToastStoragePlan:
    signature = image_content_signature(payload, "image/png", "png")
    toast_id = image_toast_id(signature)
    return ImageToastStoragePlan(
        toast_id=toast_id,
        bucket="splitter-image-toast",
        object_key=image_object_key(toast_id, "png"),
        content_type="image/png",
        extension=".png",
        payload=payload,
        byte_size=len(payload),
        checksum_sha256="82eefbe096f6ecd557e3aac27940dc126c64d71500b8853b316922539f1acb0c",
        source={"source_id": "google-drive"},
        source_kind="document_image",
        source_checksum="a" * 64,
        source_location={"docx": {"relationship_id": "rId7"}},
    )


def test_fake_object_store_records_plans_results_and_payloads() -> None:
    plan = _image_plan()
    store = FakeObjectToastStore()

    result = store.store_object(plan)

    assert result.action == "dry_run_created"
    assert store.plans_by_toast_id[plan.toast_id] == plan
    assert store.results_by_toast_id[plan.toast_id] == result
    assert store.payloads_by_toast_id[plan.toast_id] == b"image-payload"
    assert store.payloads_by_object_key[plan.object_key] == b"image-payload"


def test_fake_object_store_replaces_existing_payload_for_same_toast_id() -> None:
    plan = _image_plan()
    store = FakeObjectToastStore()

    first = store.store_object(plan)
    second = store.store_object(plan)

    assert first.action == "dry_run_created"
    assert second.action == "dry_run_replaced"
    assert second.checksum_sha256 == first.checksum_sha256
    assert second.byte_size == first.byte_size
    assert second.bucket == first.bucket
    assert second.object_key == first.object_key


def test_fake_object_store_failure_returns_failed_result_without_payload_write() -> None:
    plan = _image_plan()
    store = FakeObjectToastStore(fail_toast_ids={plan.toast_id})

    result = store.store_object(plan)

    assert result.action == "failed"
    assert any("fake_object_store_failure" in diagnostic for diagnostic in result.diagnostics)
    assert plan.toast_id not in store.payloads_by_toast_id
    assert plan.object_key not in store.payloads_by_object_key


def test_fake_object_store_rejects_tampered_checksum_before_payload_write() -> None:
    plan = _image_plan()
    tampered = ImageToastStoragePlan(
        **{
            **plan.to_constructor_dict(),
            "checksum_sha256": "0" * 64,
        }
    )
    store = FakeObjectToastStore()

    try:
        store.store_object(tampered)
    except StoragePlanError as exc:
        assert "checksum" in str(exc)
    else:
        raise AssertionError("expected tampered object plan to be rejected")

    assert not store.payloads_by_toast_id
