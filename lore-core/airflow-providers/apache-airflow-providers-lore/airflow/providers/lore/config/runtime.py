"""Bounded loader for one ready-rendered Lore runtime YAML document."""

from __future__ import annotations

import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml
from lore_splitter.config import (
    SplitterConfigError,
    validate_splitter_config,
)
from yaml.events import AliasEvent

MAX_CONFIG_BYTES = 128 * 1024
MAX_ALIASES = 50

NUMERIC_BOUNDS: dict[str, tuple[int, int]] = {
    "splitter.embedding_byte_budget": (1, 1_000_000),
    "splitter.max_embedding_unique_values": (1, 10_000),
    "splitter.toast_min_rows": (1, 1_000_000),
    "splitter.toast_min_columns": (1, 100_000),
    "splitter.toast_min_cells": (1, 10_000_000),
    "splitter.max_active_tasks": (1, 256),
    "splitter.retries": (0, 10),
    "viewer.source_url_ttl_seconds": (30, 3_600),
    "viewer.page_size_default": (1, 1_000),
    "viewer.page_size_max": (1, 1_000),
    "viewer.source_context_max_chars": (1_000, 1_000_000),
    "viewer.image_preview_max_pixels": (65_536, 40_000_000),
}

_ROOT_KEYS = frozenset({"schema_version", "splitter", "audit", "viewer"})
_SPLITTER_KEYS = frozenset(
    {
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
        "max_active_tasks",
        "retries",
    }
)
_AUDIT_KEYS = frozenset(
    {"enabled", "ruleset_version", "full_on_success", "contract_on_failed_or_skipped"}
)
_VIEWER_KEYS = frozenset(
    {
        "source_url_ttl_seconds",
        "page_size_default",
        "page_size_max",
        "source_context_max_chars",
        "image_preview_max_pixels",
    }
)
_OPERATOR_KEYS = (
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
_CONNECTION_ID = re.compile(r"^[A-Za-z0-9_.-]+$")
_CREDENTIAL_CONCEPTS = (
    "password",
    "secret",
    "token",
    "credential",
    "access_key",
    "private_key",
    "dsn",
    "uri",
)


class RuntimeConfigError(ValueError):
    """The selected runtime configuration failed a closed validation boundary."""


class _BoundedSafeLoader(yaml.SafeLoader):
    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self._alias_count = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(AliasEvent):
            self._alias_count += 1
            if self._alias_count > MAX_ALIASES:
                raise RuntimeConfigError("YAML alias limit exceeded")
        return super().compose_node(parent, index)


@dataclass(frozen=True)
class SplitterRuntimeConfig:
    s3_conn_id: str
    postgres_conn_id: str
    image_toast_bucket: str
    image_toast_prefix: str
    storage_schema: str
    storage_mode: str
    embedding_byte_budget: int
    max_embedding_unique_values: int
    toast_min_rows: int
    toast_min_columns: int
    toast_min_cells: int
    max_active_tasks: int
    retries: int

    def splitter_operator_config(self) -> dict[str, Any]:
        values = asdict(self)
        projection = {key: values[key] for key in _OPERATOR_KEYS}
        try:
            return validate_splitter_config(projection)
        except SplitterConfigError as exc:
            raise RuntimeConfigError("splitter projection is invalid") from exc


@dataclass(frozen=True)
class AuditRuntimeConfig:
    enabled: bool
    ruleset_version: str
    full_on_success: bool
    contract_on_failed_or_skipped: bool


@dataclass(frozen=True)
class ViewerRuntimeConfig:
    source_url_ttl_seconds: int
    page_size_default: int
    page_size_max: int
    source_context_max_chars: int
    image_preview_max_pixels: int


@dataclass(frozen=True)
class LoreRuntimeConfig:
    schema_version: str
    splitter: SplitterRuntimeConfig
    audit: AuditRuntimeConfig
    viewer: ViewerRuntimeConfig

    def splitter_operator_config(self) -> dict[str, Any]:
        return self.splitter.splitter_operator_config()


def load_runtime_config(path: str | Path) -> LoreRuntimeConfig:
    raw = _read_explicit_file(Path(path))
    data = _parse_one_document(raw)
    _reject_credential_keys(data)
    _require_closed_mapping(data, "root", _ROOT_KEYS)
    if data.get("schema_version") != "lore/runtime/v1":
        raise RuntimeConfigError("schema_version must be lore/runtime/v1")

    splitter_data = _require_closed_mapping(data.get("splitter"), "splitter", _SPLITTER_KEYS)
    audit_data = _require_closed_mapping(data.get("audit"), "audit", _AUDIT_KEYS)
    viewer_data = _require_closed_mapping(data.get("viewer"), "viewer", _VIEWER_KEYS)

    _validate_splitter_strings(splitter_data)
    _validate_audit(audit_data)
    for dotted_name, bounds in NUMERIC_BOUNDS.items():
        section, field = dotted_name.split(".", 1)
        values = splitter_data if section == "splitter" else viewer_data
        _bounded_integer(values.get(field), dotted_name, bounds)
    if viewer_data["page_size_default"] > viewer_data["page_size_max"]:
        raise RuntimeConfigError("viewer page_size_default exceeds page_size_max")

    return LoreRuntimeConfig(
        schema_version="lore/runtime/v1",
        splitter=SplitterRuntimeConfig(**splitter_data),
        audit=AuditRuntimeConfig(**audit_data),
        viewer=ViewerRuntimeConfig(**viewer_data),
    )


def _read_explicit_file(path: Path) -> str:
    try:
        mode = path.stat().st_mode
    except (OSError, ValueError) as exc:
        raise RuntimeConfigError("runtime config path is unavailable") from exc
    if not stat.S_ISREG(mode):
        raise RuntimeConfigError("runtime config path must be a regular file")
    try:
        with path.open("rb") as handle:
            content = handle.read(MAX_CONFIG_BYTES + 1)
    except OSError as exc:
        raise RuntimeConfigError("runtime config file cannot be read") from exc
    if not content:
        raise RuntimeConfigError("runtime config file is empty")
    if len(content) > MAX_CONFIG_BYTES:
        raise RuntimeConfigError("runtime config file exceeds size limit")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeConfigError("runtime config file must be UTF-8") from exc


def _parse_one_document(raw: str) -> dict[str, Any]:
    try:
        documents = list(yaml.load_all(raw, Loader=_BoundedSafeLoader))
    except RuntimeConfigError:
        raise
    except yaml.YAMLError as exc:
        raise RuntimeConfigError("runtime config YAML is invalid") from exc
    if len(documents) != 1 or documents[0] is None:
        raise RuntimeConfigError("runtime config must contain exactly one YAML document")
    if not isinstance(documents[0], dict):
        raise RuntimeConfigError("runtime config root must be a mapping")
    return documents[0]


def _require_closed_mapping(
    value: Any,
    field: str,
    allowed_keys: frozenset[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeConfigError(f"{field} must be a mapping")
    non_string = [key for key in value if not isinstance(key, str)]
    if non_string:
        raise RuntimeConfigError(f"{field} contains a non-string key")
    unexpected = sorted(set(value) - allowed_keys)
    if unexpected:
        raise RuntimeConfigError(f"unexpected {field} key: {unexpected[0]}")
    missing = sorted(allowed_keys - set(value))
    if missing:
        raise RuntimeConfigError(f"missing {field} key: {missing[0]}")
    return value


def _reject_credential_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and any(term in key.casefold() for term in _CREDENTIAL_CONCEPTS):
                raise RuntimeConfigError("credential-shaped configuration key is forbidden")
            _reject_credential_keys(child)
    elif isinstance(value, list):
        for child in value:
            _reject_credential_keys(child)


def _validate_splitter_strings(values: dict[str, Any]) -> None:
    for field in (
        "s3_conn_id",
        "postgres_conn_id",
        "image_toast_bucket",
        "image_toast_prefix",
        "storage_schema",
        "storage_mode",
    ):
        value = values.get(field)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise RuntimeConfigError(f"splitter.{field} must be a non-empty string")
        if "\n" in value or "\r" in value or "://" in value:
            raise RuntimeConfigError(f"splitter.{field} contains a forbidden value")
    for field in ("s3_conn_id", "postgres_conn_id"):
        if not _CONNECTION_ID.fullmatch(values[field]):
            raise RuntimeConfigError(f"splitter.{field} must be an identifier")
    if values["storage_mode"] != "postgres":
        raise RuntimeConfigError("splitter.storage_mode is unsupported")


def _validate_audit(values: dict[str, Any]) -> None:
    for field in ("enabled", "full_on_success", "contract_on_failed_or_skipped"):
        if type(values.get(field)) is not bool:
            raise RuntimeConfigError(f"audit.{field} must be boolean")
    ruleset = values.get("ruleset_version")
    if not isinstance(ruleset, str) or not ruleset.strip() or ruleset != ruleset.strip():
        raise RuntimeConfigError("audit.ruleset_version must be a non-empty string")
    if "\n" in ruleset or "\r" in ruleset or "://" in ruleset:
        raise RuntimeConfigError("audit.ruleset_version contains a forbidden value")


def _bounded_integer(value: Any, field: str, bounds: tuple[int, int]) -> None:
    minimum, maximum = bounds
    if type(value) is not int or not minimum <= value <= maximum:
        raise RuntimeConfigError(f"{field} is outside its allowed integer range")
