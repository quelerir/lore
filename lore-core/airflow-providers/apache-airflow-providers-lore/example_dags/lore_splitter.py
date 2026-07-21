"""Explicit paired Lore Splitter and exact-run deterministic audit DAG."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from airflow.providers.lore.config import load_runtime_config
from airflow.providers.lore.operators import (
    LoreSplitterAuditOperator,
    LoreSplitterOperator,
)
from airflow.sdk import dag, get_current_context, task
from airflow.utils.trigger_rule import TriggerRule

DEFAULT_RUNTIME_CONFIG_PATH = "/opt/airflow/dags/configs/lore.yaml"
MAX_FILE_ITEMS = 1_000
MAX_FILE_ITEM_BYTES = 64 * 1024
_REQUIRED_FILE_ITEM_KEYS = frozenset({"source_id", "stream", "file_id", "bucket", "key"})
_OPTIONAL_FILE_ITEM_KEYS = frozenset(
    {
        "source_path",
        "object_path",
        "mime_type",
        "size_bytes",
        "created_at",
        "updated_at",
        "source_url",
        "metadata",
    }
)
_FILE_ITEM_KEYS = _REQUIRED_FILE_ITEM_KEYS | _OPTIONAL_FILE_ITEM_KEYS

RUNTIME_CONFIG_PATH = os.environ.get("LORE_CONFIG_PATH") or DEFAULT_RUNTIME_CONFIG_PATH
RUNTIME_CONFIG = load_runtime_config(RUNTIME_CONFIG_PATH)


def _validated_item(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"file_items[{index}] must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"file_items[{index}] keys must be strings")
    unexpected = set(value) - _FILE_ITEM_KEYS
    missing = _REQUIRED_FILE_ITEM_KEYS - set(value)
    if unexpected or missing:
        raise ValueError(f"file_items[{index}] has an invalid shape")
    for key in _REQUIRED_FILE_ITEM_KEYS:
        field = value[key]
        if not isinstance(field, str) or not field.strip() or field != field.strip():
            raise ValueError(f"file_items[{index}].{key} must be a non-empty string")
    if "size_bytes" in value and (
        type(value["size_bytes"]) is not int or value["size_bytes"] < 0
    ):
        raise ValueError(f"file_items[{index}].size_bytes must be a non-negative integer")
    if "metadata" in value and not isinstance(value["metadata"], dict):
        raise ValueError(f"file_items[{index}].metadata must be a mapping")
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"file_items[{index}] must be JSON-compatible") from exc
    if len(encoded) > MAX_FILE_ITEM_BYTES:
        raise ValueError(f"file_items[{index}] exceeds the size limit")
    return dict(value)


@task(task_id="validated_file_items")
def validated_file_items() -> list[dict[str, Any]]:
    context = get_current_context()
    dag_run = context.get("dag_run")
    conf = getattr(dag_run, "conf", None)
    values = conf.get("file_items") if isinstance(conf, dict) else None
    if not isinstance(values, list):
        raise ValueError("dag_run.conf.file_items must be a list")
    if len(values) > MAX_FILE_ITEMS:
        raise ValueError("dag_run.conf.file_items exceeds the item limit")
    return [_validated_item(value, index) for index, value in enumerate(values)]


@dag(
    dag_id="lore_splitter",
    schedule=None,
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    catchup=False,
)
def _build_lore_splitter_dag() -> None:
    file_items = validated_file_items()
    split_file = LoreSplitterOperator.partial(
        task_id="split_file",
        configurations=RUNTIME_CONFIG.splitter_operator_config(),
        max_active_tis_per_dag=RUNTIME_CONFIG.splitter.max_active_tasks,
        retries=RUNTIME_CONFIG.splitter.retries,
    ).expand(file_item=file_items)
    audit_file = LoreSplitterAuditOperator.partial(
        task_id="audit_file",
        splitter_task_id="split_file",
        postgres_conn_id=RUNTIME_CONFIG.splitter.postgres_conn_id,
        s3_conn_id=RUNTIME_CONFIG.splitter.s3_conn_id,
        ruleset_version=RUNTIME_CONFIG.audit.ruleset_version,
        trigger_rule=TriggerRule.ALL_DONE,
    ).expand(file_item=file_items)
    split_file >> audit_file


lore_splitter = _build_lore_splitter_dag()
