from __future__ import annotations

import pytest
from lore_splitter.airflow_item import (
    AirbyteItemError,
    normalize_airbyte_item,
)
from lore_splitter.config import (
    SplitterConfigError,
    content_config_hash,
    validate_splitter_config,
)


def item(**overrides):
    value = {
        "source_id": "drive",
        "stream": "regulations",
        "file_id": "file-1",
        "source_path": "Reports/readme.md",
        "object_path": "Reports/readme.md",
        "mime_type": "text/markdown",
        "size_bytes": 12,
        "bucket": "airbyte-source",
        "key": "staging/readme.md",
    }
    value.update(overrides)
    return value


def test_normalize_airbyte_item_requires_identity_and_source_location():
    normalized = normalize_airbyte_item(item())
    assert normalized.source_file.file_id == "file-1"
    assert normalized.bucket == "airbyte-source"
    assert normalized.key == "staging/readme.md"

    with pytest.raises(AirbyteItemError, match="file identity"):
        normalize_airbyte_item(item(file_id=""))
    with pytest.raises(AirbyteItemError, match="source bucket/key"):
        normalize_airbyte_item(item(bucket=""))


def test_content_hash_excludes_storage_identity_but_changes_with_content_settings():
    base = {
        "s3_conn_id": "source",
        "image_toast_bucket": "images-a",
        "chunk": {"max_tokens": 100},
        "model": "model-a",
    }
    changed_storage = {**base, "s3_conn_id": "source-b", "image_toast_bucket": "images-b"}
    changed_content = {**base, "chunk": {"max_tokens": 101}}
    assert content_config_hash(base) == content_config_hash(changed_storage)
    assert content_config_hash(base) != content_config_hash(changed_content)


def test_validate_splitter_config_fails_without_hidden_defaults():
    with pytest.raises(SplitterConfigError, match="s3_conn_id"):
        validate_splitter_config({"splitter": {}})
    with pytest.raises(SplitterConfigError, match="postgres_conn_id"):
        validate_splitter_config({"splitter": {"s3_conn_id": "shared"}})
    validated = validate_splitter_config({"splitter": {
        "s3_conn_id": "shared",
        "postgres_conn_id": "core",
        "image_toast_bucket": "lore-images",
        "image_toast_prefix": "splitter/images",
        "storage_schema": "lore_core",
        "storage_mode": "durable",
        "embedding_byte_budget": 4096,
        "max_embedding_unique_values": 3,
        "toast_min_rows": 40,
        "toast_min_columns": 8,
        "toast_min_cells": 240,
    }})
    assert validated["s3_conn_id"] == "shared"
