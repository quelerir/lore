"""Typed application facade for bounded Splitter inspection reads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Callable, Protocol, TypeVar

from audit.read_contracts import (
    AuditReadError,
    Availability,
    ChunkBatchRequest,
    ChunkDetail,
    ChunkDetailRequest,
    ChunkListRequest,
    ChunkNeighborsRequest,
    ChunkPreview,
    DiagnosticListRequest,
    FileCard,
    FileCardRequest,
    FileListRequest,
    ImageDelivery,
    ImageDeliveryKind,
    ImageReadResult,
    ImageRequest,
    ManifestRequest,
    OccurrenceListRequest,
    PayloadDetail,
    PayloadRequest,
    ReadPage,
    ReadRunDetail,
    ReferenceBatchRequest,
    ReferenceResolution,
    RunCompareRequest,
    RunComparison,
    RunDetailRequest,
    RunListRequest,
    RunManifest,
    SemanticPreflightCounts,
    SourceContext,
    SourceContextRequest,
    SourceHashState,
    TableCapabilityResult,
    TablePageRequest,
    TableProfile,
    TableProfileRequest,
    TableRowPage,
    TableSampleRequest,
)
from audit.read_repositories import (
    AuditCoreReadRepository,
    PayloadReadResult,
    RegisteredPayloadToken,
    RegisteredSourceToken,
    SourceReadResult,
)

T = TypeVar("T")


class RegisteredTableReader(Protocol):
    def get_profile(
        self, token: RegisteredPayloadToken, request: TableProfileRequest
    ) -> TableProfile: ...

    def get_page(
        self, token: RegisteredPayloadToken, request: TablePageRequest
    ) -> TableRowPage: ...

    def get_sample(
        self, token: RegisteredPayloadToken, request: TableSampleRequest
    ) -> TableRowPage: ...


class RegisteredImageReader(Protocol):
    def get_image(
        self, token: RegisteredPayloadToken, request: ImageRequest
    ) -> ImageDelivery: ...


class CurrentSourceReader(Protocol):
    def get_source_context(
        self, token: RegisteredSourceToken, request: SourceContextRequest
    ) -> SourceContext: ...


class AuditReadService:
    """The sole public application boundary for persisted audit inspection."""

    def __init__(
        self,
        repository: AuditCoreReadRepository,
        *,
        manifest_target_cap: int = 100,
        table_reader: RegisteredTableReader | None = None,
        image_reader: RegisteredImageReader | None = None,
        source_reader: CurrentSourceReader | None = None,
    ) -> None:
        if type(manifest_target_cap) is not int or not 0 < manifest_target_cap <= 10_000:
            raise ValueError("invalid manifest target cap")
        self._repository = repository
        self._manifest_target_cap = manifest_target_cap
        self._table_reader = table_reader
        self._image_reader = image_reader
        self._source_reader = source_reader

    @staticmethod
    def _invoke(request: Any, expected: type[Any], operation: Callable[[Any], T]) -> T:
        if not isinstance(request, expected):
            raise AuditReadError("invalid_request")
        try:
            return operation(request)
        except AuditReadError:
            raise
        except Exception:
            raise AuditReadError("read_failed") from None

    def list_files(self, request: FileListRequest) -> ReadPage:
        return self._invoke(request, FileListRequest, self._repository.list_files)

    def get_file(self, request: FileCardRequest) -> FileCard:
        result = self._invoke(request, FileCardRequest, self._repository.get_file)
        if not isinstance(result, FileCard) or result.logical_file_key != request.logical_file_key:
            raise AuditReadError("membership_mismatch", resource="file")
        return result

    def list_runs(self, request: RunListRequest) -> ReadPage:
        return self._invoke(request, RunListRequest, self._repository.list_runs)

    def get_run(self, request: RunDetailRequest) -> ReadRunDetail:
        result = self._invoke(request, RunDetailRequest, self._repository.get_run)
        if not isinstance(result, ReadRunDetail) or result.run_id != request.run_id:
            raise AuditReadError("membership_mismatch", resource="run")
        return result

    def get_manifest(self, request: ManifestRequest) -> RunManifest:
        if not isinstance(request, ManifestRequest):
            raise AuditReadError("invalid_request")
        run = self.get_run(RunDetailRequest(request.run_id))
        target_limit = min(request.bounds.page_size, self._manifest_target_cap)
        chunk_request = ChunkListRequest(
            request.run_id,
            bounds=replace(request.bounds, page_size=target_limit),
        )
        chunks = self.list_chunks(chunk_request)
        preflight = self._invoke(
            request.run_id,
            str,
            self._repository.get_semantic_preflight_counts,
        )
        if not isinstance(preflight, SemanticPreflightCounts):
            raise AuditReadError("read_failed")
        target_ids = tuple(item.chunk_id for item in chunks.items)
        capabilities = ["run_detail", "comparison"]
        if run.chunk_count:
            capabilities.append("chunks")
        if run.payload_count:
            capabilities.append("payloads")
        if run.warning_count or run.error_count:
            capabilities.append("diagnostics")
        return RunManifest(
            run_id=run.run_id,
            status=run.status,
            counts={
                "chunks": run.chunk_count,
                "payloads": run.payload_count,
                "warnings": run.warning_count,
                "errors": run.error_count,
                "semantic_preflight": preflight.to_dict(),
            },
            hashes={
                "source_content": run.source_content_hash,
                "config": run.config_hash,
            },
            capabilities=tuple(capabilities),
            target_ids=target_ids,
            bounds=request.bounds,
        )

    def list_chunks(self, request: ChunkListRequest) -> ReadPage:
        return self._invoke(request, ChunkListRequest, self._repository.list_chunks)

    def get_chunk(self, request: ChunkDetailRequest) -> ChunkDetail:
        result = self._invoke(request, ChunkDetailRequest, self._repository.get_chunk)
        if (
            not isinstance(result, ChunkDetail)
            or result.preview.run_id != request.run_id
            or result.preview.chunk_id != request.chunk_id
        ):
            raise AuditReadError("membership_mismatch", resource="chunk")
        return result

    def get_chunk_neighbors(self, request: ChunkNeighborsRequest) -> tuple[ChunkPreview, ...]:
        result = self._invoke(
            request, ChunkNeighborsRequest, self._repository.get_chunk_neighbors
        )
        if any(not isinstance(item, ChunkPreview) or item.run_id != request.run_id for item in result):
            raise AuditReadError("membership_mismatch", resource="chunk")
        return result

    def get_chunks(self, request: ChunkBatchRequest) -> tuple[ChunkPreview, ...]:
        result = self._invoke(request, ChunkBatchRequest, self._repository.get_chunks)
        allowed = set(request.chunk_ids)
        if any(
            not isinstance(item, ChunkPreview)
            or item.run_id != request.run_id
            or item.chunk_id not in allowed
            for item in result
        ):
            raise AuditReadError("membership_mismatch", resource="chunk")
        return result

    def get_payload(self, request: PayloadRequest) -> PayloadDetail:
        result = self._get_payload_result(request)
        return result.detail

    def _get_payload_result(self, request: PayloadRequest) -> PayloadReadResult:
        result = self._invoke(request, PayloadRequest, self._repository.get_payload)
        if (
            not isinstance(result, PayloadReadResult)
            or result.detail.run_id != request.run_id
            or result.detail.payload_id != request.payload_id
        ):
            raise AuditReadError("membership_mismatch", resource="payload")
        return result

    @staticmethod
    def _capability_reason(error: Exception) -> str:
        return "dependency_timeout" if isinstance(error, TimeoutError) else "capability_unavailable"

    def _table_core(self, run_id: str, payload_id: str) -> PayloadReadResult:
        return self._get_payload_result(PayloadRequest(run_id, payload_id))

    def get_table_profile(self, request: TableProfileRequest) -> TableCapabilityResult:
        if not isinstance(request, TableProfileRequest):
            raise AuditReadError("invalid_request")
        core = self._table_core(request.run_id, request.payload_id)
        if core.detail.kind != "table" or core.token is None or core.token.storage_kind != "postgres":
            return TableCapabilityResult(
                core.detail, Availability.UNAVAILABLE, reason_code="kind_mismatch"
            )
        if self._table_reader is None:
            return TableCapabilityResult(
                core.detail, Availability.UNAVAILABLE, reason_code="capability_unavailable"
            )
        try:
            profile = self._table_reader.get_profile(core.token, request)
            if profile.payload_id != request.payload_id:
                raise ValueError
            return TableCapabilityResult(core.detail, Availability.AVAILABLE, profile=profile)
        except Exception as error:
            return TableCapabilityResult(
                core.detail, Availability.UNAVAILABLE, reason_code=self._capability_reason(error)
            )

    def get_table_page(self, request: TablePageRequest) -> TableCapabilityResult:
        if not isinstance(request, TablePageRequest):
            raise AuditReadError("invalid_request")
        return self._table_rows(request, "page")

    def get_table_sample(self, request: TableSampleRequest) -> TableCapabilityResult:
        if not isinstance(request, TableSampleRequest):
            raise AuditReadError("invalid_request")
        return self._table_rows(request, "sample")

    def _table_rows(
        self, request: TablePageRequest | TableSampleRequest, operation: str
    ) -> TableCapabilityResult:
        core = self._table_core(request.run_id, request.payload_id)
        if core.detail.kind != "table" or core.token is None or core.token.storage_kind != "postgres":
            return TableCapabilityResult(
                core.detail, Availability.UNAVAILABLE, reason_code="kind_mismatch"
            )
        if not self._registered_table_request(core.token, request):
            return TableCapabilityResult(
                core.detail, Availability.UNAVAILABLE, reason_code="capability_unavailable"
            )
        if self._table_reader is None:
            return TableCapabilityResult(
                core.detail, Availability.UNAVAILABLE, reason_code="capability_unavailable"
            )
        try:
            if operation == "page":
                page = self._table_reader.get_page(core.token, request)  # type: ignore[arg-type]
            else:
                page = self._table_reader.get_sample(core.token, request)  # type: ignore[arg-type]
            if page.payload_id != request.payload_id:
                raise ValueError
            return TableCapabilityResult(core.detail, Availability.AVAILABLE, page=page)
        except AuditReadError:
            raise
        except Exception as error:
            return TableCapabilityResult(
                core.detail, Availability.UNAVAILABLE, reason_code=self._capability_reason(error)
            )

    @staticmethod
    def _registered_table_request(
        token: RegisteredPayloadToken,
        request: TablePageRequest | TableSampleRequest,
    ) -> bool:
        registration = token.registration
        if registration is None:
            return True
        if not isinstance(registration, Mapping):
            return False
        columns = registration.get("columns")
        if not isinstance(columns, (list, tuple)) or any(
            not isinstance(column, str) or not column for column in columns
        ):
            return False
        allowed = set(columns)
        if any(column not in allowed for column in request.columns):
            return False
        if isinstance(request, TablePageRequest):
            if request.sort_column is not None and request.sort_column not in allowed:
                return False
            if any(item.column not in allowed for item in request.filters):
                return False
        return True

    def get_image(self, request: ImageRequest) -> ImageReadResult:
        if not isinstance(request, ImageRequest):
            raise AuditReadError("invalid_request")
        core = self._get_payload_result(PayloadRequest(request.run_id, request.payload_id))
        if core.detail.kind != "image":
            raise AuditReadError("membership_mismatch", resource="payload")
        if core.token is None or core.token.storage_kind != "s3" or self._image_reader is None:
            return ImageReadResult(
                core.detail,
                self._unavailable_image(request.payload_id, "capability_unavailable"),
            )
        try:
            delivery = self._image_reader.get_image(core.token, request)
            if delivery.payload_id != request.payload_id:
                raise ValueError
            return ImageReadResult(core.detail, delivery)
        except Exception as error:
            return ImageReadResult(
                core.detail,
                self._unavailable_image(request.payload_id, self._capability_reason(error)),
            )

    @staticmethod
    def _unavailable_image(payload_id: str, reason: str) -> ImageDelivery:
        return ImageDelivery(
            payload_id,
            Availability.UNAVAILABLE,
            ImageDeliveryKind.UNAVAILABLE,
            None,
            None,
            None,
            reason_code=reason,
        )

    def get_source_context(self, request: SourceContextRequest) -> SourceContext:
        if not isinstance(request, SourceContextRequest):
            raise AuditReadError("invalid_request")
        core = self._invoke(request, SourceContextRequest, self._repository.get_source)
        if (
            not isinstance(core, SourceReadResult)
            or core.run.run_id != request.run_id
            or (core.token is not None and core.token.run_id != request.run_id)
        ):
            raise AuditReadError("membership_mismatch", resource="source")
        expected = core.run.source_content_hash
        if core.token is None:
            return self._unavailable_source(request.run_id, expected, "source_unregistered")
        if self._source_reader is None:
            return self._unavailable_source(request.run_id, expected, "capability_unavailable")
        try:
            result = self._source_reader.get_source_context(core.token, request)
            if result.run_id != request.run_id or result.expected_hash != expected:
                raise ValueError
            return result
        except Exception as error:
            return self._unavailable_source(
                request.run_id, expected, self._capability_reason(error)
            )

    @staticmethod
    def _unavailable_source(run_id: str, expected_hash: str, reason: str) -> SourceContext:
        return SourceContext(
            run_id,
            SourceHashState.UNAVAILABLE,
            Availability.UNAVAILABLE,
            expected_hash,
            reason_code=reason,
        )

    def list_occurrences(self, request: OccurrenceListRequest) -> ReadPage:
        return self._invoke(request, OccurrenceListRequest, self._repository.list_occurrences)

    def list_diagnostics(self, request: DiagnosticListRequest) -> ReadPage:
        return self._invoke(request, DiagnosticListRequest, self._repository.list_diagnostics)

    def resolve_references(
        self, request: ReferenceBatchRequest
    ) -> tuple[ReferenceResolution, ...]:
        return self._invoke(
            request, ReferenceBatchRequest, self._repository.resolve_references
        )

    def compare_runs(self, request: RunCompareRequest) -> RunComparison:
        result = self._invoke(request, RunCompareRequest, self._repository.compare_runs)
        if (
            not isinstance(result, RunComparison)
            or result.left_run_id != request.left_run_id
            or result.right_run_id != request.right_run_id
        ):
            raise AuditReadError("membership_mismatch", resource="comparison")
        return result


__all__ = [
    "AuditReadService",
    "CurrentSourceReader",
    "RegisteredImageReader",
    "RegisteredTableReader",
]
