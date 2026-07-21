"""Request dataclasses for bounded Splitter inspection reads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from lore_audit.run_status import RunStatus
from lore_audit.validation import canonicalize_safe_json
from lore_audit.read.enums import _BYTE_CAP, _COUNT_CAP


@dataclass(frozen=True)
class ReadBounds:
    page_size: int = 50
    max_text_bytes: int = 1_000_000
    max_batch_size: int = 100
    max_filter_count: int = 8
    max_filter_values: int = 32
    max_complexity: int = 100
    timeout_ms: int = 5_000

    def __post_init__(self) -> None:
        counts = (
            self.page_size,
            self.max_batch_size,
            self.max_filter_count,
            self.max_filter_values,
            self.max_complexity,
            self.timeout_ms,
        )
        valid = (
            all(type(value) is int and 0 < value <= _COUNT_CAP for value in counts)
            and type(self.max_text_bytes) is int
            and 0 < self.max_text_bytes <= _BYTE_CAP
        )
        if not valid:
            raise ValueError("invalid audit read bounds")


def _request_identity(value: str, name: str) -> None:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512:
        raise ValueError(f"invalid {name}")


def _request_cursor(value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not value):
        raise ValueError("invalid cursor")


@dataclass(frozen=True)
class FileListRequest:
    search: str = ""
    statuses: tuple[RunStatus, ...] = ()
    cursor: str | None = None
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/file-list-request/v1"

    def __post_init__(self) -> None:
        if not isinstance(self.search, str) or len(self.search.encode("utf-8")) > 256:
            raise ValueError("invalid file search")
        normalized = " ".join(self.search.split()).casefold()
        statuses = tuple(self.statuses)
        if any(not isinstance(item, RunStatus) for item in statuses):
            raise ValueError("invalid file status filter")
        if len(statuses) != len(set(statuses)) or not isinstance(self.bounds, ReadBounds):
            raise ValueError("invalid file list request")
        _request_cursor(self.cursor)
        object.__setattr__(self, "search", normalized)
        object.__setattr__(self, "statuses", tuple(sorted(statuses, key=lambda item: item.value)))


@dataclass(frozen=True)
class FileCardRequest:
    logical_file_key: str
    schema_version: ClassVar[str] = "audit-read/file-card-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.logical_file_key, "logical_file_key")


@dataclass(frozen=True)
class RunListRequest:
    logical_file_key: str
    cursor: str | None = None
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/run-list-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.logical_file_key, "logical_file_key")
        _request_cursor(self.cursor)
        if not isinstance(self.bounds, ReadBounds):
            raise ValueError("invalid run list request")


@dataclass(frozen=True)
class RunDetailRequest:
    run_id: str
    schema_version: ClassVar[str] = "audit-read/run-detail-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")


@dataclass(frozen=True)
class ManifestRequest:
    run_id: str
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/manifest-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        if not isinstance(self.bounds, ReadBounds):
            raise ValueError("invalid manifest request")


@dataclass(frozen=True)
class ChunkListRequest:
    run_id: str
    cursor: str | None = None
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/chunk-list-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        _request_cursor(self.cursor)
        if not isinstance(self.bounds, ReadBounds):
            raise ValueError("invalid chunk list request")


@dataclass(frozen=True)
class ChunkDetailRequest:
    run_id: str
    chunk_id: str
    bounds: ReadBounds = field(default_factory=ReadBounds)
    display_continuation: str | None = None
    full_continuation: str | None = None
    vector_continuation: str | None = None
    schema_version: ClassVar[str] = "audit-read/chunk-detail-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        _request_identity(self.chunk_id, "chunk_id")
        if not isinstance(self.bounds, ReadBounds):
            raise ValueError("invalid chunk detail request")
        for value in (
            self.display_continuation,
            self.full_continuation,
            self.vector_continuation,
        ):
            _request_cursor(value)


@dataclass(frozen=True)
class ChunkNeighborsRequest:
    run_id: str
    chunk_id: str
    before: int
    after: int
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/chunk-neighbors-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        _request_identity(self.chunk_id, "chunk_id")
        if (
            type(self.before) is not int
            or type(self.after) is not int
            or self.before <= 0
            or self.after <= 0
            or not isinstance(self.bounds, ReadBounds)
            or self.before + self.after + 1 > self.bounds.max_batch_size
        ):
            raise ValueError("invalid chunk neighborhood bounds")


@dataclass(frozen=True)
class ChunkBatchRequest:
    run_id: str
    chunk_ids: tuple[str, ...]
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/chunk-batch-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        chunk_ids = tuple(self.chunk_ids)
        for item in chunk_ids:
            _request_identity(item, "chunk_id")
        if (
            not chunk_ids
            or len(chunk_ids) != len(set(chunk_ids))
            or not isinstance(self.bounds, ReadBounds)
            or len(chunk_ids) > self.bounds.max_batch_size
        ):
            raise ValueError("invalid chunk batch request")
        object.__setattr__(self, "chunk_ids", tuple(sorted(chunk_ids)))


@dataclass(frozen=True)
class PayloadRequest:
    run_id: str
    payload_id: str
    schema_version: ClassVar[str] = "audit-read/payload-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        _request_identity(self.payload_id, "payload_id")


@dataclass(frozen=True)
class OccurrenceListRequest:
    run_id: str
    payload_id: str
    cursor: str | None = None
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/occurrence-list-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        _request_identity(self.payload_id, "payload_id")
        _request_cursor(self.cursor)
        if not isinstance(self.bounds, ReadBounds):
            raise ValueError("invalid occurrence list request")


@dataclass(frozen=True)
class DiagnosticListRequest:
    run_id: str
    origins: tuple[str, ...] = ("splitter", "audit_rule")
    cursor: str | None = None
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/diagnostic-list-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        origins = tuple(self.origins)
        if (
            not origins
            or len(origins) != len(set(origins))
            or set(origins) - {"splitter", "audit_rule"}
            or not isinstance(self.bounds, ReadBounds)
            or len(origins) > self.bounds.max_filter_values
        ):
            raise ValueError("invalid diagnostic list request")
        _request_cursor(self.cursor)
        object.__setattr__(self, "origins", tuple(sorted(origins)))


@dataclass(frozen=True)
class ReferenceBatchRequest:
    run_id: str
    references: tuple[tuple[str, str], ...]
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/reference-batch-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        references = tuple(tuple(item) for item in self.references)
        if (
            not references
            or any(len(item) != 2 for item in references)
            or len(references) != len(set(references))
            or not isinstance(self.bounds, ReadBounds)
            or len(references) > self.bounds.max_batch_size
        ):
            raise ValueError("invalid reference batch request")
        for payload_id, kind in references:
            _request_identity(payload_id, "payload_id")
            if kind not in {"table", "image"}:
                raise ValueError("invalid reference kind")
        object.__setattr__(self, "references", tuple(sorted(references)))


@dataclass(frozen=True)
class RunCompareRequest:
    left_run_id: str
    right_run_id: str
    schema_version: ClassVar[str] = "audit-read/run-compare-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.left_run_id, "left_run_id")
        _request_identity(self.right_run_id, "right_run_id")
        if self.left_run_id == self.right_run_id:
            raise ValueError("comparison requires two distinct runs")


@dataclass(frozen=True)
class TableFilter:
    column: str
    operator: str
    values: tuple[Any, ...] = ()
    schema_version: ClassVar[str] = "audit-read/table-filter/v1"

    def __post_init__(self) -> None:
        _request_identity(self.column, "column")
        if self.operator not in {
            "eq",
            "ne",
            "lt",
            "lte",
            "gt",
            "gte",
            "is_null",
            "prefix",
            "contains",
        }:
            raise ValueError("invalid table filter operator")
        values = tuple(canonicalize_safe_json(value) for value in self.values)
        if self.operator == "is_null":
            if values:
                raise ValueError("is_null filter accepts no values")
        elif len(values) != 1:
            raise ValueError("table filter requires one value")
        object.__setattr__(self, "values", values)


def _table_request(
    run_id: str,
    payload_id: str,
    columns: tuple[str, ...],
    bounds: ReadBounds,
) -> tuple[str, ...]:
    _request_identity(run_id, "run_id")
    _request_identity(payload_id, "payload_id")
    values = tuple(columns)
    if (
        not values
        or len(values) != len(set(values))
        or any(not isinstance(item, str) or not item for item in values)
        or not isinstance(bounds, ReadBounds)
        or len(values) > bounds.max_batch_size
    ):
        raise ValueError("invalid table request")
    return values


@dataclass(frozen=True)
class TableProfileRequest:
    run_id: str
    payload_id: str
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/table-profile-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        _request_identity(self.payload_id, "payload_id")
        if not isinstance(self.bounds, ReadBounds):
            raise ValueError("invalid table profile request")


@dataclass(frozen=True)
class TablePageRequest:
    run_id: str
    payload_id: str
    columns: tuple[str, ...]
    filters: tuple[TableFilter, ...] = ()
    sort_column: str | None = None
    descending: bool = False
    cursor: str | None = None
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/table-page-request/v1"

    def __post_init__(self) -> None:
        columns = _table_request(self.run_id, self.payload_id, self.columns, self.bounds)
        filters = tuple(self.filters)
        if (
            any(not isinstance(item, TableFilter) for item in filters)
            or len(filters) > self.bounds.max_filter_count
            or len(columns) + 2 * len(filters) > self.bounds.max_complexity
            or type(self.descending) is not bool
        ):
            raise ValueError("invalid table page request")
        if self.sort_column is not None and self.sort_column not in columns:
            raise ValueError("sort column is not selected")
        _request_cursor(self.cursor)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "filters", filters)


@dataclass(frozen=True)
class TableSampleRequest:
    run_id: str
    payload_id: str
    columns: tuple[str, ...]
    limit: int
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/table-sample-request/v1"

    def __post_init__(self) -> None:
        columns = _table_request(self.run_id, self.payload_id, self.columns, self.bounds)
        if type(self.limit) is not int or not 0 < self.limit <= self.bounds.page_size:
            raise ValueError("invalid table sample limit")
        object.__setattr__(self, "columns", columns)


@dataclass(frozen=True)
class ImageRequest:
    run_id: str
    payload_id: str
    bounds: ReadBounds = field(default_factory=ReadBounds)
    prefer_inline: bool = True
    schema_version: ClassVar[str] = "audit-read/image-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        _request_identity(self.payload_id, "payload_id")
        if not isinstance(self.bounds, ReadBounds) or type(self.prefer_inline) is not bool:
            raise ValueError("invalid image request")


@dataclass(frozen=True)
class SourceContextRequest:
    run_id: str
    bounds: ReadBounds = field(default_factory=ReadBounds)
    schema_version: ClassVar[str] = "audit-read/source-context-request/v1"

    def __post_init__(self) -> None:
        _request_identity(self.run_id, "run_id")
        if not isinstance(self.bounds, ReadBounds):
            raise ValueError("invalid source context request")


__all__ = [
    "ChunkBatchRequest",
    "ChunkDetailRequest",
    "ChunkListRequest",
    "ChunkNeighborsRequest",
    "DiagnosticListRequest",
    "FileCardRequest",
    "FileListRequest",
    "ImageRequest",
    "ManifestRequest",
    "OccurrenceListRequest",
    "PayloadRequest",
    "ReadBounds",
    "ReferenceBatchRequest",
    "RunCompareRequest",
    "RunDetailRequest",
    "RunListRequest",
    "SourceContextRequest",
    "TableFilter",
    "TablePageRequest",
    "TableProfileRequest",
    "TableSampleRequest",
]
