from __future__ import annotations


def normalize_markdown_source(markdown: str) -> str:
    normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.rstrip("\n") + "\n"
