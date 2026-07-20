"""Closed durable payload registration for deterministic audit resolution."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from audit.engine_contracts import (
    PayloadResolutionFact,
    PhysicalResolution,
)
from audit.image_safety import validate_safe_raster_content_type
from audit.validation import validate_target_id
from audit._vendor.storage_contracts import (
    ImageToastStorageResult,
    TableToastStorageResult,
)

PAYLOAD_REGISTRATION_V1 = "audit/payload-registration/v1"
AUDIT_REGISTRATION_KEY = "audit_registration"
MAX_REGISTRATION_COUNT = 10_000_000
MAX_REGISTRATION_STRING = 512
MAX_REGISTRATION_COLLECTION_ITEMS = 64
MAX_REGISTRATION_DEPTH = 4
MAX_REGISTRATION_BYTES = 8_192

_ERROR = "invalid payload audit registration"
_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_SQL_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*", re.ASCII)
_CONNECTION_SHAPED = re.compile(
    r"(?:conn(?:ection)?(?:_id)?|dsn|password|passwd|credential|secret|token|signed[_-]?url|api[_-]?key)",
    re.I,
)
_URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)
_ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "payload_id",
        "kind",
        "backend",
        "registration_identity",
        "metadata",
        "summary",
    }
)
_TABLE_IDENTITY_KEYS = frozenset(
    {
        "schema_name",
        "table_name",
        "row_count",
        "column_count",
        "columns",
        "source_kind",
        "source_checksum",
        "source_location",
        "profile_signature",
    }
)
_IMAGE_IDENTITY_KEYS = frozenset(
    {
        "bucket",
        "object_key",
        "content_type",
        "extension",
        "byte_size",
        "checksum_sha256",
        "source_kind",
        "source_checksum",
        "source_location",
        "width",
        "height",
        "dimensions",
    }
)


def _fail() -> None:
    raise ValueError(_ERROR)


def _bounded_non_empty_string(value: Any, *, identifier: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_REGISTRATION_STRING:
        _fail()
    if _CONNECTION_SHAPED.search(value) or _URL.match(value):
        _fail()
    if identifier and _SQL_IDENTIFIER.fullmatch(value) is None:
        _fail()
    return value


def _sha256(value: Any) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail()
    return value


def _count(value: Any) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > MAX_REGISTRATION_COUNT
    ):
        _fail()
    return value


def _validate_bounded_value(value: Any, *, depth: int = 0, items: list[int] | None = None) -> None:
    if items is None:
        items = [0]
    if depth > MAX_REGISTRATION_DEPTH:
        _fail()
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail()
        return
    if isinstance(value, str):
        _bounded_non_empty_string(value)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            items[0] += 1
            if items[0] > MAX_REGISTRATION_COLLECTION_ITEMS:
                _fail()
            if not isinstance(key, str) or not key or len(key) > MAX_REGISTRATION_STRING:
                _fail()
            if _CONNECTION_SHAPED.search(key):
                _fail()
            _validate_bounded_value(item, depth=depth + 1, items=items)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            items[0] += 1
            if items[0] > MAX_REGISTRATION_COLLECTION_ITEMS:
                _fail()
            _validate_bounded_value(item, depth=depth + 1, items=items)
        return
    _fail()


def _canonical_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail()
    _validate_bounded_value(value)
    try:
        encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        projected = json.loads(encoded)
    except (TypeError, ValueError):
        _fail()
    if not isinstance(projected, dict) or len(encoded.encode("utf-8")) > MAX_REGISTRATION_BYTES:
        _fail()
    return projected


def _add_if_present(target: dict[str, Any], key: str, value: Any) -> None:
    if value is not None and value != {} and value != ():
        target[key] = value


def _payload_metadata(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, Mapping):
        _fail()
    return metadata


def _table_registration(
    payload: Mapping[str, Any], result: TableToastStorageResult
) -> dict[str, Any]:
    metadata_input = _payload_metadata(payload)
    registration_identity: dict[str, Any] = {
        "schema_name": _bounded_non_empty_string(result.schema_name, identifier=True),
        "table_name": _bounded_non_empty_string(result.table_name, identifier=True),
        "row_count": _count(result.row_count),
    }
    metadata: dict[str, Any] = {"row_count": result.row_count}
    summary: dict[str, Any] = {"row_count": result.row_count}

    columns = metadata_input.get("columns")
    if columns is not None:
        if not isinstance(columns, (list, tuple)):
            _fail()
        columns = list(columns)
        _validate_bounded_value(columns)
        if any(not isinstance(item, str) or not item for item in columns):
            _fail()
        registration_identity["columns"] = columns
        metadata["columns"] = columns
        summary["columns"] = columns

    column_count = metadata_input.get("column_count")
    if column_count is not None:
        column_count = _count(column_count)
        if columns is not None and column_count != len(columns):
            _fail()
        registration_identity["column_count"] = column_count
        metadata["column_count"] = column_count
        summary["column_count"] = column_count

    profile_signature = metadata_input.get("profile_signature")
    if profile_signature is not None:
        registration_identity["profile_signature"] = _sha256(profile_signature)
        summary["profile_signature"] = profile_signature

    for key in ("source_kind", "source_checksum", "source_location"):
        value = getattr(result, key)
        if value is None or value == {}:
            continue
        if key == "source_checksum":
            value = _sha256(value)
        elif key == "source_kind":
            value = _bounded_non_empty_string(value)
        registration_identity[key] = value
        metadata[key] = value
    _add_if_present(metadata, "sheet", result.sheet)
    _add_if_present(metadata, "range", result.range)
    return _envelope(
        payload_id=result.toast_id,
        kind="table",
        backend="postgres",
        registration_identity=registration_identity,
        metadata=metadata,
        summary=summary,
    )


def _image_registration(
    payload: Mapping[str, Any], result: ImageToastStorageResult
) -> dict[str, Any]:
    metadata_input = _payload_metadata(payload)
    registration_identity: dict[str, Any] = {
        "bucket": _bounded_non_empty_string(result.bucket),
        "object_key": _bounded_non_empty_string(result.object_key),
        "content_type": validate_safe_raster_content_type(result.content_type),
        "extension": _bounded_non_empty_string(result.extension),
        "byte_size": _count(result.byte_size),
        "checksum_sha256": _sha256(result.checksum_sha256),
    }
    metadata: dict[str, Any] = {
        "content_type": result.content_type,
        "extension": result.extension,
        "byte_size": result.byte_size,
        "checksum_sha256": result.checksum_sha256,
    }
    for key in ("source_kind", "source_checksum", "source_location"):
        value = getattr(result, key)
        if value is None or value == {}:
            continue
        if key == "source_checksum":
            value = _sha256(value)
        elif key == "source_kind":
            value = _bounded_non_empty_string(value)
        registration_identity[key] = value
        metadata[key] = value
    for key in ("width", "height"):
        value = metadata_input.get(key)
        if value is not None:
            value = _count(value)
            registration_identity[key] = value
            metadata[key] = value
    dimensions = metadata_input.get("dimensions")
    if dimensions is not None:
        dimensions = _canonical_mapping(dimensions)
        registration_identity["dimensions"] = dimensions
        metadata["dimensions"] = dimensions
    return _envelope(
        payload_id=result.toast_id,
        kind="image",
        backend="s3",
        registration_identity=registration_identity,
        metadata=metadata,
        summary={},
    )


def _envelope(
    *,
    payload_id: str,
    kind: str,
    backend: str,
    registration_identity: Mapping[str, Any],
    metadata: Mapping[str, Any],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    validate_target_id(payload_id)
    value = {
        "schema_version": PAYLOAD_REGISTRATION_V1,
        "payload_id": payload_id,
        "kind": kind,
        "backend": backend,
        "registration_identity": _canonical_mapping(registration_identity),
        "metadata": _canonical_mapping(metadata),
        "summary": _canonical_mapping(summary),
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_REGISTRATION_BYTES:
        _fail()
    return value


def build_payload_registration(payload: Any, result: Any) -> dict[str, Any]:
    """Project one successful typed storage result into the exact durable v1 envelope."""

    try:
        if not isinstance(payload, Mapping):
            _fail()
        payload_id = validate_target_id(payload.get("payload_id"))
        kind = payload.get("kind")
        if kind == "table" and isinstance(result, TableToastStorageResult):
            if payload_id != result.toast_id or result.action not in {
                "created",
                "reused",
                "replaced",
            }:
                _fail()
            return _table_registration(payload, result)
        if kind == "image" and isinstance(result, ImageToastStorageResult):
            if payload_id != result.toast_id or result.action not in {"created", "reused"}:
                _fail()
            return _image_registration(payload, result)
        _fail()
    except (TypeError, ValueError):
        raise ValueError(_ERROR) from None


def _validate_parsed_envelope(
    payload_id: str, kind: str, registration: Any
) -> dict[str, Any]:
    if not isinstance(registration, Mapping) or set(registration) != _ENVELOPE_KEYS:
        _fail()
    if registration.get("schema_version") != PAYLOAD_REGISTRATION_V1:
        _fail()
    if registration.get("payload_id") != payload_id or registration.get("kind") != kind:
        _fail()
    expected_backend = "postgres" if kind == "table" else "s3"
    if registration.get("backend") != expected_backend:
        _fail()
    canonical = _envelope(
        payload_id=registration["payload_id"],
        kind=registration["kind"],
        backend=registration["backend"],
        registration_identity=registration["registration_identity"],
        metadata=registration["metadata"],
        summary=registration["summary"],
    )
    allowed_identity = _TABLE_IDENTITY_KEYS if kind == "table" else _IMAGE_IDENTITY_KEYS
    identity = canonical["registration_identity"]
    metadata = canonical["metadata"]
    summary = canonical["summary"]
    if set(identity) - allowed_identity:
        _fail()
    if kind == "table":
        required = {"schema_name", "table_name", "row_count"}
        if not required <= set(identity):
            _fail()
        _bounded_non_empty_string(identity["schema_name"], identifier=True)
        _bounded_non_empty_string(identity["table_name"], identifier=True)
        _count(identity["row_count"])
        if "column_count" in identity:
            _count(identity["column_count"])
        if "columns" in identity:
            columns = identity["columns"]
            if not isinstance(columns, list) or any(
                not isinstance(item, str) or not item for item in columns
            ):
                _fail()
            if "column_count" in identity and len(columns) != identity["column_count"]:
                _fail()
        if "profile_signature" in identity:
            _sha256(identity["profile_signature"])
    else:
        required = {
            "bucket",
            "object_key",
            "content_type",
            "extension",
            "byte_size",
            "checksum_sha256",
        }
        if not required <= set(identity):
            _fail()
        for key in ("bucket", "object_key", "extension"):
            _bounded_non_empty_string(identity[key])
        validate_safe_raster_content_type(identity["content_type"])
        _count(identity["byte_size"])
        _sha256(identity["checksum_sha256"])
        for key in ("width", "height"):
            if key in identity:
                _count(identity[key])
    if "source_kind" in identity:
        _bounded_non_empty_string(identity["source_kind"])
    if "source_checksum" in identity:
        _sha256(identity["source_checksum"])
    for projection in (metadata, summary):
        for key in set(identity) & set(projection):
            if projection[key] != identity[key]:
                _fail()
    return canonical


def parse_payload_registration(
    payload_id: str,
    kind: str,
    metadata: Any,
    occurrence_count: int,
) -> PayloadResolutionFact:
    """Parse one persisted registration, degrading only a genuinely absent legacy key."""

    try:
        validate_target_id(payload_id)
        if kind not in {"table", "image"}:
            _fail()
        _count(occurrence_count)
        if not isinstance(metadata, Mapping):
            _fail()
        if AUDIT_REGISTRATION_KEY not in metadata:
            return PayloadResolutionFact(
                payload_id=payload_id,
                kind=kind,
                registered=False,
                occurrence_count=occurrence_count,
            )
        registration = _validate_parsed_envelope(
            payload_id, kind, metadata[AUDIT_REGISTRATION_KEY]
        )
        identity = registration["registration_identity"]
        if kind == "table":
            physical = PhysicalResolution(
                storage_kind="postgres",
                resolved=True,
                identity={
                    "schema_name": identity["schema_name"],
                    "table_name": identity["table_name"],
                },
            )
        else:
            physical = PhysicalResolution(
                storage_kind="s3",
                resolved=True,
                identity={"bucket": identity["bucket"], "object_key": identity["object_key"]},
                checksum_sha256=identity["checksum_sha256"],
                byte_size=identity["byte_size"],
                content_type=identity["content_type"],
            )
        return PayloadResolutionFact(
            payload_id=payload_id,
            kind=kind,
            registered=True,
            occurrence_count=occurrence_count,
            registration_identity=identity,
            physical=physical,
            metadata=registration["metadata"],
            summary=registration["summary"],
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError(_ERROR) from None


__all__ = [
    "AUDIT_REGISTRATION_KEY",
    "MAX_REGISTRATION_BYTES",
    "MAX_REGISTRATION_COLLECTION_ITEMS",
    "MAX_REGISTRATION_COUNT",
    "MAX_REGISTRATION_DEPTH",
    "MAX_REGISTRATION_STRING",
    "PAYLOAD_REGISTRATION_V1",
    "build_payload_registration",
    "parse_payload_registration",
]
