from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from audit.http_api.contracts import (
    ChunkBatchBody,
    ChunkDetailQuery,
    ChunkNeighborsQuery,
    ComparisonQuery,
    DiagnosticListQuery,
    FileDetailQuery,
    FileListQuery,
    ImageQuery,
    PageQuery,
    ReferenceBatchBody,
    SourceContextQuery,
    TableFilterInput,
    TablePageBody,
    TableSampleBody,
)
from audit.http_api.limits import AuditHttpLimits
from audit.http_api.errors import (
    install_safe_error_handlers,
    normalize_http_error,
)
from audit.read_contracts import (
    AuditReadError,
    ChunkBatchRequest,
    FileListRequest,
    ReferenceBatchRequest,
    TableFilter,
    TablePageRequest,
)
from audit._vendor.run_status import RunStatus

RUN_ID = "00000000-0000-0000-0000-000000000023"


def test_limits_are_frozen_server_owned_and_build_complete_reduced_bounds() -> None:
    limits = AuditHttpLimits(
        page_size_default=25,
        page_size_max=50,
        max_text_bytes=4096,
        max_batch_size=4,
        max_filter_count=2,
        max_filter_values=1,
        max_complexity=8,
        timeout_ms=750,
    )

    bounds = limits.read_bounds(page_size=10, max_text_bytes=1024)

    assert bounds.page_size == 10
    assert bounds.max_text_bytes == 1024
    assert bounds.max_batch_size == 4
    assert bounds.max_filter_count == 2
    assert bounds.max_filter_values == 1
    assert bounds.max_complexity == 8
    assert bounds.timeout_ms == 750
    assert limits.read_bounds(page_size=10, max_text_bytes=1024) == bounds
    with pytest.raises(FrozenInstanceError):
        limits.timeout_ms = 99
    for request in ({"page_size": 51}, {"max_text_bytes": 4097}):
        with pytest.raises(AuditReadError) as error:
            limits.read_bounds(**request)
        assert error.value.code == "bounds_exceeded"
    with pytest.raises(ValueError):
        AuditHttpLimits(timeout_ms=True)


def test_file_transport_is_strict_bounded_and_builds_exact_phase22_request() -> None:
    limits = AuditHttpLimits(page_size_default=20, page_size_max=40)
    query = FileListQuery(
        search="  Employee   Handbook ",
        statuses=[RunStatus.SUCCESS, RunStatus.FAILED],
        cursor="opaque",
        page_size=10,
    )

    request = query.to_request(limits)

    assert request == FileListRequest(
        search="employee handbook",
        statuses=(RunStatus.FAILED, RunStatus.SUCCESS),
        cursor="opaque",
        bounds=limits.read_bounds(page_size=10),
    )
    for hostile in (
        {"schema": "public"},
        {"table": "audit_runs"},
        {"sql": "select 1"},
        {"connection_id": "secret"},
        {"timeout_ms": 999999},
        {"max_batch_size": 999999},
    ):
        with pytest.raises(ValidationError):
            FileListQuery(**hostile)
    with pytest.raises(ValidationError):
        FileListQuery(page_size=True)
    with pytest.raises(ValidationError):
        FileListQuery(statuses=["invented"])
    with pytest.raises(ValidationError):
        FileDetailQuery(logical_file_key="🙂" * 129)
    with pytest.raises(ValidationError):
        PageQuery(cursor="x" * 4097)


def test_batch_neighborhood_and_reference_models_are_closed_and_capped() -> None:
    limits = AuditHttpLimits(max_batch_size=2)
    body = ChunkBatchBody(chunk_ids=["chunk-b", "chunk-a"])

    assert body.to_request(RUN_ID, limits) == ChunkBatchRequest(
        RUN_ID,
        ("chunk-a", "chunk-b"),
        limits.read_bounds(),
    )
    with pytest.raises(AuditReadError) as error:
        ChunkBatchBody(chunk_ids=["a", "b", "c"]).to_request(RUN_ID, limits)
    assert error.value.code == "bounds_exceeded"
    with pytest.raises(ValidationError):
        ChunkNeighborsQuery(before=True, after=1)
    with pytest.raises(ValidationError):
        ReferenceBatchBody(references=[{"payload_id": "p", "kind": "video"}])
    references = ReferenceBatchBody(
        references=[
            {"payload_id": "image-a", "kind": "image"},
            {"payload_id": "table-a", "kind": "table"},
        ]
    )
    assert references.to_request(RUN_ID, limits) == ReferenceBatchRequest(
        RUN_ID,
        (("image-a", "image"), ("table-a", "table")),
        limits.read_bounds(),
    )


