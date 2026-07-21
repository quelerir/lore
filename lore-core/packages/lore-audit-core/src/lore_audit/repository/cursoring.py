"""Keyset pagination cursor helpers local to the audit read repository."""

from __future__ import annotations

from typing import Any

from lore_audit.read_contracts import AuditReadError
from lore_audit.read_cursor import CursorCodec


def decode_page_cursor(
    codec: CursorCodec,
    cursor: str,
    *,
    operation: str,
    sort: str,
    filters: dict[str, Any],
) -> tuple[Any, ...]:
    """Decode a page cursor token and return the keyset last-seen tuple."""
    return codec.decode_page(cursor, operation=operation, sort=sort, filters=filters)


def encode_page_cursor(
    codec: CursorCodec,
    *,
    operation: str,
    sort: str,
    filters: dict[str, Any],
    last: tuple[Any, ...],
) -> str:
    """Encode a keyset last-seen tuple as a page cursor token."""
    return codec.encode_page(operation=operation, sort=sort, filters=filters, last=last)


__all__ = [
    "decode_page_cursor",
    "encode_page_cursor",
]
