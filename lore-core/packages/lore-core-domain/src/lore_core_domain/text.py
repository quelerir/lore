from __future__ import annotations

import unicodedata


def normalize_text(value: str) -> str:
    """Normalize only Unicode, line endings, and the final newline."""
    if not isinstance(value, str):
        raise TypeError("text must be a string")
    return (
        unicodedata.normalize("NFC", value).replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
        + "\n"
    )
