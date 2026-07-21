from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from audit.http_api.factory import create_audit_app
from audit.http_api.limits import AuditHttpLimits
from lore_audit.read_contracts import (
    Availability,
    ChunkBatchRequest,
    ChunkDetailRequest,
    ChunkListRequest,
    ChunkNeighborsRequest,
    DiagnosticListRequest,
    FileCardRequest,
    FileListRequest,
    ImageDelivery,
    ImageDeliveryKind,
    ImageReadResult,
    ImageRequest,
    ManifestRequest,
    OccurrenceListRequest,
    PayloadRequest,
    PayloadDetail,
    ReferenceBatchRequest,
    RunCompareRequest,
    RunDetailRequest,
    RunListRequest,
    SensitiveValue,
    SourceContextRequest,
    TableFilter,
    TablePageRequest,
    TableProfileRequest,
    TableSampleRequest,
)

RUN_A = "00000000-0000-0000-0000-000000000001"
RUN_B = "00000000-0000-0000-0000-000000000002"
PAYLOAD = "payload-1"
CHUNK = "chunk-1"

LIMITS = AuditHttpLimits(
    page_size_default=11,
    page_size_max=25,
    max_text_bytes=4096,
    max_batch_size=8,
    max_filter_count=3,
    max_filter_values=4,
    max_complexity=12,
    timeout_ms=3210,
)


@dataclass(frozen=True)
class Projection:
    operation: str
    marker: str = "preserved"

    def to_dict(self) -> dict[str, str]:
        return {"operation": self.operation, "marker": self.marker}


class RecordingService:
    def __init__(self, results: dict[str, object] | None = None) -> None:
        self.events: list[tuple[str, object]] = []
        self.results = results or {}

    def __getattr__(self, name: str) -> Any:
        def invoke(request: object) -> Projection | tuple[Projection, ...]:
            self.events.append((name, request))
            if name in self.results:
                return self.results[name]
            result = Projection(name)
            if name in {"get_chunk_neighbors", "get_chunks", "resolve_references"}:
                return (result, Projection(name, "second"))
            return result

        return invoke


def _client(results: dict[str, object] | None = None) -> tuple[TestClient, RecordingService]:
    service = RecordingService(results)
    return TestClient(create_audit_app(service, LIMITS)), service


def _bounds(*, page_size: int = 11, max_text_bytes: int = 4096):
    return LIMITS.read_bounds(page_size=page_size, max_text_bytes=max_text_bytes)


