import hashlib


def projection_id(index_version: str, canonical_id: str) -> str:
    return f"{index_version}:{canonical_id}"


def section_prefixes(heading_path: tuple[str, ...]) -> list[tuple[str, ...]]:
    return [tuple(heading_path[: i + 1]) for i in range(len(heading_path))]


def section_id(document_id: str, heading_path: tuple[str, ...]) -> str:
    # Deterministic, collision-resistant, stable per (document, path).
    # \x1f (unit separator) cannot appear in heading text, so it is an
    # unambiguous delimiter between path segments and the document id.
    payload = document_id + "\x1e" + "\x1f".join(heading_path)
    return "sec_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]
