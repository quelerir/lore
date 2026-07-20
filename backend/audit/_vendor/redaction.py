"""Redaction helpers vendored verbatim from splitter/per_file.py (lines 33-121)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SECRET_KEY = re.compile(
    r"(token|secret|password|passwd|credential|authorization|api[_-]?key|dsn|signature|signed[_-]?url)",
    re.I,
)
_DSN = re.compile(r"(?:postgres(?:ql)?|mysql|redis)://[^\s]+", re.I)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I)
_HTTP_URL = re.compile(r"https?://[^\s<>'\"]{1,2048}", re.I)


def _redact_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme and parts.netloc:
        _, at, host = parts.netloc.rpartition("@")
        netloc = host if at else parts.netloc
        query = [
            (key, "[redacted]")
            if _SECRET_KEY.search(key)
            or key.lower() in {"x-amz-signature", "sig", "signature", "token"}
            else (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
        ]
        value = urlunsplit(
            (parts.scheme, netloc, parts.path, urlencode(query), parts.fragment)
        )
    return value


def redact_text(value: str) -> str:
    value = _DSN.sub("[redacted-dsn]", value)
    value = _BEARER.sub("[redacted-token]", value)
    value = _HTTP_URL.sub(lambda match: _redact_url(match.group(0)), value)
    return _redact_url(value)


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: "[redacted]" if _SECRET_KEY.search(str(key)) else redact_value(item)
            for key, item in value.items()
            if not _SECRET_KEY.search(str(key)) or item is None
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value
