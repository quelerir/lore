"""Pure validation helpers for stable audit identity and bounded safe values."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from lore_core_domain.redaction import redact_value

MAX_RULESET_VERSION_LENGTH = 128
MAX_TARGET_KIND_LENGTH = 64
MAX_TARGET_ID_LENGTH = 128
MAX_RULE_ID_LENGTH = 128
MAX_REASON_CODE_LENGTH = 64
MAX_DIAGNOSTIC_KEY_LENGTH = 512
MAX_SAFE_JSON_DEPTH = 6
MAX_SAFE_JSON_ITEMS = 256
MAX_SAFE_JSON_STRING_LENGTH = 2048
MAX_SAFE_JSON_BYTES = 16384

_IDENTIFIER = re.compile(r"[a-z0-9_.-]+", re.ASCII)
_RULESET_VERSION = re.compile(r"[a-z0-9_.-]+(?:/[a-z0-9_.-]+)*", re.ASCII)


class _FrozenMapping(tuple):
    """Tuple-of-pairs marker that keeps empty mappings distinct from sequences."""


def _validate_component(value: str, *, name: str, max_length: int, allow_slash: bool) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    if not value or len(value) > max_length:
        raise ValueError(f"{name} length is outside the allowed range")
    grammar = _RULESET_VERSION if allow_slash else _IDENTIFIER
    if grammar.fullmatch(value) is None:
        raise ValueError(f"{name} contains unsupported characters")
    return value


def validate_ruleset_version(value: str) -> str:
    return _validate_component(
        value,
        name="ruleset_version",
        max_length=MAX_RULESET_VERSION_LENGTH,
        allow_slash=True,
    )


def validate_target_kind(value: str) -> str:
    return _validate_component(
        value,
        name="target_kind",
        max_length=MAX_TARGET_KIND_LENGTH,
        allow_slash=False,
    )


def validate_target_id(value: str) -> str:
    return _validate_component(
        value,
        name="target_id",
        max_length=MAX_TARGET_ID_LENGTH,
        allow_slash=False,
    )


def validate_rule_id(value: str) -> str:
    return _validate_component(
        value,
        name="rule_id",
        max_length=MAX_RULE_ID_LENGTH,
        allow_slash=False,
    )


def validate_reason_code(value: str) -> str:
    return _validate_component(
        value,
        name="reason_code",
        max_length=MAX_REASON_CODE_LENGTH,
        allow_slash=False,
    )


def build_diagnostic_key(
    ruleset_version: str,
    target_kind: str,
    target_id: str,
    rule_id: str,
) -> str:
    """Build the canonical ruleset-first diagnostic identity."""

    components = (
        validate_ruleset_version(ruleset_version),
        validate_target_kind(target_kind),
        validate_target_id(target_id),
        validate_rule_id(rule_id),
    )
    key = ":".join(components)
    if len(key) > MAX_DIAGNOSTIC_KEY_LENGTH:
        raise ValueError("diagnostic key exceeds the allowed length")
    return key


def _bounded_copy(value: Any, *, depth: int, item_count: list[int]) -> Any:
    if depth > MAX_SAFE_JSON_DEPTH:
        raise ValueError("safe JSON exceeds the maximum depth")
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("safe JSON floats must be finite")
        return value
    if isinstance(value, str):
        if len(value) > MAX_SAFE_JSON_STRING_LENGTH:
            raise ValueError("safe JSON string exceeds the maximum length")
        return value
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, item in value.items():
            item_count[0] += 1
            if item_count[0] > MAX_SAFE_JSON_ITEMS:
                raise ValueError("safe JSON exceeds the maximum items")
            if not isinstance(key, str):
                raise TypeError("safe JSON mapping keys must be strings")
            if len(key) > MAX_SAFE_JSON_STRING_LENGTH:
                raise ValueError("safe JSON string exceeds the maximum length")
            copied[key] = _bounded_copy(item, depth=depth + 1, item_count=item_count)
        return copied
    if isinstance(value, (list, tuple)):
        copied_items = []
        for item in value:
            item_count[0] += 1
            if item_count[0] > MAX_SAFE_JSON_ITEMS:
                raise ValueError("safe JSON exceeds the maximum items")
            copied_items.append(_bounded_copy(item, depth=depth + 1, item_count=item_count))
        return copied_items
    raise TypeError(f"unsupported safe JSON value: {type(value).__name__}")


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenMapping((key, _freeze(item)) for key, item in sorted(value.items()))
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def safe_json_to_dict(value: Any) -> Any:
    """Project an immutable safe value into explicit JSON-compatible values."""

    if isinstance(value, _FrozenMapping):
        return {key: safe_json_to_dict(item) for key, item in value}
    if isinstance(value, tuple):
        return [safe_json_to_dict(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError("value is not canonical safe JSON")


def canonicalize_safe_json(value: Any) -> Any:
    """Validate, redact, bound, sort, and deeply freeze a JSON-compatible value."""

    copied = _bounded_copy(value, depth=0, item_count=[0])
    canonical = _freeze(redact_value(copied))
    projected = safe_json_to_dict(canonical)
    encoded = json.dumps(
        projected,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_SAFE_JSON_BYTES:
        raise ValueError("safe JSON exceeds the maximum serialized bytes")
    return canonical


def utc_iso8601(value: datetime) -> str:
    """Serialize an aware zero-offset datetime with the canonical ``Z`` suffix."""

    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("datetime must be aware and UTC")
    return value.replace(tzinfo=None).isoformat(timespec="auto") + "Z"


__all__ = [
    "MAX_DIAGNOSTIC_KEY_LENGTH",
    "MAX_REASON_CODE_LENGTH",
    "MAX_RULESET_VERSION_LENGTH",
    "MAX_RULE_ID_LENGTH",
    "MAX_SAFE_JSON_BYTES",
    "MAX_SAFE_JSON_DEPTH",
    "MAX_SAFE_JSON_ITEMS",
    "MAX_SAFE_JSON_STRING_LENGTH",
    "MAX_TARGET_ID_LENGTH",
    "MAX_TARGET_KIND_LENGTH",
    "build_diagnostic_key",
    "canonicalize_safe_json",
    "safe_json_to_dict",
    "utc_iso8601",
]