CASES = [
    ("get", "/api/v1/audit/files?search=Hello%20%20WORLD&page_size=7", None, "list_files", FileListRequest("hello world", (), None, _bounds(page_size=7))),
    ("get", "/api/v1/audit/files/detail?logical_file_key=docs/manual.pdf", None, "get_file", FileCardRequest("docs/manual.pdf")),
    ("get", "/api/v1/audit/runs?logical_file_key=docs/manual.pdf&cursor=next&page_size=5", None, "list_runs", RunListRequest("docs/manual.pdf", "next", _bounds(page_size=5))),
    ("get", f"/api/v1/audit/runs/{RUN_A}", None, "get_run", RunDetailRequest(RUN_A)),
    ("get", f"/api/v1/audit/runs/{RUN_A}/manifest?target_limit=6", None, "get_manifest", ManifestRequest(RUN_A, _bounds(page_size=6))),
    ("get", f"/api/v1/audit/runs/{RUN_A}/chunks?cursor=next&page_size=7", None, "list_chunks", ChunkListRequest(RUN_A, "next", _bounds(page_size=7))),
    ("post", f"/api/v1/audit/runs/{RUN_A}/chunks/query", {"chunk_ids": ["chunk-2", CHUNK]}, "get_chunks", ChunkBatchRequest(RUN_A, ("chunk-2", CHUNK), _bounds())),
    ("get", f"/api/v1/audit/runs/{RUN_A}/chunks/{CHUNK}?max_text_bytes=100&display_continuation=d&full_continuation=f&vector_continuation=v", None, "get_chunk", ChunkDetailRequest(RUN_A, CHUNK, _bounds(max_text_bytes=100), "d", "f", "v")),
    ("get", f"/api/v1/audit/runs/{RUN_A}/chunks/{CHUNK}/neighbors?before=2&after=3", None, "get_chunk_neighbors", ChunkNeighborsRequest(RUN_A, CHUNK, 2, 3, _bounds())),
    ("get", f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}", None, "get_payload", PayloadRequest(RUN_A, PAYLOAD)),
    ("get", f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/occurrences?cursor=next&page_size=4", None, "list_occurrences", OccurrenceListRequest(RUN_A, PAYLOAD, "next", _bounds(page_size=4))),
    ("get", f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/table/profile", None, "get_table_profile", TableProfileRequest(RUN_A, PAYLOAD, _bounds())),
    ("post", f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/table/query", {"columns": ["name", "score"], "filters": [{"column": "score", "operator": "gte", "values": [10]}], "sort_column": "score", "descending": True, "cursor": "next", "page_size": 5}, "get_table_page", TablePageRequest(RUN_A, PAYLOAD, ("name", "score"), (TableFilter("score", "gte", (10,)),), "score", True, "next", _bounds(page_size=5))),
    ("post", f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/table/sample", {"columns": ["name"], "limit": 3}, "get_table_sample", TableSampleRequest(RUN_A, PAYLOAD, ("name",), 3, _bounds(page_size=3))),
    ("get", f"/api/v1/audit/runs/{RUN_A}/diagnostics?origins=splitter&cursor=next&page_size=4", None, "list_diagnostics", DiagnosticListRequest(RUN_A, ("splitter",), "next", _bounds(page_size=4))),
    ("post", f"/api/v1/audit/runs/{RUN_A}/references/resolve", {"references": [{"payload_id": PAYLOAD, "kind": "table"}]}, "resolve_references", ReferenceBatchRequest(RUN_A, ((PAYLOAD, "table"),), _bounds())),
    ("get", f"/api/v1/audit/runs/{RUN_A}/source-context?max_source_bytes=512", None, "get_source_context", SourceContextRequest(RUN_A, _bounds(max_text_bytes=512))),
    ("get", f"/api/v1/audit/comparisons?left_run_id={RUN_A}&right_run_id={RUN_B}", None, "compare_runs", RunCompareRequest(RUN_A, RUN_B)),
]


@pytest.mark.parametrize(("method", "url", "body", "operation", "expected_request"), CASES)
def test_ordinary_routes_delegate_once_with_exact_request_and_projection(
    method: str,
    url: str,
    body: dict[str, Any] | None,
    operation: str,
    expected_request: object,
) -> None:
    client, service = _client()

    response = client.request(method, url, json=body)

    assert response.status_code == 200, response.text
    expected_result = Projection(operation)
    if operation in {"get_chunk_neighbors", "get_chunks", "resolve_references"}:
        assert response.json() == [expected_result.to_dict(), Projection(operation, "second").to_dict()]
    else:
        assert response.json() == expected_result.to_dict()
    assert service.events == [(operation, expected_request)]


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("get", "/api/v1/audit/runs//chunks", None),
        ("get", f"/api/v1/audit/runs/{RUN_A}/chunks?cursor=", None),
        ("get", "/api/v1/audit/files?page_size=26", None),
        ("get", "/api/v1/audit/files?unknown=value", None),
        ("post", f"/api/v1/audit/runs/{RUN_A}/chunks/query", {"chunk_ids": [f"chunk-{i}" for i in range(9)]}),
        ("post", f"/api/v1/audit/runs/{RUN_A}/chunks/query", {"chunk_ids": [CHUNK], "run_id": RUN_B}),
    ],
)
def test_invalid_transport_input_never_calls_service(
    method: str, url: str, body: dict[str, Any] | None
) -> None:
    client, service = _client()

    response = client.request(method, url, json=body)

    assert response.status_code in {400, 404}
    assert service.events == []


@pytest.mark.parametrize(
    ("url", "body"),
    [
        (
            f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/table/query",
            {"columns": ["name"], "page_size": "7"},
        ),
        (
            f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/table/query",
            {"columns": ["name"], "descending": "false"},
        ),
        (
            f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/table/query",
            {
                "columns": ["name"],
                "filters": [{"column": "name", "operator": "eq", "values": ["7"]}],
                "page_size": 1,
            },
        ),
        (
            f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/table/sample",
            {"columns": ["name"], "limit": "1"},
        ),
    ],
)
def test_post_json_scalars_are_strict_while_query_coercion_remains_query_only(
    url, body
) -> None:
    client, service = _client()

    response = client.post(url, json=body)

    if body.get("filters"):
        assert response.status_code == 200
        assert service.events[0][1].filters[0].values == ("7",)
    else:
        assert response.status_code == 400
        assert service.events == []


def _image_result(
    availability: Availability,
    kind: ImageDeliveryKind,
    sensitive: str | bytes | None,
) -> ImageReadResult:
    payload = PayloadDetail(RUN_A, PAYLOAD, "image", True, availability, {"caption": "safe"})
    inline_bytes = sensitive if type(sensitive) is bytes else b"image-metadata"
    delivery = ImageDelivery(
        PAYLOAD,
        availability,
        kind,
        "image/png",
        len(inline_bytes),
        hashlib.sha256(inline_bytes).hexdigest(),
        SensitiveValue(sensitive) if sensitive is not None else None,
        reason_code="preview_unavailable" if kind is ImageDeliveryKind.UNAVAILABLE else None,
    )
    return ImageReadResult(payload, delivery)


def test_image_route_returns_inline_bytes_with_exact_content_type_and_one_call() -> None:
    canary = b"\x89PNG\r\n\x1a\nPNG-CANARY-123"
    result = _image_result(
        Availability.AVAILABLE,
        ImageDeliveryKind.INLINE_PREVIEW,
        canary,
    )
    client, service = _client({"get_image": result})

    response = client.get(
        f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/image?max_inline_bytes=512"
    )

    assert response.status_code == 200
    assert response.content == canary
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert service.events == [
        ("get_image", ImageRequest(RUN_A, PAYLOAD, _bounds(max_text_bytes=512), True))
    ]
    assert "PNG-CANARY-123" not in repr(result)
    assert "PNG-CANARY-123" not in str(client.app.openapi())


def test_image_route_returns_temporary_redirect_without_serializing_url() -> None:
    canary = "https://signed.example/image?token=REDIRECT-CANARY"
    result = _image_result(
        Availability.AVAILABLE,
        ImageDeliveryKind.TEMPORARY_LINK,
        canary,
    )
    client, service = _client({"get_image": result})

    response = client.get(
        f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/image?prefer_inline=false",
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert response.headers["location"] == canary
    assert canary not in response.text
    assert canary not in repr(result)
    assert canary not in str(client.app.openapi())
    assert service.events == [("get_image", ImageRequest(RUN_A, PAYLOAD, _bounds(), False))]


def test_image_route_preserves_unavailable_safe_json() -> None:
    result = _image_result(
        Availability.UNAVAILABLE,
        ImageDeliveryKind.UNAVAILABLE,
        None,
    )
    client, service = _client({"get_image": result})

    response = client.get(f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/image")

    assert response.status_code == 200
    assert response.json() == result.to_dict()
    assert service.events == [("get_image", ImageRequest(RUN_A, PAYLOAD, _bounds(), True))]


@pytest.mark.parametrize(
    "result",
    [
        _image_result(
            Availability.AVAILABLE,
            ImageDeliveryKind.INLINE_PREVIEW,
            "not-bytes",
        ),
        _image_result(
            Availability.AVAILABLE,
            ImageDeliveryKind.TEMPORARY_LINK,
            b"not-a-url",
        ),
        _image_result(
            Availability.UNAVAILABLE,
            ImageDeliveryKind.INLINE_PREVIEW,
            None,
        ),
    ],
)
def test_image_route_rejects_delivery_mismatches_as_safe_read_failure(
    result: ImageReadResult,
) -> None:
    client, service = _client({"get_image": result})

    response = client.get(f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/image")

    assert response.status_code == 500
    assert response.json()["code"] == "read_failed"
    assert "not-bytes" not in response.text
    assert "not-a-url" not in response.text
    assert service.events == [("get_image", ImageRequest(RUN_A, PAYLOAD, _bounds(), True))]


@pytest.mark.parametrize(
    ("content_type", "payload"),
    [
        ("image/svg+xml", b"<svg><script>alert(1)</script></svg>"),
        ("image/png", b"<html>active</html>\x89PNG\r\n\x1a\n"),
        ("image/png", b"GIF89a<html>polyglot</html>"),
        ("image/png\r\nX-Injected: yes", b"\x89PNG\r\n\x1a\nbytes"),
    ],
)
def test_image_route_rejects_unsafe_inline_media_before_response(content_type, payload) -> None:
    result = _image_result(
        Availability.AVAILABLE,
        ImageDeliveryKind.INLINE_PREVIEW,
        payload,
    )
    object.__setattr__(result.delivery, "content_type", content_type)
    object.__setattr__(result.delivery, "byte_size", len(payload))
    object.__setattr__(
        result.delivery, "checksum_sha256", hashlib.sha256(payload).hexdigest()
    )
    client, service = _client({"get_image": result})

    response = client.get(f"/api/v1/audit/runs/{RUN_A}/payloads/{PAYLOAD}/image")

    assert response.status_code == 500
    assert response.json()["code"] == "read_failed"
    assert "script" not in response.text
    assert service.events == [("get_image", ImageRequest(RUN_A, PAYLOAD, _bounds(), True))]


EXPECTED_OPERATIONS = {
    ("get", "/api/v1/audit/files"),
    ("get", "/api/v1/audit/files/detail"),
    ("get", "/api/v1/audit/runs"),
    ("get", "/api/v1/audit/runs/{run_id}"),
    ("get", "/api/v1/audit/runs/{run_id}/manifest"),
    ("get", "/api/v1/audit/runs/{run_id}/chunks"),
    ("post", "/api/v1/audit/runs/{run_id}/chunks/query"),
    ("get", "/api/v1/audit/runs/{run_id}/chunks/{chunk_id}"),
    ("get", "/api/v1/audit/runs/{run_id}/chunks/{chunk_id}/neighbors"),
    ("get", "/api/v1/audit/runs/{run_id}/payloads/{payload_id}"),
    ("get", "/api/v1/audit/runs/{run_id}/payloads/{payload_id}/occurrences"),
    ("get", "/api/v1/audit/runs/{run_id}/payloads/{payload_id}/table/profile"),
    ("post", "/api/v1/audit/runs/{run_id}/payloads/{payload_id}/table/query"),
    ("post", "/api/v1/audit/runs/{run_id}/payloads/{payload_id}/table/sample"),
    ("get", "/api/v1/audit/runs/{run_id}/payloads/{payload_id}/image"),
    ("get", "/api/v1/audit/runs/{run_id}/diagnostics"),
    ("post", "/api/v1/audit/runs/{run_id}/references/resolve"),
    ("get", "/api/v1/audit/runs/{run_id}/source-context"),
    ("get", "/api/v1/audit/comparisons"),
}


def _operations(schema: dict[str, Any]) -> set[tuple[str, str]]:
    methods = {"get", "post", "put", "patch", "delete"}
    return {
        (method, path)
        for path, path_item in schema["paths"].items()
        for method in path_item
        if method in methods
    }


def _property_names(value: object) -> set[str]:
    if isinstance(value, list):
        return set().union(*(_property_names(item) for item in value), set())
    if not isinstance(value, dict):
        return set()
    names = set(value.get("properties", {}))
    for nested in value.values():
        names.update(_property_names(nested))
    return names


def test_openapi_is_exact_deterministic_and_read_only() -> None:
    first = create_audit_app(RecordingService(), LIMITS).openapi()
    second = create_audit_app(RecordingService(), LIMITS).openapi()
    rendered = json.dumps(first, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    rerendered = json.dumps(second, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    assert rendered == rerendered
    assert _operations(first) == EXPECTED_OPERATIONS
    assert sum(method == "get" for method, _ in EXPECTED_OPERATIONS) == 15
    assert sum(method == "post" for method, _ in EXPECTED_OPERATIONS) == 4
    assert first["info"] == {
        "title": "Lore Splitter Audit Read API",
        "description": "Bounded read-only inspection facade for persisted splitter evidence.",
        "version": "1.3.0",
    }

    forbidden_segments = {"process", "processing", "review", "comment", "finding", "ai"}
    assert not any(
        forbidden_segments.intersection(segment.casefold() for segment in path.split("/"))
        for _, path in EXPECTED_OPERATIONS
    )
    assert not {"put", "patch", "delete"}.intersection(method for method, _ in _operations(first))
    component_schemas = first.get("components", {}).get("schemas", {})
    properties = {name.casefold() for name in _property_names(component_schemas)}
    assert properties.isdisjoint(
        {
            "schema",
            "table",
            "bucket",
            "key",
            "uri",
            "dsn",
            "connection",
            "sql",
            "expression",
            "hook",
            "raw_record",
            "password",
            "secret",
            "capability_token",
        }
    )
    assert all(
        value is False
        for schema in component_schemas.values()
        for key, value in schema.items()
        if key == "additionalProperties"
    )


def test_http_subpackage_exports_only_the_explicit_factory_surface() -> None:
    from audit import http_api

    assert http_api.create_audit_app is create_audit_app
    assert callable(http_api.create_audit_router)
