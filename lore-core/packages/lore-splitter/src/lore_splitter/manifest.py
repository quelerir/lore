from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lore_splitter.contracts import ManifestDiagnostic, SourceFile


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class ManifestLoadResult:
    records: list[SourceFile]
    diagnostics: list[ManifestDiagnostic]
    declared_size_bytes: int


ALIASES = {
    "source_id": ("source_id", "datasource_id", "datasource", "connector", "source"),
    "stream": ("stream", "stream_name", "name"),
    "file_id": ("file_id", "id", "drive_id", "source_file_id"),
    "source_path": ("source_path", "path", "source_relative_path", "relative_path"),
    "object_path": ("object_path", "staging_path", "staging_file_path", "s3_path", "uri"),
    "mime_type": ("mime_type", "mime", "content_type"),
    "size_bytes": ("size_bytes", "bytes", "size", "file_size"),
}


def load_manifest(path: str | Path) -> ManifestLoadResult:
    manifest_path = Path(path)
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"Could not read manifest {manifest_path}: {exc}") from exc

    raw_records = _parse_manifest_text(text, manifest_path)
    records: list[SourceFile] = []
    diagnostics: list[ManifestDiagnostic] = []
    declared_size_bytes = 0
    for raw in raw_records:
        declared_size_bytes += _declared_size(raw)
        source_file, diagnostic = _normalize_record(raw)
        if source_file is not None:
            records.append(source_file)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    return ManifestLoadResult(
        records=records,
        diagnostics=diagnostics,
        declared_size_bytes=declared_size_bytes,
    )


def _parse_manifest_text(text: str, path: Path) -> list[dict[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return []

    if path.suffix.lower() == ".jsonl":
        records = []
        for line_number, line in enumerate(stripped.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ManifestError(f"Invalid JSONL at line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ManifestError(f"Invalid JSONL at line {line_number}: expected object")
            records.append(value)
        return records

    try:
        value = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Invalid JSON manifest {path}: {exc}") from exc

    if isinstance(value, dict):
        if isinstance(value.get("records"), list):
            value = value["records"]
        else:
            return [value]
    if not isinstance(value, list):
        raise ManifestError("Invalid JSON manifest: expected object, records object, or list")
    if not all(isinstance(item, dict) for item in value):
        raise ManifestError("Invalid JSON manifest: every record must be an object")
    return value


def _normalize_record(raw: dict[str, Any]) -> tuple[SourceFile | None, ManifestDiagnostic | None]:
    values = {field: _first_present(raw, aliases) for field, aliases in ALIASES.items()}
    required_fields = set(ALIASES) - {"mime_type"}
    missing = [
        field
        for field, value in values.items()
        if field in required_fields and (value is None or value == "")
    ]
    if missing:
        return None, ManifestDiagnostic(
            reason="invalid_record",
            message=f"Missing required field: {', '.join(missing)}",
            source_id=_optional_str(values.get("source_id")),
            stream=_optional_str(values.get("stream")),
            file_id=_optional_str(values.get("file_id")),
            source_path=_optional_str(values.get("source_path")),
            object_path=_optional_str(values.get("object_path")),
        )

    try:
        size_bytes = int(values["size_bytes"])
    except (TypeError, ValueError):
        return None, ManifestDiagnostic(
            reason="invalid_record",
            message="Invalid required field: size_bytes must be an integer",
            source_id=_optional_str(values.get("source_id")),
            stream=_optional_str(values.get("stream")),
            file_id=_optional_str(values.get("file_id")),
            source_path=_optional_str(values.get("source_path")),
            object_path=_optional_str(values.get("object_path")),
        )

    metadata = raw.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {
            key: value
            for key, value in raw.items()
            if key not in {alias for aliases in ALIASES.values() for alias in aliases}
            and key not in {"created_at", "updated_at", "modified_at", "source_url", "url"}
        }

    return (
        SourceFile(
            source_id=str(values["source_id"]),
            stream=str(values["stream"]),
            file_id=str(values["file_id"]),
            source_path=str(values["source_path"]),
            object_path=str(values["object_path"]),
            mime_type=_optional_str(values["mime_type"]) or "",
            size_bytes=size_bytes,
            created_at=_optional_str(_first_present(raw, ("created_at", "createdAt"))),
            updated_at=_optional_str(
                _first_present(raw, ("updated_at", "updatedAt", "modified_at"))
            ),
            source_url=_optional_str(_first_present(raw, ("source_url", "url", "web_url"))),
            metadata=metadata,
            raw_record=raw,
        ),
        None,
    )


def _first_present(raw: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in raw:
            return raw[key]
    return None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _declared_size(raw: dict[str, Any]) -> int:
    value = _first_present(raw, ALIASES["size_bytes"])
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