def test_table_transport_rejects_unbounded_trees_and_builds_typed_filters() -> None:
    limits = AuditHttpLimits(
        page_size_default=10,
        page_size_max=20,
        max_batch_size=3,
        max_filter_count=1,
        max_filter_values=1,
        max_complexity=5,
    )
    body = TablePageBody(
        columns=["employee", "amount"],
        filters=[{"column": "amount", "operator": "gte", "values": [10]}],
        sort_column="amount",
        descending=True,
        cursor="next",
        page_size=5,
    )

    assert body.to_request(RUN_ID, "table-a", limits) == TablePageRequest(
        RUN_ID,
        "table-a",
        ("employee", "amount"),
        (TableFilter("amount", "gte", (10,)),),
        "amount",
        True,
        "next",
        limits.read_bounds(page_size=5),
    )
    with pytest.raises(ValidationError):
        TableFilterInput(column="amount", operator="between", values=[1])
    with pytest.raises(ValidationError):
        TableFilterInput(column="amount", operator="eq", values=[{"sql": "select"}])
    with pytest.raises(AuditReadError) as error:
        TablePageBody(
            columns=["a"],
            filters=[
                {"column": "a", "operator": "eq", "values": [1]},
                {"column": "a", "operator": "ne", "values": [2]},
            ],
        ).to_request(RUN_ID, "table-a", limits)
    assert error.value.code == "bounds_exceeded"
    with pytest.raises(ValidationError):
        TableSampleBody(columns=["a"], limit=True)
    with pytest.raises(ValidationError):
        TablePageBody(columns=["a"], page_size="7")
    with pytest.raises(ValidationError):
        TablePageBody(columns=["a"], descending="false")


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (ChunkDetailQuery, {"max_text_bytes": True}),
        (DiagnosticListQuery, {"origins": ["database"]}),
        (ImageQuery, {"prefer_inline": 1}),
        (SourceContextQuery, {"max_source_bytes": True}),
        (ComparisonQuery, {"left_run_id": "a", "right_run_id": "a"}),
    ],
)
def test_remaining_transport_models_reject_ambiguous_or_invalid_values(model, payload) -> None:
    with pytest.raises(ValidationError):
        model(**payload)


@pytest.mark.parametrize(
    ("code", "status", "message"),
    [
        ("invalid_request", 400, "audit request is invalid"),
        ("invalid_cursor", 400, "audit cursor is invalid"),
        ("bounds_exceeded", 400, "audit request exceeds configured bounds"),
        ("not_found", 404, "audit resource was not found"),
        ("membership_mismatch", 409, "audit resource membership is invalid"),
        ("registration_invalid", 409, "audit payload registration is invalid"),
        ("capability_unavailable", 503, "audit capability is unavailable"),
        ("dependency_timeout", 504, "audit dependency timed out"),
        ("read_failed", 500, "audit read failed"),
    ],
)
def test_safe_error_projection_has_locked_status_and_four_fields(code, status, message) -> None:
    projected_status, envelope = normalize_http_error(
        AuditReadError(code, resource="chunk")
    )

    assert projected_status == status
    assert envelope.model_dump() == {
        "schema_version": "audit-http/error/v1",
        "code": code,
        "message": message,
        "resource": None if status == 500 else "chunk",
    }
    assert envelope.model_fields_set == {"schema_version", "code", "message", "resource"}


def test_safe_error_projection_drops_unknown_codes_resources_and_exception_details() -> None:
    canary = "postgresql://user:password@private/audit?locator=s3://secret-bucket/key"
    failure = RuntimeError(canary)
    failure.__cause__ = ValueError(f"cause:{canary}")
    failure.__context__ = LookupError(f"context:{canary}")

    status, envelope = normalize_http_error(failure)
    unknown_status, unknown = normalize_http_error(
        AuditReadError("invented", resource=canary)
    )
    rendered = envelope.model_dump_json() + repr(envelope) + unknown.model_dump_json()

    assert (status, envelope.code, envelope.resource) == (500, "read_failed", None)
    assert (unknown_status, unknown.code, unknown.resource) == (500, "read_failed", None)
    assert canary not in rendered
    assert "password" not in rendered
    assert "cause:" not in rendered
    assert "context:" not in rendered


def test_framework_errors_share_safe_envelope_and_degradation_remains_success_data() -> None:
    canary = "SIGNED-URL-CANARY?token=super-secret"
    app = FastAPI()

    @app.get("/validated")
    def validated(page_size: int) -> dict[str, int]:
        return {"page_size": page_size}

    @app.get("/service-error")
    def service_error() -> None:
        raise AuditReadError("not_found", resource="chunk")

    @app.get("/unexpected")
    def unexpected() -> None:
        raise RuntimeError(canary) from ValueError(f"cause:{canary}")

    @app.get("/degraded")
    def degraded() -> dict[str, object]:
        return {"availability": "unavailable", "partial": True, "truncated": True}

    install_safe_error_handlers(app)
    client = TestClient(app, raise_server_exceptions=False)

    responses = [
        client.get(f"/validated?page_size={canary}"),
        client.post("/validated", json={"body": canary}),
        client.get("/missing"),
        client.get("/service-error"),
        client.get("/unexpected"),
    ]

    assert [response.status_code for response in responses] == [400, 400, 404, 404, 500]
    for response in responses:
        assert set(response.json()) == {"schema_version", "code", "message", "resource"}
        assert canary not in response.text
        assert "body" not in response.text
        assert "cause" not in response.text
    assert client.get("/degraded").json() == {
        "availability": "unavailable",
        "partial": True,
        "truncated": True,
    }
