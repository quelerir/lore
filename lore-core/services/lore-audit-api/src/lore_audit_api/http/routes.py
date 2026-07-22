"""Read-only FastAPI routes over the public audit facade."""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse, RedirectResponse

from lore_audit_api.http.contracts import (
    ChunkBatchBody,
    ChunkDetailQuery,
    ChunkNeighborsQuery,
    ComparisonQuery,
    DiagnosticListQuery,
    FileDetailQuery,
    FileListQuery,
    Identity,
    ImageQuery,
    ManifestQuery,
    OccurrenceListQuery,
    PageQuery,
    PayloadBatchBody,
    ReferenceBatchBody,
    RunListQuery,
    SourceContextQuery,
    TablePageBody,
    TableSampleBody,
)
from lore_audit_api.http.limits import AuditHttpLimits
from lore_audit.image_safety import validate_safe_raster_payload
from lore_audit.read import (
    AuditReadError,
    Availability,
    ChunkListRequest,
    ImageDeliveryKind,
    ManifestRequest,
    OccurrenceListRequest,
    PayloadRequest,
    RunDetailRequest,
    TableProfileRequest,
)
from lore_audit.read_service import AuditReadService


def _project(result: Any) -> dict[str, Any]:
    return result.to_dict()


def _project_many(result: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [item.to_dict() for item in result]


def create_audit_router(
    service: AuditReadService,
    limits: AuditHttpLimits,
    *,
    prefix: str = "/api/v1/audit",
) -> APIRouter:
    """Create the exact injected audit read router without starting resources."""

    router = APIRouter(prefix=prefix)

    @router.get("/files")
    def list_files(query: Annotated[FileListQuery, Query()]) -> dict[str, Any]:
        return _project(service.list_files(query.to_request(limits)))

    @router.get("/files/detail")
    def get_file(query: Annotated[FileDetailQuery, Query()]) -> dict[str, Any]:
        return _project(service.get_file(query.to_request()))

    @router.get("/runs")
    def list_runs(query: Annotated[RunListQuery, Query()]) -> dict[str, Any]:
        return _project(service.list_runs(query.to_request(limits)))

    @router.get("/runs/{run_id}")
    def get_run(run_id: Identity) -> dict[str, Any]:
        return _project(service.get_run(RunDetailRequest(run_id)))

    @router.get("/runs/{run_id}/manifest")
    def get_manifest(
        run_id: Identity,
        query: Annotated[ManifestQuery, Query()],
    ) -> dict[str, Any]:
        request = ManifestRequest(
            run_id,
            limits.read_bounds(page_size=query.target_limit),
        )
        return _project(service.get_manifest(request))

    @router.get("/runs/{run_id}/chunks")
    def list_chunks(
        run_id: Identity,
        query: Annotated[PageQuery, Query()],
    ) -> dict[str, Any]:
        request = ChunkListRequest(
            run_id,
            query.cursor,
            limits.read_bounds(page_size=query.page_size),
        )
        return _project(service.list_chunks(request))

    @router.post("/runs/{run_id}/chunks/query")
    def get_chunks(run_id: Identity, body: ChunkBatchBody) -> list[dict[str, Any]]:
        return _project_many(service.get_chunks(body.to_request(run_id, limits)))

    @router.get("/runs/{run_id}/chunks/{chunk_id}")
    def get_chunk(
        run_id: Identity,
        chunk_id: Identity,
        query: Annotated[ChunkDetailQuery, Query()],
    ) -> dict[str, Any]:
        return _project(service.get_chunk(query.to_request(run_id, chunk_id, limits)))

    @router.get("/runs/{run_id}/chunks/{chunk_id}/neighbors")
    def get_chunk_neighbors(
        run_id: Identity,
        chunk_id: Identity,
        query: Annotated[ChunkNeighborsQuery, Query()],
    ) -> list[dict[str, Any]]:
        return _project_many(
            service.get_chunk_neighbors(query.to_request(run_id, chunk_id, limits))
        )

    @router.post("/runs/{run_id}/payloads/query")
    def get_payloads(run_id: Identity, body: PayloadBatchBody) -> list[dict[str, Any]]:
        return _project_many(service.get_payloads(body.to_request(run_id, limits)))

    @router.get("/runs/{run_id}/payloads/{payload_id}")
    def get_payload(run_id: Identity, payload_id: Identity) -> dict[str, Any]:
        return _project(service.get_payload(PayloadRequest(run_id, payload_id)))

    @router.get("/runs/{run_id}/payloads/{payload_id}/occurrences")
    def list_occurrences(
        run_id: Identity,
        payload_id: Identity,
        query: Annotated[OccurrenceListQuery, Query()],
    ) -> dict[str, Any]:
        request = OccurrenceListRequest(
            run_id,
            payload_id,
            query.cursor,
            limits.read_bounds(page_size=query.page_size),
        )
        return _project(service.list_occurrences(request))

    @router.get("/runs/{run_id}/payloads/{payload_id}/image")
    def get_image(
        run_id: Identity,
        payload_id: Identity,
        query: Annotated[ImageQuery, Query()],
    ) -> Response:
        result = service.get_image(query.to_request(run_id, payload_id, limits))
        delivery = result.delivery
        sensitive = delivery.sensitive
        if delivery.availability is Availability.UNAVAILABLE:
            if delivery.kind is ImageDeliveryKind.UNAVAILABLE and sensitive is None:
                return JSONResponse(result.to_dict())
            raise AuditReadError("read_failed")
        if delivery.availability is not Availability.AVAILABLE or sensitive is None:
            raise AuditReadError("read_failed")
        if (
            delivery.kind is ImageDeliveryKind.INLINE_PREVIEW
            and type(sensitive.value) is bytes
            and isinstance(delivery.content_type, str)
            and delivery.content_type
        ):
            payload = sensitive.value
            try:
                validate_safe_raster_payload(delivery.content_type, payload)
            except ValueError:
                raise AuditReadError("read_failed") from None
            if (
                delivery.byte_size != len(payload)
                or delivery.checksum_sha256 != hashlib.sha256(payload).hexdigest()
            ):
                raise AuditReadError("read_failed")
            return Response(
                content=payload,
                media_type=delivery.content_type,
                headers={"X-Content-Type-Options": "nosniff"},
            )
        if (
            delivery.kind is ImageDeliveryKind.TEMPORARY_LINK
            and type(sensitive.value) is str
        ):
            return RedirectResponse(url=sensitive.value, status_code=307)
        raise AuditReadError("read_failed")

    @router.get("/runs/{run_id}/payloads/{payload_id}/table/profile")
    def get_table_profile(run_id: Identity, payload_id: Identity) -> dict[str, Any]:
        request = TableProfileRequest(run_id, payload_id, limits.read_bounds())
        return _project(service.get_table_profile(request))

    @router.post("/runs/{run_id}/payloads/{payload_id}/table/query")
    def get_table_page(
        run_id: Identity,
        payload_id: Identity,
        body: TablePageBody,
    ) -> dict[str, Any]:
        return _project(service.get_table_page(body.to_request(run_id, payload_id, limits)))

    @router.post("/runs/{run_id}/payloads/{payload_id}/table/sample")
    def get_table_sample(
        run_id: Identity,
        payload_id: Identity,
        body: TableSampleBody,
    ) -> dict[str, Any]:
        return _project(service.get_table_sample(body.to_request(run_id, payload_id, limits)))

    @router.get("/runs/{run_id}/diagnostics")
    def list_diagnostics(
        run_id: Identity,
        query: Annotated[DiagnosticListQuery, Query()],
    ) -> dict[str, Any]:
        return _project(service.list_diagnostics(query.to_request(run_id, limits)))

    @router.post("/runs/{run_id}/references/resolve")
    def resolve_references(
        run_id: Identity,
        body: ReferenceBatchBody,
    ) -> list[dict[str, Any]]:
        return _project_many(service.resolve_references(body.to_request(run_id, limits)))

    @router.get("/runs/{run_id}/source-context")
    def get_source_context(
        run_id: Identity,
        query: Annotated[SourceContextQuery, Query()],
    ) -> dict[str, Any]:
        return _project(service.get_source_context(query.to_request(run_id, limits)))

    @router.get("/comparisons")
    def compare_runs(query: Annotated[ComparisonQuery, Query()]) -> dict[str, Any]:
        return _project(service.compare_runs(query.to_request()))

    return router


__all__ = ["create_audit_router"]
