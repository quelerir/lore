"""Closed Pydantic transport contracts for audit read operations."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from audit.http_api.limits import AuditHttpLimits
from audit.read_contracts import (
    AuditReadError,
    ChunkBatchRequest,
    ChunkDetailRequest,
    ChunkNeighborsRequest,
    DiagnosticListRequest,
    FileCardRequest,
    FileListRequest,
    ImageRequest,
    ReferenceBatchRequest,
    RunCompareRequest,
    RunListRequest,
    SourceContextRequest,
    TableFilter,
    TablePageRequest,
    TableSampleRequest,
)
from audit._vendor.run_status import RunStatus


def _bounded_utf8(value: str, *, maximum: int, empty: bool = False) -> str:
    if (not empty and not value) or len(value.encode("utf-8")) > maximum:
        raise ValueError("invalid bounded text")
    return value


def _identity(value: str) -> str:
    return _bounded_utf8(value, maximum=512)


def _cursor(value: str) -> str:
    return _bounded_utf8(value, maximum=4096)


def _search(value: str) -> str:
    return _bounded_utf8(value, maximum=256, empty=True)


def _query_int(value: object) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    raise ValueError("invalid query integer")


def _query_bool(value: object) -> bool:
    if type(value) is bool:
        return value
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError("invalid query boolean")


Identity = Annotated[StrictStr, AfterValidator(_identity)]
Cursor = Annotated[StrictStr, AfterValidator(_cursor)]
Search = Annotated[StrictStr, AfterValidator(_search)]
PositiveInt = Annotated[StrictInt, Field(gt=0, le=100_000_000)]
PageSize = Annotated[StrictInt, Field(gt=0, le=10_000)]
QueryPositiveInt = Annotated[int, BeforeValidator(_query_int), Field(gt=0, le=100_000_000)]
QueryPageSize = Annotated[int, BeforeValidator(_query_int), Field(gt=0, le=10_000)]
QueryBool = Annotated[bool, BeforeValidator(_query_bool)]
AuditErrorCode = Literal[
    "invalid_request",
    "invalid_cursor",
    "bounds_exceeded",
    "not_found",
    "membership_mismatch",
    "registration_invalid",
    "capability_unavailable",
    "dependency_timeout",
    "read_failed",
]
AuditErrorResource = Literal["file", "run", "chunk", "payload", "source", "comparison"]


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuditHttpErrorEnvelope(_ClosedModel):
    schema_version: Literal["audit-http/error/v1"]
    code: AuditErrorCode
    message: StrictStr
    resource: AuditErrorResource | None


class _CursorModel(_ClosedModel):
    cursor: Cursor | None = None


class PageQuery(_CursorModel):
    page_size: QueryPageSize | None = None


class FileListQuery(PageQuery):
    search: Search = ""
    statuses: Annotated[list[RunStatus], Field(max_length=16)] = Field(default_factory=list)

    def to_request(self, limits: AuditHttpLimits) -> FileListRequest:
        return FileListRequest(
            search=self.search,
            statuses=tuple(self.statuses),
            cursor=self.cursor,
            bounds=limits.read_bounds(page_size=self.page_size),
        )


class FileDetailQuery(_ClosedModel):
    logical_file_key: Identity

    def to_request(self) -> FileCardRequest:
        return FileCardRequest(self.logical_file_key)


class RunListQuery(PageQuery):
    logical_file_key: Identity

    def to_request(self, limits: AuditHttpLimits) -> RunListRequest:
        return RunListRequest(
            self.logical_file_key,
            self.cursor,
            limits.read_bounds(page_size=self.page_size),
        )


class ManifestQuery(_ClosedModel):
    target_limit: QueryPageSize | None = None


class ChunkDetailQuery(_ClosedModel):
    max_text_bytes: QueryPositiveInt | None = None
    display_continuation: Cursor | None = None
    full_continuation: Cursor | None = None
    vector_continuation: Cursor | None = None

    def to_request(
        self,
        run_id: Identity,
        chunk_id: Identity,
        limits: AuditHttpLimits,
    ) -> ChunkDetailRequest:
        return ChunkDetailRequest(
            run_id,
            chunk_id,
            limits.read_bounds(max_text_bytes=self.max_text_bytes),
            self.display_continuation,
            self.full_continuation,
            self.vector_continuation,
        )


class ChunkNeighborsQuery(_ClosedModel):
    before: QueryPageSize
    after: QueryPageSize

    def to_request(
        self,
        run_id: Identity,
        chunk_id: Identity,
        limits: AuditHttpLimits,
    ) -> ChunkNeighborsRequest:
        try:
            return ChunkNeighborsRequest(
                run_id,
                chunk_id,
                self.before,
                self.after,
                limits.read_bounds(),
            )
        except ValueError:
            raise AuditReadError("bounds_exceeded") from None


class ChunkBatchBody(_ClosedModel):
    chunk_ids: Annotated[list[Identity], Field(min_length=1, max_length=100)]

    def to_request(self, run_id: Identity, limits: AuditHttpLimits) -> ChunkBatchRequest:
        if len(self.chunk_ids) > limits.max_batch_size:
            raise AuditReadError("bounds_exceeded")
        return ChunkBatchRequest(run_id, tuple(self.chunk_ids), limits.read_bounds())


class OccurrenceListQuery(PageQuery):
    pass


class DiagnosticListQuery(PageQuery):
    origins: Annotated[
        list[Literal["splitter", "audit_rule"]], Field(min_length=1, max_length=2)
    ] = Field(default_factory=lambda: ["splitter", "audit_rule"])

    def to_request(self, run_id: Identity, limits: AuditHttpLimits) -> DiagnosticListRequest:
        return DiagnosticListRequest(
            run_id,
            tuple(self.origins),
            self.cursor,
            limits.read_bounds(page_size=self.page_size),
        )


class ReferenceInput(_ClosedModel):
    payload_id: Identity
    kind: Literal["table", "image"]


class ReferenceBatchBody(_ClosedModel):
    references: Annotated[list[ReferenceInput], Field(min_length=1, max_length=100)]

    def to_request(self, run_id: Identity, limits: AuditHttpLimits) -> ReferenceBatchRequest:
        if len(self.references) > limits.max_batch_size:
            raise AuditReadError("bounds_exceeded")
        references = tuple((item.payload_id, item.kind) for item in self.references)
        return ReferenceBatchRequest(run_id, references, limits.read_bounds())


Scalar = StrictStr | StrictInt | StrictFloat | StrictBool | None


class TableFilterInput(_ClosedModel):
    column: Identity
    operator: Literal["eq", "ne", "lt", "lte", "gt", "gte", "is_null", "prefix", "contains"]
    values: Annotated[list[Scalar], Field(max_length=1)] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_values(self) -> TableFilterInput:
        if self.operator == "is_null":
            if self.values:
                raise ValueError("is_null accepts no values")
        elif len(self.values) != 1:
            raise ValueError("filter requires one value")
        for value in self.values:
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("filter value must be finite")
            if isinstance(value, str) and len(value.encode("utf-8")) > 512:
                raise ValueError("filter value is too large")
        return self

    def to_contract(self) -> TableFilter:
        return TableFilter(self.column, self.operator, tuple(self.values))


class TablePageBody(_CursorModel):
    columns: Annotated[list[Identity], Field(min_length=1, max_length=100)]
    filters: Annotated[list[TableFilterInput], Field(max_length=8)] = Field(default_factory=list)
    sort_column: Identity | None = None
    descending: StrictBool = False
    page_size: PageSize | None = None

    def to_request(
        self,
        run_id: Identity,
        payload_id: Identity,
        limits: AuditHttpLimits,
    ) -> TablePageRequest:
        if (
            len(self.columns) > limits.max_batch_size
            or len(self.filters) > limits.max_filter_count
            or any(len(item.values) > limits.max_filter_values for item in self.filters)
            or len(self.columns) + 2 * len(self.filters) > limits.max_complexity
        ):
            raise AuditReadError("bounds_exceeded")
        return TablePageRequest(
            run_id,
            payload_id,
            tuple(self.columns),
            tuple(item.to_contract() for item in self.filters),
            self.sort_column,
            self.descending,
            self.cursor,
            limits.read_bounds(page_size=self.page_size),
        )


class TableSampleBody(_ClosedModel):
    columns: Annotated[list[Identity], Field(min_length=1, max_length=100)]
    limit: PageSize

    def to_request(
        self,
        run_id: Identity,
        payload_id: Identity,
        limits: AuditHttpLimits,
    ) -> TableSampleRequest:
        if len(self.columns) > limits.max_batch_size:
            raise AuditReadError("bounds_exceeded")
        bounds = limits.read_bounds(page_size=self.limit)
        return TableSampleRequest(run_id, payload_id, tuple(self.columns), self.limit, bounds)


class ImageQuery(_ClosedModel):
    prefer_inline: QueryBool = True
    max_inline_bytes: QueryPositiveInt | None = None

    def to_request(
        self,
        run_id: Identity,
        payload_id: Identity,
        limits: AuditHttpLimits,
    ) -> ImageRequest:
        return ImageRequest(
            run_id,
            payload_id,
            limits.read_bounds(max_text_bytes=self.max_inline_bytes),
            self.prefer_inline,
        )


class SourceContextQuery(_ClosedModel):
    max_source_bytes: QueryPositiveInt | None = None

    def to_request(self, run_id: Identity, limits: AuditHttpLimits) -> SourceContextRequest:
        return SourceContextRequest(
            run_id,
            limits.read_bounds(max_text_bytes=self.max_source_bytes),
        )


class ComparisonQuery(_ClosedModel):
    left_run_id: Identity
    right_run_id: Identity

    @model_validator(mode="after")
    def distinct_runs(self) -> ComparisonQuery:
        if self.left_run_id == self.right_run_id:
            raise ValueError("comparison requires distinct runs")
        return self

    def to_request(self) -> RunCompareRequest:
        return RunCompareRequest(self.left_run_id, self.right_run_id)
