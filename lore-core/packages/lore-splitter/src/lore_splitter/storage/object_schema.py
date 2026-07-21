from __future__ import annotations

import hashlib
import json
import re

from lore_core_domain.storage_contracts import (
    ImageToastStoragePlan,
    StoragePlanError,
)


def table_content_signature(columns, storage_types, rows) -> str:
    basis = {
        "columns": list(columns),
        "storage_types": list(storage_types),
        "rows": [list(row) for row in rows],
    }
    payload = json.dumps(basis, ensure_ascii=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()

TOAST_IMAGE_RE = re.compile(r"^toast_img_[0-9a-f]{20}$")
_OBJECT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]*$")
_EXTENSION_RE = re.compile(r"^[a-z0-9]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def image_content_signature(payload: bytes, content_type: str, extension: str) -> str:
    basis = b"\0".join(
        (
            payload,
            _normalize_content_type(content_type).encode("utf-8"),
            _normalize_extension(extension).encode("utf-8"),
        )
    )
    return hashlib.sha256(basis).hexdigest()


def image_toast_id(signature: str) -> str:
    if not _SHA256_RE.fullmatch(signature):
        raise StoragePlanError("invalid image content signature")
    return f"toast_img_{signature[:20]}"


def image_object_key(
    toast_id: str,
    extension: str,
    *,
    prefix: str = "image-toast",
) -> str:
    _validate_toast_image_id(toast_id)
    normalized_extension = _normalize_extension(extension)
    normalized_prefix = prefix.strip("/")
    if not normalized_prefix or ".." in normalized_prefix or normalized_prefix.startswith("/"):
        raise StoragePlanError("invalid image object key prefix")
    key = f"{normalized_prefix}/{toast_id[10:22]}/{toast_id}.{normalized_extension}"
    _validate_object_key(key)
    return key


def validate_image_storage_plan(plan: ImageToastStoragePlan) -> None:
    _validate_toast_image_id(plan.toast_id)
    if not plan.bucket or "/" in plan.bucket or ".." in plan.bucket:
        raise StoragePlanError("invalid image object bucket")
    if plan.content_type != _normalize_content_type(plan.content_type):
        raise StoragePlanError("invalid image content type")
    normalized_extension = _normalize_extension(plan.extension)
    if plan.extension != f".{normalized_extension}":
        raise StoragePlanError("invalid image extension")
    if not _is_valid_image_object_key(plan.object_key, plan.toast_id, plan.extension):
        raise StoragePlanError("invalid image object key")
    if plan.byte_size != len(plan.payload):
        raise StoragePlanError("image byte size does not match payload")
    checksum = hashlib.sha256(plan.payload).hexdigest()
    if plan.checksum_sha256 != checksum:
        raise StoragePlanError("image checksum does not match payload")
    expected_toast_id = image_toast_id(
        image_content_signature(plan.payload, plan.content_type, plan.extension)
    )
    if plan.toast_id != expected_toast_id:
        raise StoragePlanError("image toast id does not match payload metadata")


def _validate_toast_image_id(toast_id: str) -> None:
    if not TOAST_IMAGE_RE.fullmatch(toast_id):
        raise StoragePlanError("invalid image TOAST id: expected toast_img_[0-9a-f]{20}")


def _normalize_content_type(content_type: str) -> str:
    normalized = content_type.strip().lower()
    if not normalized.startswith("image/") or any(char.isspace() for char in normalized):
        raise StoragePlanError("invalid image content type")
    return normalized


def _normalize_extension(extension: str) -> str:
    normalized = extension.strip().lower().lstrip(".")
    if not _EXTENSION_RE.fullmatch(normalized):
        raise StoragePlanError("invalid image extension")
    return normalized


def _validate_object_key(key: str) -> None:
    if key.startswith("/") or ".." in key or not _OBJECT_KEY_RE.fullmatch(key):
        raise StoragePlanError("invalid image object key")


def _is_valid_image_object_key(object_key: str, toast_id: str, extension: str) -> bool:
    _validate_object_key(object_key)
    normalized_extension = _normalize_extension(extension)
    suffix = f"{toast_id[10:22]}/{toast_id}.{normalized_extension}"
    if not object_key.endswith(f"/{suffix}"):
        return False
    prefix = object_key[: -(len(suffix) + 1)]
    return image_object_key(toast_id, extension, prefix=prefix) == object_key
