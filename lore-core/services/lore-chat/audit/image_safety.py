"""Validation for raster images that may be rendered inline by audit clients."""

from __future__ import annotations

_SAFE_RASTER_TYPES = frozenset(
    {
        "image/gif",
        "image/jpeg",
        "image/jpg",
        "image/png",
        "image/webp",
    }
)


def validate_safe_raster_content_type(value: object) -> str:
    """Return one exact safe raster media type or reject it without reflection."""

    if type(value) is not str or value not in _SAFE_RASTER_TYPES:
        raise ValueError("unsafe raster media type")
    return value


def validate_safe_raster_payload(content_type: object, payload: object) -> bytes:
    """Match bounded bytes to the registered raster type using format signatures."""

    selected = validate_safe_raster_content_type(content_type)
    if type(payload) is not bytes:
        raise ValueError("unsafe raster payload")
    signatures = {
        "image/gif": payload.startswith((b"GIF87a", b"GIF89a")),
        "image/jpeg": payload.startswith(b"\xff\xd8\xff"),
        "image/jpg": payload.startswith(b"\xff\xd8\xff"),
        "image/png": payload.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/webp": (
            len(payload) >= 12
            and payload.startswith(b"RIFF")
            and payload[8:12] == b"WEBP"
        ),
    }
    if not signatures[selected]:
        raise ValueError("unsafe raster payload")
    return payload


__all__ = ["validate_safe_raster_content_type", "validate_safe_raster_payload"]
