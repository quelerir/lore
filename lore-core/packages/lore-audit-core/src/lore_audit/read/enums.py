"""Shared StrEnums and scalar caps for the audit read domain."""

from __future__ import annotations

from enum import StrEnum

_COUNT_CAP = 10_000
_BYTE_CAP = 100_000_000


class Availability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ImageDeliveryKind(StrEnum):
    INLINE_PREVIEW = "inline_preview"
    TEMPORARY_LINK = "temporary_link"
    UNAVAILABLE = "unavailable"


class SourceHashState(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"


__all__ = [
    "Availability",
    "ImageDeliveryKind",
    "SourceHashState",
    "_BYTE_CAP",
    "_COUNT_CAP",
]
