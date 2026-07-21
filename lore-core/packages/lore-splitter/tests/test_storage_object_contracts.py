from __future__ import annotations

from typing import Protocol

import pytest
from lore_splitter.storage import (
    ImageToastStoragePlan,
    ImageToastStorageResult,
    ObjectToastStore,
    StoragePlanError,
    image_content_signature,
    image_object_key,
    image_toast_id,
    validate_image_storage_plan,
)


def _image_plan(payload: bytes = b"image-payload") -> ImageToastStoragePlan:
    signature = image_content_signature(payload, "Image/PNG", ".PNG")
    toast_id = image_toast_id(signature)
    return ImageToastStoragePlan(
        toast_id=toast_id,
        bucket="splitter-image-toast",
        object_key=image_object_key(toast_id, ".PNG"),
        content_type="image/png",
        extension=".png",
        payload=payload,
        byte_size=len(payload),
        checksum_sha256="82eefbe096f6ecd557e3aac27940dc126c64d71500b8853b316922539f1acb0c",
        source={"source_id": "google-drive", "file_id": "doc-1"},
        source_kind="document_image",
        source_checksum="a" * 64,
        source_location={"pdf": {"page": 1, "bbox": [72, 137, 392, 317]}},
        warnings=("large-image",),
        diagnostics=("storage-plan-built",),
    )


def test_image_content_signature_ids_and_keys_are_deterministic_and_content_primary() -> None:
    payload = b"image-payload"
    signature = image_content_signature(payload, "Image/PNG", ".PNG")

    assert signature == image_content_signature(payload, "image/png", "png")
    assert signature != image_content_signature(payload + b"!", "image/png", "png")
    assert signature != image_content_signature(payload, "image/jpeg", "jpg")
    assert signature != image_content_signature(payload, "image/png", "jpg")

    toast_id = image_toast_id(signature)
    assert toast_id.startswith("toast_img_")
    assert toast_id == image_toast_id(signature)
    assert image_object_key(toast_id, ".PNG") == f"image-toast/{toast_id[10:22]}/{toast_id}.png"


@pytest.mark.parametrize("extension", ["", "../png", "/tmp/source.png"])
def test_image_object_key_rejects_unsafe_extensions(extension: str) -> None:
    toast_id = image_toast_id(image_content_signature(b"payload", "image/png", "png"))

    with pytest.raises(StoragePlanError):
        image_object_key(toast_id, extension)


def test_image_storage_plan_and_result_serialize_without_postgres_fields() -> None:
    plan = _image_plan()
    validate_image_storage_plan(plan)
    result = ImageToastStorageResult.from_plan(plan, action="dry_run_created")

    plan_dict = plan.to_dict()
    result_dict = result.to_dict()
    assert plan_dict["toast_id"] == plan.toast_id
    assert plan_dict["bucket"] == "splitter-image-toast"
    assert plan_dict["object_key"].endswith(f"/{plan.toast_id}.png")
    assert plan_dict["byte_size"] == len(b"image-payload")
    assert result_dict["action"] == "dry_run_created"
    assert result_dict["source_location"] == {"pdf": {"page": 1, "bbox": [72, 137, 392, 317]}}

    forbidden = {
        "schema_name",
        "schema",
        "table_name",
        "staging_table_name",
        "row_count",
        "rows",
        "advisory_lock_key",
    }
    assert forbidden.isdisjoint(plan_dict)
    assert forbidden.isdisjoint(result_dict)
    assert "payload" not in result_dict


def test_validate_image_storage_plan_rejects_tampered_payload_metadata() -> None:
    plan = _image_plan()
    tampered = ImageToastStoragePlan(
        **{
            **plan.to_constructor_dict(),
            "byte_size": plan.byte_size + 1,
        }
    )

    with pytest.raises(StoragePlanError, match="byte size"):
        validate_image_storage_plan(tampered)


def test_storage_package_exports_stable_object_contract_names() -> None:
    import lore_splitter.storage as storage

    assert "ImageToastStoragePlan" in storage.__all__
    assert "ImageToastStorageResult" in storage.__all__
    assert "image_content_signature" in storage.__all__
    assert "image_toast_id" in storage.__all__
    assert "image_object_key" in storage.__all__
    assert issubclass(ObjectToastStore, Protocol)
