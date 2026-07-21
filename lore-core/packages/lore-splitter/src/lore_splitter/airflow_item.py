"""Strict normalization of one immutable Airbyte file item."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lore_splitter.contracts import SourceFile


class AirbyteItemError(ValueError):
    """Permanent failure in the public Airbyte file-item contract."""


@dataclass(frozen=True)
class NormalizedAirbyteItem:
    source_file: SourceFile
    bucket: str
    key: str


def normalize_airbyte_item(item: Any) -> NormalizedAirbyteItem:
    if not isinstance(item, dict):
        raise AirbyteItemError("file item must be a JSON object")

    def required(name: str) -> str:
        value = item.get(name)
        if value is None or not str(value).strip():
            raise AirbyteItemError(f"missing {name}")
        return str(value).strip()

    file_id = item.get("file_id") or item.get("id") or item.get("source_file_id")
    if file_id is None or not str(file_id).strip():
        raise AirbyteItemError("missing file identity")
    bucket = item.get("bucket") or item.get("source_bucket")
    key = item.get("key") or item.get("source_key") or item.get("object_key")
    if bucket is None or key is None or not str(bucket).strip() or not str(key).strip():
        raise AirbyteItemError("missing source bucket/key")

    source_path = item.get("source_path") or item.get("path") or str(key)
    object_path = item.get("object_path") or item.get("path") or str(key)
    safe_item = {
        key: value
        for key, value in item.items()
        if key.lower() not in {"raw_record", "credentials", "token", "secret", "password", "dsn"}
    }
    source = SourceFile(
        source_id=required("source_id"),
        stream=required("stream"),
        file_id=str(file_id).strip(),
        source_path=str(source_path),
        object_path=str(object_path),
        mime_type=str(item.get("mime_type") or item.get("content_type") or ""),
        size_bytes=int(item.get("size_bytes") or 0),
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at"),
        source_url=item.get("source_url"),
        metadata=dict(safe_item),
        raw_record=safe_item,
    )
    return NormalizedAirbyteItem(source, str(bucket).strip(), str(key).strip())
