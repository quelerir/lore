"""Authenticated opaque cursors and UTF-8-safe text continuations."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from lore_audit.read import AuditReadError, TextWindow

_TOKEN_VERSION = 1
_MAX_TOKEN_BYTES = 4_096
_TEXT_FIELDS = frozenset({"display_text", "full_text", "vector_text"})
_TYPED_VALUE_TAG = "__lore_cursor_type__"
_TYPED_VALUE_KEYS = frozenset({_TYPED_VALUE_TAG, "value"})


def _encode_page_value(value: Any) -> Any:
    if type(value) is Decimal:
        return {_TYPED_VALUE_TAG: "decimal", "value": str(value)}
    if type(value) is date:
        return {_TYPED_VALUE_TAG: "date", "value": value.isoformat()}
    if value is None or type(value) in {bool, int, float, str}:
        return value
    raise AuditReadError("invalid_cursor")


def _decode_page_value(value: Any) -> Any:
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if not isinstance(value, dict) or set(value) != _TYPED_VALUE_KEYS:
        raise AuditReadError("invalid_cursor")
    kind = value.get(_TYPED_VALUE_TAG)
    encoded = value.get("value")
    if not isinstance(encoded, str):
        raise AuditReadError("invalid_cursor")
    try:
        if kind == "decimal":
            return Decimal(encoded)
        if kind == "date":
            return date.fromisoformat(encoded)
    except (InvalidOperation, ValueError):
        raise AuditReadError("invalid_cursor") from None
    raise AuditReadError("invalid_cursor")


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise AuditReadError("invalid_cursor") from None


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > _MAX_TOKEN_BYTES * 2:
        raise AuditReadError("invalid_cursor")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError):
        raise AuditReadError("invalid_cursor") from None
    if len(decoded) > _MAX_TOKEN_BYTES:
        raise AuditReadError("invalid_cursor")
    return decoded


@dataclass(frozen=True)
class CursorCodec:
    key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.key, bytes) or len(self.key) < 16:
            raise ValueError("cursor key must contain at least 16 bytes")

    def _encode(self, payload: dict[str, Any]) -> str:
        encoded = _canonical(payload)
        if len(encoded) > _MAX_TOKEN_BYTES:
            raise AuditReadError("bounds_exceeded")
        signature = hmac.new(self.key, encoded, hashlib.sha256).digest()
        return f"{_b64encode(encoded)}.{_b64encode(signature)}"

    def _decode(self, token: str) -> dict[str, Any]:
        try:
            payload_part, signature_part = token.split(".")
            encoded = _b64decode(payload_part)
            signature = _b64decode(signature_part)
            expected = hmac.new(self.key, encoded, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise AuditReadError("invalid_cursor")
            payload = json.loads(encoded)
        except (AttributeError, ValueError, json.JSONDecodeError):
            raise AuditReadError("invalid_cursor") from None
        if not isinstance(payload, dict) or payload.get("version") != _TOKEN_VERSION:
            raise AuditReadError("invalid_cursor")
        return payload

    def encode_page(
        self,
        *,
        operation: str,
        sort: str,
        filters: dict[str, Any],
        last: tuple[Any, ...],
    ) -> str:
        if not operation or not sort or not isinstance(filters, dict) or not last:
            raise AuditReadError("invalid_request")
        return self._encode(
            {
                "version": _TOKEN_VERSION,
                "kind": "page",
                "operation": operation,
                "sort": sort,
                "filters": json.loads(_canonical(filters)),
                "last": [_encode_page_value(value) for value in last],
            }
        )

    def decode_page(
        self,
        token: str,
        *,
        operation: str,
        sort: str,
        filters: dict[str, Any],
    ) -> tuple[Any, ...]:
        payload = self._decode(token)
        expected_filters = json.loads(_canonical(filters))
        expected = {
            "version": _TOKEN_VERSION,
            "kind": "page",
            "operation": operation,
            "sort": sort,
            "filters": expected_filters,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise AuditReadError("invalid_cursor")
        if set(payload) != {*expected, "last"} or not isinstance(payload["last"], list):
            raise AuditReadError("invalid_cursor")
        return tuple(_decode_page_value(value) for value in payload["last"])

    def encode_text(
        self,
        *,
        run_id: str,
        chunk_id: str,
        field_name: str,
        offset: int,
        max_bytes: int,
        content_hash: str,
    ) -> str:
        return self._encode(
            {
                "version": _TOKEN_VERSION,
                "kind": "text",
                "run_id": run_id,
                "chunk_id": chunk_id,
                "field": field_name,
                "offset": offset,
                "max_bytes": max_bytes,
                "content_hash": content_hash,
            }
        )

    def decode_text(
        self,
        token: str,
        *,
        run_id: str,
        chunk_id: str,
        field_name: str,
        max_bytes: int,
        content_hash: str,
    ) -> int:
        payload = self._decode(token)
        expected = {
            "version": _TOKEN_VERSION,
            "kind": "text",
            "run_id": run_id,
            "chunk_id": chunk_id,
            "field": field_name,
            "max_bytes": max_bytes,
            "content_hash": content_hash,
        }
        if set(payload) != {*expected, "offset"}:
            raise AuditReadError("invalid_cursor")
        if any(payload.get(key) != value for key, value in expected.items()):
            raise AuditReadError("invalid_cursor")
        offset = payload.get("offset")
        if type(offset) is not int or offset <= 0:
            raise AuditReadError("invalid_cursor")
        return offset


@dataclass(frozen=True)
class TextWindowBuilder:
    codec: CursorCodec

    def window(
        self,
        value: str,
        *,
        run_id: str,
        chunk_id: str,
        field: str,
        content_hash: str,
        max_bytes: int,
        continuation: str | None = None,
    ) -> TextWindow:
        if field not in _TEXT_FIELDS or type(max_bytes) is not int or max_bytes <= 0:
            raise AuditReadError("invalid_request")
        if not isinstance(value, str) or not run_id or not chunk_id or not content_hash:
            raise AuditReadError("invalid_request")
        encoded = value.encode("utf-8")
        offset = 0
        if continuation is not None:
            offset = self.codec.decode_text(
                continuation,
                run_id=run_id,
                chunk_id=chunk_id,
                field_name=field,
                max_bytes=max_bytes,
                content_hash=content_hash,
            )
        if offset >= len(encoded):
            raise AuditReadError("invalid_cursor")
        end = min(offset + max_bytes, len(encoded))
        while end > offset:
            try:
                text = encoded[offset:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        else:
            raise AuditReadError("bounds_exceeded")
        truncated = end < len(encoded)
        token = None
        if truncated:
            token = self.codec.encode_text(
                run_id=run_id,
                chunk_id=chunk_id,
                field_name=field,
                offset=end,
                max_bytes=max_bytes,
                content_hash=content_hash,
            )
        return TextWindow(text, truncated, end - offset, len(encoded), token)


__all__ = ["CursorCodec", "TextWindowBuilder"]
