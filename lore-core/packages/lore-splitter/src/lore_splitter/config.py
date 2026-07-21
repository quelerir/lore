"""Validation and identity projection for resolved Splitter configuration."""

from __future__ import annotations

import hashlib
import json
from typing import Any


class SplitterConfigError(ValueError):
    """Invalid resolved Splitter configuration."""


_STORAGE_KEYS = frozenset(
    {"s3_conn_id", "postgres_conn_id", "image_toast_bucket", "image_toast_prefix", "storage_schema"}
)

_REQUIRED_RESOLVED_KEYS = (
    "s3_conn_id",
    "postgres_conn_id",
    "image_toast_bucket",
    "image_toast_prefix",
    "storage_schema",
    "storage_mode",
    "embedding_byte_budget",
    "max_embedding_unique_values",
    "toast_min_rows",
    "toast_min_columns",
    "toast_min_cells",
)


def validate_splitter_config(configurations: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(configurations, dict):
        raise SplitterConfigError("configurations must be a mapping")
    splitter = configurations.get("splitter", configurations)
    if not isinstance(splitter, dict):
        raise SplitterConfigError("splitter configuration must be a mapping")
    for key in _REQUIRED_RESOLVED_KEYS:
        if splitter.get(key) is None or not str(splitter.get(key)).strip():
            raise SplitterConfigError(f"missing required splitter key: {key}")
    return dict(splitter)


def content_config_hash(config: dict[str, Any]) -> str:
    projection = _project_content_settings(config)
    encoded = json.dumps(projection, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _project_content_settings(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            child_key: _project_content_settings(child_value, child_key)
            for child_key, child_value in sorted(value.items())
            if child_key not in _STORAGE_KEYS
        }
    if isinstance(value, list):
        return [_project_content_settings(item) for item in value]
    return value
