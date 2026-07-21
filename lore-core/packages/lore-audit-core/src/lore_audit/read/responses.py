"""Response, detail, and card dataclasses for the audit read domain."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from lore_audit.run_status import RunStatus
from lore_audit.validation import (
    canonicalize_safe_json,
    safe_json_to_dict,
    utc_iso8601,
)
from lore_audit.read.enums import Availability, ImageDeliveryKind, SourceHashState
from lore_audit.read.requests import ReadBounds

_TERMINAL = {
    RunStatus.SUCCESS,
    RunStatus.SKIPPED,
    RunStatus.FAILED,
    RunStatus.STALE,
}


def _non_empty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _non_negative(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class FileCard:
    logical_file_key: str
    display_name: str
    latest_status: RunStatus
    run_count: int
    latest_run_id: str | None
    schema_version: ClassVar[str] = "audit-read/file-card/v1"

    def __post_init__(self) -> None:
        _non_empty(self.logical_file_key, "logical_file_key")
        _non_empty(self.display_name, "display_name")
        if not isinstance(self.latest_status, RunStatus):
            raise TypeError("latest_status must be a RunStatus")
        _non_negative(self.run_count, "run_count")
        if self.latest_run_id is not None:
            _non_empty(self.latest_run_id, "latest_run_id")

    @property
    def identity(self) -> str:
        return self.logical_file_key

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.display_name.casefold(), self.logical_file_key)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "logical_file_key": self.logical_file_key,
            "display_name": self.display_name,
            "latest_status": self.latest_status.value,
            "run_count": self.run_count,
            "latest_run_id": self.latest_run_id,
        }


@dataclass(frozen=True)
class ReadRunDetail:
    run_id: str
    logical_file_key: str
    status: RunStatus
    source_content_hash: str
    config_hash: str
    claimed_at: datetime
    finished_at: datetime | None
    chunk_count: int
    payload_count: int
    warning_count: int
    error_count: int
    schema_version: ClassVar[str] = "audit-read/run-detail/v1"

    def __post_init__(self) -> None:
        for name in ("run_id", "logical_file_key", "source_content_hash", "config_hash"):
            _non_empty(getattr(self, name), name)
        if not isinstance(self.status, RunStatus):
            raise TypeError("status must be a RunStatus")
        utc_iso8601(self.claimed_at)
        if self.status in _TERMINAL and self.finished_at is None:
            raise ValueError("terminal read run requires finished_at")
        if self.status is RunStatus.ACTIVE and self.finished_at is not None:
            raise ValueError("active read run cannot have finished_at")
        if self.finished_at is not None:
            utc_iso8601(self.finished_at)
            if self.finished_at < self.claimed_at:
                raise ValueError("finished_at must not precede claimed_at")
        for name in ("chunk_count", "payload_count", "warning_count", "error_count"):
            _non_negative(getattr(self, name), name)

    @property
    def identity(self) -> str:
        return self.run_id

    @property
    def sort_key(self) -> tuple[datetime, str]:
        return (self.claimed_at, self.run_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "logical_file_key": self.logical_file_key,
            "status": self.status.value,
            "source_content_hash": self.source_content_hash,
            "config_hash": self.config_hash,
            "claimed_at": utc_iso8601(self.claimed_at),
            "finished_at": utc_iso8601(self.finished_at) if self.finished_at else None,
            "chunk_count": self.chunk_count,
            "payload_count": self.payload_count,
            "warning_count": self.warning_count,
            "error_count": self.error_count,
        }


@dataclass(frozen=True)
class ChunkPreview:
    chunk_id: str
    run_id: str
    ordinal: int
    pipeline_type: str
    chunk_type: str
    content_signature: str
    schema_version: ClassVar[str] = "audit-read/chunk-preview/v1"

    def __post_init__(self) -> None:
        for name in ("chunk_id", "run_id", "pipeline_type", "chunk_type", "content_signature"):
            _non_empty(getattr(self, name), name)
        _non_negative(self.ordinal, "ordinal")

    @property
    def identity(self) -> str:
        return self.chunk_id

    @property
    def sort_key(self) -> tuple[int, str]:
        return (self.ordinal, self.chunk_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "chunk_id": self.chunk_id,
            "run_id": self.run_id,
            "ordinal": self.ordinal,
            "pipeline_type": self.pipeline_type,
            "chunk_type": self.chunk_type,
            "content_signature": self.content_signature,
        }


@dataclass(frozen=True)
class TextWindow:
    text: str
    truncated: bool
    returned_bytes: int
    full_bytes: int
    continuation: str | None = None
    schema_version: ClassVar[str] = "audit-read/text-window/v1"

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not isinstance(self.truncated, bool):
            raise TypeError("invalid text window")
        _non_negative(self.returned_bytes, "returned_bytes")
        _non_negative(self.full_bytes, "full_bytes")
        if self.returned_bytes != len(self.text.encode("utf-8")):
            raise ValueError("returned_bytes does not match text")
        if self.returned_bytes > self.full_bytes:
            raise ValueError("returned_bytes exceeds full_bytes")
        if self.truncated != (self.continuation is not None):
            raise ValueError("truncation and continuation disagree")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "text": self.text,
            "truncated": self.truncated,
            "returned_bytes": self.returned_bytes,
            "full_bytes": self.full_bytes,
            "continuation": self.continuation,
        }


@dataclass(frozen=True)
class ChunkDetail:
    preview: ChunkPreview
    display_text: TextWindow
    full_text: TextWindow
    vector_text: TextWindow
    coordinates: Any = field(default_factory=dict)
    payload_refs: tuple[str, ...] = ()
    schema_version: ClassVar[str] = "audit-read/chunk-detail/v1"

    def __post_init__(self) -> None:
        if not isinstance(self.preview, ChunkPreview):
            raise TypeError("preview must be a ChunkPreview")
        for name in ("display_text", "full_text", "vector_text"):
            if not isinstance(getattr(self, name), TextWindow):
                raise TypeError(f"{name} must be a TextWindow")
        refs = tuple(self.payload_refs)
        if any(not isinstance(value, str) or not value for value in refs):
            raise ValueError("payload_refs contains an invalid identity")
        if len(refs) != len(set(refs)):
            raise ValueError("payload_refs contains a duplicate identity")
        object.__setattr__(self, "payload_refs", tuple(sorted(refs)))
        object.__setattr__(self, "coordinates", canonicalize_safe_json(self.coordinates))

    @property
    def identity(self) -> str:
        return self.preview.chunk_id

    @property
    def sort_key(self) -> tuple[int, str]:
        return self.preview.sort_key

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "preview": self.preview.to_dict(),
            "display_text": self.display_text.to_dict(),
            "full_text": self.full_text.to_dict(),
            "vector_text": self.vector_text.to_dict(),
            "coordinates": safe_json_to_dict(self.coordinates),
            "payload_refs": list(self.payload_refs),
        }


@dataclass(frozen=True)
class ReadPage:
    items: tuple[Any, ...]
    order_key: str
    next_cursor: str | None = None
    truncated: bool = False
    schema_version: ClassVar[str] = "audit-read/page/v1"

    def __post_init__(self) -> None:
        _non_empty(self.order_key, "order_key")
        items = tuple(self.items)
        if any(not hasattr(item, "identity") or not hasattr(item, "to_dict") for item in items):
            raise TypeError("page items must be typed read DTOs")
        identities = tuple(item.identity for item in items)
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate page identity")
        object.__setattr__(self, "items", tuple(sorted(items, key=lambda item: item.sort_key)))
        if self.truncated != (self.next_cursor is not None):
            raise ValueError("page truncation and cursor disagree")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "order_key": self.order_key,
            "items": [item.to_dict() for item in self.items],
            "next_cursor": self.next_cursor,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class SensitiveValue:
    value: str | bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.value, (str, bytes)) or not self.value:
            raise ValueError("sensitive value must not be empty")

    def __repr__(self) -> str:
        return "SensitiveValue(<redacted>)"


@dataclass(frozen=True)
class ImageDelivery:
    payload_id: str
    availability: Availability
    kind: ImageDeliveryKind
    content_type: str | None
    byte_size: int | None
    checksum_sha256: str | None
    sensitive: SensitiveValue | None = field(default=None, repr=False)
    expires_at: datetime | None = None
    reason_code: str | None = None
    schema_version: ClassVar[str] = "audit-read/image-delivery/v1"

    def __post_init__(self) -> None:
        _non_empty(self.payload_id, "payload_id")
        if not isinstance(self.availability, Availability):
            raise TypeError("availability must be an Availability")
        if not isinstance(self.kind, ImageDeliveryKind):
            raise TypeError("kind must be an ImageDeliveryKind")
        if self.byte_size is not None:
            _non_negative(self.byte_size, "byte_size")
        if self.availability is Availability.AVAILABLE and self.sensitive is None:
            raise ValueError("available image delivery requires a sensitive value")
        if self.availability is Availability.UNAVAILABLE and self.sensitive is not None:
            raise ValueError("unavailable image delivery cannot carry a sensitive value")
        if self.kind is ImageDeliveryKind.UNAVAILABLE and self.reason_code is None:
            raise ValueError("unavailable image delivery requires a reason code")
        if self.expires_at is not None:
            utc_iso8601(self.expires_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "payload_id": self.payload_id,
            "availability": self.availability.value,
            "delivery_kind": self.kind.value,
            "content_type": self.content_type,
            "byte_size": self.byte_size,
            "checksum_sha256": self.checksum_sha256,
            "expires_at": utc_iso8601(self.expires_at) if self.expires_at else None,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class SourceContext:
    run_id: str
    state: SourceHashState
    availability: Availability
    expected_hash: str
    current_hash: str | None = None
    reason_code: str | None = None
    schema_version: ClassVar[str] = "audit-read/source-context/v1"

    def __post_init__(self) -> None:
        _non_empty(self.run_id, "run_id")
        _non_empty(self.expected_hash, "expected_hash")
        if not isinstance(self.state, SourceHashState):
            raise TypeError("state must be a SourceHashState")
        if not isinstance(self.availability, Availability):
            raise TypeError("availability must be an Availability")
        if self.state is SourceHashState.UNAVAILABLE and self.current_hash is not None:
            raise ValueError("unavailable source has no current hash")
        if self.state is not SourceHashState.UNAVAILABLE and self.current_hash is None:
            raise ValueError("available source requires current hash")
        if self.state is SourceHashState.MATCH and self.current_hash != self.expected_hash:
            raise ValueError("matching source hashes disagree")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "state": self.state.value,
            "availability": self.availability.value,
            "expected_hash": self.expected_hash,
            "current_hash": self.current_hash,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    status: RunStatus
    counts: Any
    hashes: Any
    capabilities: tuple[str, ...]
    target_ids: tuple[str, ...]
    bounds: ReadBounds
    schema_version: ClassVar[str] = "audit-read/run-manifest/v1"

    def __post_init__(self) -> None:
        _non_empty(self.run_id, "run_id")
        if not isinstance(self.status, RunStatus) or not isinstance(self.bounds, ReadBounds):
            raise TypeError("invalid run manifest")
        capabilities = tuple(self.capabilities)
        targets = tuple(self.target_ids)
        if any(not isinstance(item, str) or not item for item in (*capabilities, *targets)):
            raise ValueError("manifest identities must be non-empty strings")
        object.__setattr__(self, "counts", canonicalize_safe_json(self.counts))
        object.__setattr__(self, "hashes", canonicalize_safe_json(self.hashes))
        object.__setattr__(self, "capabilities", tuple(sorted(set(capabilities))))
        object.__setattr__(self, "target_ids", tuple(sorted(set(targets))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "status": self.status.value,
            "counts": safe_json_to_dict(self.counts),
            "hashes": safe_json_to_dict(self.hashes),
            "capabilities": list(self.capabilities),
            "target_ids": list(self.target_ids),
            "bounds": {
                "page_size": self.bounds.page_size,
                "max_text_bytes": self.bounds.max_text_bytes,
                "max_batch_size": self.bounds.max_batch_size,
                "max_filter_count": self.bounds.max_filter_count,
                "max_filter_values": self.bounds.max_filter_values,
                "max_complexity": self.bounds.max_complexity,
                "timeout_ms": self.bounds.timeout_ms,
            },
        }


@dataclass(frozen=True)
class SemanticPreflightCounts:
    """Closed identity-free estimate inputs for one exact persisted run."""

    targets: tuple[tuple[str, int], ...]
    diagnostics: tuple[tuple[str, int], ...]
    mandatory: tuple[tuple[str, int], ...]
    schema_version = "audit-semantic-preflight/v1"
    target_fields: ClassVar[tuple[str, ...]] = (
        "chunks",
        "boundaries",
        "source_comparisons",
        "tables",
        "images",
        "transcript_blocks",
        "linked_diagnostic_groups",
        "final_synthesis",
    )
    diagnostic_fields: ClassVar[tuple[str, ...]] = (
        "processing",
        "audit_rule",
        "critical",
        "warning",
    )
    mandatory_fields: ClassVar[tuple[str, ...]] = (
        "deduplicated_targets",
        "semantic_actions",
        "diagnostic_linked_targets",
        "edge_chunks",
        "size_extremes",
        "chunk_types",
        "payload_types",
        "broken_references",
        "transcript_speakers",
        "transcript_time_regions",
    )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> SemanticPreflightCounts:
        if not isinstance(value, Mapping):
            raise TypeError("invalid semantic preflight")
        allowed = {"schema_version", "targets", "diagnostics", "mandatory"}
        required = {"targets", "diagnostics", "mandatory"}
        if set(value) - allowed or set(value) & required != required:
            raise ValueError("invalid semantic preflight members")
        version = value.get("schema_version", cls.schema_version)
        if version != cls.schema_version:
            raise ValueError("invalid semantic preflight version")

        def section(name: str, fields: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
            raw = value[name]
            if not isinstance(raw, Mapping) or set(raw) != set(fields):
                raise ValueError("invalid semantic preflight members")
            if any(type(raw[key]) is not int or raw[key] < 0 for key in fields):
                raise ValueError("invalid semantic preflight count")
            return tuple((key, raw[key]) for key in fields)

        return cls(
            section("targets", cls.target_fields),
            section("diagnostics", cls.diagnostic_fields),
            section("mandatory", cls.mandatory_fields),
        )

    def __post_init__(self) -> None:
        expected = (
            self.target_fields,
            self.diagnostic_fields,
            self.mandatory_fields,
        )
        sections = (self.targets, self.diagnostics, self.mandatory)
        if any(
            tuple(key for key, _ in section) != fields
            or any(type(value) is not int or value < 0 for _, value in section)
            for section, fields in zip(sections, expected)
        ):
            raise ValueError("invalid semantic preflight ordering")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "targets": dict(self.targets),
            "diagnostics": dict(self.diagnostics),
            "mandatory": dict(self.mandatory),
        }


@dataclass(frozen=True)
class PayloadDetail:
    run_id: str
    payload_id: str
    kind: str
    registered: bool
    availability: Availability
    summary: Any = field(default_factory=dict)
    reason_code: str | None = None
    schema_version: ClassVar[str] = "audit-read/payload-detail/v1"

    def __post_init__(self) -> None:
        for name in ("run_id", "payload_id", "kind"):
            _non_empty(getattr(self, name), name)
        if type(self.registered) is not bool or not isinstance(self.availability, Availability):
            raise TypeError("invalid payload state")
        object.__setattr__(self, "summary", canonicalize_safe_json(self.summary))

    @property
    def identity(self) -> str:
        return self.payload_id

    @property
    def sort_key(self) -> tuple[str]:
        return (self.payload_id,)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "payload_id": self.payload_id,
            "kind": self.kind,
            "registered": self.registered,
            "availability": self.availability.value,
            "summary": safe_json_to_dict(self.summary),
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class PayloadOccurrenceDetail:
    run_id: str
    payload_id: str
    occurrence_ordinal: int
    kind: str
    chunk_id: str | None
    coordinates: Any = field(default_factory=dict)
    schema_version: ClassVar[str] = "audit-read/payload-occurrence/v1"

    def __post_init__(self) -> None:
        for name in ("run_id", "payload_id", "kind"):
            _non_empty(getattr(self, name), name)
        _non_negative(self.occurrence_ordinal, "occurrence_ordinal")
        if self.chunk_id is not None:
            _non_empty(self.chunk_id, "chunk_id")
        object.__setattr__(self, "coordinates", canonicalize_safe_json(self.coordinates))

    @property
    def identity(self) -> str:
        return f"{self.payload_id}:{self.occurrence_ordinal}"

    @property
    def sort_key(self) -> tuple[str, int]:
        return (self.payload_id, self.occurrence_ordinal)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "payload_id": self.payload_id,
            "occurrence_ordinal": self.occurrence_ordinal,
            "kind": self.kind,
            "chunk_id": self.chunk_id,
            "coordinates": safe_json_to_dict(self.coordinates),
        }


@dataclass(frozen=True)
class DiagnosticDetail:
    diagnostic_id: str
    run_id: str
    origin: str
    code: str
    level: str
    diagnostic_key: str | None
    chunk_id: str | None
    payload_id: str | None
    schema_version: ClassVar[str] = "audit-read/diagnostic-detail/v1"

    def __post_init__(self) -> None:
        for name in ("diagnostic_id", "run_id", "code", "level"):
            _non_empty(getattr(self, name), name)
        if self.origin not in {"splitter", "audit_rule"}:
            raise ValueError("invalid diagnostic origin")
        if self.origin == "audit_rule" and not self.diagnostic_key:
            raise ValueError("audit diagnostic requires diagnostic_key")

    @property
    def identity(self) -> str:
        return self.diagnostic_id

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.origin, self.diagnostic_key or self.diagnostic_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "diagnostic_id": self.diagnostic_id,
            "run_id": self.run_id,
            "origin": self.origin,
            "code": self.code,
            "level": self.level,
            "diagnostic_key": self.diagnostic_key,
            "chunk_id": self.chunk_id,
            "payload_id": self.payload_id,
        }


@dataclass(frozen=True)
class ReferenceResolution:
    run_id: str
    payload_id: str
    kind: str
    availability: Availability
    registered: bool
    reason_code: str | None
    schema_version: ClassVar[str] = "audit-read/reference-resolution/v1"

    def __post_init__(self) -> None:
        for name in ("run_id", "payload_id", "kind"):
            _non_empty(getattr(self, name), name)
        if not isinstance(self.availability, Availability) or type(self.registered) is not bool:
            raise TypeError("invalid reference resolution")

    @property
    def identity(self) -> str:
        return self.payload_id

    @property
    def sort_key(self) -> tuple[str]:
        return (self.payload_id,)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "payload_id": self.payload_id,
            "kind": self.kind,
            "availability": self.availability.value,
            "registered": self.registered,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class TableProfile:
    payload_id: str
    columns: tuple[str, ...]
    row_count: int
    summary: Any = field(default_factory=dict)
    schema_version: ClassVar[str] = "audit-read/table-profile/v1"

    def __post_init__(self) -> None:
        _non_empty(self.payload_id, "payload_id")
        columns = tuple(self.columns)
        if any(not isinstance(item, str) or not item for item in columns):
            raise ValueError("invalid table column")
        if len(columns) != len(set(columns)):
            raise ValueError("duplicate table column")
        _non_negative(self.row_count, "row_count")
        object.__setattr__(self, "columns", tuple(sorted(columns)))
        object.__setattr__(self, "summary", canonicalize_safe_json(self.summary))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "payload_id": self.payload_id,
            "columns": list(self.columns),
            "row_count": self.row_count,
            "summary": safe_json_to_dict(self.summary),
        }


@dataclass(frozen=True)
class TableRowPage:
    payload_id: str
    columns: tuple[str, ...]
    rows: tuple[Any, ...]
    next_cursor: str | None
    truncated: bool
    schema_version: ClassVar[str] = "audit-read/table-row-page/v1"

    def __post_init__(self) -> None:
        _non_empty(self.payload_id, "payload_id")
        columns = tuple(self.columns)
        if any(not isinstance(item, str) or not item for item in columns):
            raise ValueError("invalid table column")
        object.__setattr__(self, "columns", tuple(columns))
        object.__setattr__(self, "rows", tuple(canonicalize_safe_json(row) for row in self.rows))
        if self.truncated != (self.next_cursor is not None):
            raise ValueError("table page truncation and cursor disagree")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "payload_id": self.payload_id,
            "columns": list(self.columns),
            "rows": [safe_json_to_dict(row) for row in self.rows],
            "next_cursor": self.next_cursor,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class TableCapabilityResult:
    payload: PayloadDetail
    availability: Availability
    profile: TableProfile | None = None
    page: TableRowPage | None = None
    reason_code: str | None = None
    schema_version: ClassVar[str] = "audit-read/table-capability-result/v1"

    def __post_init__(self) -> None:
        if not isinstance(self.payload, PayloadDetail):
            raise TypeError("table result requires payload detail")
        if not isinstance(self.availability, Availability):
            raise TypeError("invalid table availability")
        if self.profile is not None and self.profile.payload_id != self.payload.payload_id:
            raise ValueError("table profile membership mismatch")
        if self.page is not None and self.page.payload_id != self.payload.payload_id:
            raise ValueError("table page membership mismatch")
        if self.availability is Availability.AVAILABLE:
            if self.payload.kind != "table" or (self.profile is None) == (self.page is None):
                raise ValueError("available table result requires one table result")
        if self.availability is Availability.UNAVAILABLE and (self.profile or self.page):
            raise ValueError("unavailable table result cannot carry rows")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "payload": self.payload.to_dict(),
            "availability": self.availability.value,
            "profile": self.profile.to_dict() if self.profile else None,
            "page": self.page.to_dict() if self.page else None,
            "reason_code": self.reason_code,
        }


@dataclass(frozen=True)
class ImageReadResult:
    payload: PayloadDetail
    delivery: ImageDelivery
    schema_version: ClassVar[str] = "audit-read/image-result/v1"

    def __post_init__(self) -> None:
        if not isinstance(self.payload, PayloadDetail) or self.payload.kind != "image":
            raise TypeError("image result requires image payload detail")
        if not isinstance(self.delivery, ImageDelivery):
            raise TypeError("image result requires image delivery")
        if self.delivery.payload_id != self.payload.payload_id:
            raise ValueError("image delivery membership mismatch")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "payload": self.payload.to_dict(),
            "delivery": self.delivery.to_dict(),
        }


@dataclass(frozen=True)
class RunComparison:
    left_run_id: str
    right_run_id: str
    logical_file_key: str
    unchanged: tuple[str, ...]
    changed: tuple[tuple[str, str], ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    schema_version: ClassVar[str] = "audit-read/run-comparison/v1"

    def __post_init__(self) -> None:
        for name in ("left_run_id", "right_run_id", "logical_file_key"):
            _non_empty(getattr(self, name), name)
        if self.left_run_id == self.right_run_id:
            raise ValueError("comparison requires two distinct runs")
        for name in ("unchanged", "added", "removed"):
            values = tuple(getattr(self, name))
            if any(not isinstance(item, str) or not item for item in values):
                raise ValueError(f"invalid comparison {name} identity")
            object.__setattr__(self, name, tuple(sorted(values)))
        changes = tuple(tuple(item) for item in self.changed)
        if any(len(item) != 2 or not all(isinstance(v, str) and v for v in item) for item in changes):
            raise ValueError("invalid changed comparison identity")
        object.__setattr__(self, "changed", tuple(sorted(changes)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "left_run_id": self.left_run_id,
            "right_run_id": self.right_run_id,
            "logical_file_key": self.logical_file_key,
            "unchanged": list(self.unchanged),
            "changed": [list(item) for item in self.changed],
            "added": list(self.added),
            "removed": list(self.removed),
        }


__all__ = [
    "ChunkDetail",
    "ChunkPreview",
    "DiagnosticDetail",
    "FileCard",
    "ImageDelivery",
    "ImageReadResult",
    "PayloadDetail",
    "PayloadOccurrenceDetail",
    "ReadPage",
    "ReadRunDetail",
    "ReferenceResolution",
    "RunComparison",
    "RunManifest",
    "SemanticPreflightCounts",
    "SensitiveValue",
    "SourceContext",
    "TableCapabilityResult",
    "TableProfile",
    "TableRowPage",
    "TextWindow",
]
