"""Bounded, injected external-image fetching for Markdown documents."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from lore_splitter.documents.contracts import (
    ImageSourceLocation,
    ImageToastCandidate,
)


@dataclass(frozen=True)
class FetchedImage:
    payload: bytes
    content_type: str


Fetcher = Callable[[str, int], FetchedImage | tuple[bytes, str]]


def fetch_external_image(
    url: str,
    *,
    fetcher: Fetcher,
    max_bytes: int = 5 * 1024 * 1024,
    allowed_schemes: frozenset[str] = frozenset({"https"}),
) -> ImageToastCandidate:
    """Fetch one image through an injected bounded fetcher.

    The function never performs network I/O itself and deliberately reports only
    stable validation errors to callers.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in allowed_schemes or not parsed.netloc:
        raise ValueError("external_image_scheme_not_allowed")
    fetched = fetcher(url, max_bytes)
    if isinstance(fetched, tuple):
        payload, content_type = fetched
    else:
        payload, content_type = fetched.payload, fetched.content_type
    if not isinstance(payload, bytes) or len(payload) > max_bytes:
        raise ValueError("external_image_size_limit")
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if not normalized_type.startswith("image/"):
        raise ValueError("external_image_content_type_not_allowed")
    extension = "." + normalized_type.split("/", 1)[1].replace("jpeg", "jpg")
    checksum = hashlib.sha256(payload).hexdigest()
    return ImageToastCandidate(
        payload=payload,
        content_type=normalized_type,
        extension=extension,
        byte_size=len(payload),
        checksum_sha256=checksum,
        width_px=None,
        height_px=None,
        source_identity={"source_url": url},
        source_location=ImageSourceLocation(
            source_format="markdown",
            metadata={"external": True, "url": url},
        ),
    )
