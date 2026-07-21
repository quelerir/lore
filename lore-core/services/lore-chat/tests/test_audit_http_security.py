from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient


from audit.http_api.factory import create_audit_app
from audit.http_api.middleware import AuditHttpMiddleware
from lore_audit.read_contracts import AuditReadError

RUN_ID = "00000000-0000-0000-0000-000000000023"


@dataclass(frozen=True)
class _Projection:
    value: str = "safe"

    def to_dict(self) -> dict[str, str]:
        return {"value": self.value}


class _Service:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        result: _Projection | None = None,
    ) -> None:
        self.calls = 0
        self.failure = failure
        self.result = result or _Projection()

    def __getattr__(self, name: str) -> Any:
        def invoke(request: object) -> _Projection:
            del request
            self.calls += 1
            if self.failure is not None:
                raise self.failure
            return self.result

        return invoke


def _scope(
    *,
    raw_path: bytes = b"/api/v1/audit/files",
    query_string: bytes = b"",
    headers: list[tuple[bytes, bytes]] | None = None,
    method: str = "POST",
) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": raw_path.decode("ascii", errors="ignore"),
        "raw_path": raw_path,
        "query_string": query_string,
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "root_path": "",
    }


def _run_asgi(
    middleware: AuditHttpMiddleware,
    scope: dict[str, Any],
    frames: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    sent: list[dict[str, Any]] = []
    calls = 0

    async def receive() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if frames:
            return frames.pop(0)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(middleware(scope, receive, send))
    return sent, calls


@pytest.mark.parametrize(
    ("scope", "frames", "expected_receive_calls"),
    [
        (_scope(raw_path=b"/" + b"p" * 33), [], 0),
        (_scope(query_string=b"q=" + b"x" * 31), [], 0),
        (_scope(headers=[(b"content-length", b"9")]), [], 0),
        (
            _scope(headers=[(b"content-length", b"1")]),
            [
                {"type": "http.request", "body": b"1234", "more_body": True},
                {"type": "http.request", "body": b"56789", "more_body": False},
            ],
            2,
        ),
        (
            _scope(),
            [
                {"type": "http.request", "body": b"1234", "more_body": True},
                {"type": "http.request", "body": b"56789", "more_body": False},
            ],
            2,
        ),
    ],
)
def test_early_caps_return_one_safe_error_before_service_work(
    scope: dict[str, Any],
    frames: list[dict[str, Any]],
    expected_receive_calls: int,
) -> None:
    service_calls = 0

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        del scope
        nonlocal service_calls
        while True:
            message = await receive()
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        service_calls += 1
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = AuditHttpMiddleware(
        app,
        max_path_bytes=32,
        max_query_bytes=32,
        max_body_bytes=8,
    )
    sent, receive_calls = _run_asgi(middleware, scope, list(frames))

    assert service_calls == 0
    assert receive_calls == expected_receive_calls
    assert sent[0]["status"] == 400
    body = json.loads(sent[1]["body"])
    assert body == {
        "schema_version": "audit-http/error/v1",
        "code": "bounds_exceeded",
        "message": "audit request exceeds configured bounds",
        "resource": None,
    }


@pytest.mark.parametrize(
    ("method", "headers"),
    [
        ("GET", [(b"content-length", b"1")]),
        ("HEAD", [(b"content-length", b"1")]),
        ("GET", [(b"transfer-encoding", b"chunked")]),
        ("HEAD", [(b"transfer-encoding", b"identity")]),
    ],
)
def test_get_and_head_declared_bodies_are_rejected_without_downstream_receive(
    method, headers
) -> None:
    downstream_calls = 0
    downstream_receive_calls = 0

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        del scope, receive
        nonlocal downstream_calls, downstream_receive_calls
        downstream_calls += 1
        downstream_receive_calls += 1
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    middleware = AuditHttpMiddleware(app, max_body_bytes=8)
    sent, receive_calls = _run_asgi(
        middleware,
        _scope(method=method, headers=headers),
        [{"type": "http.request", "body": b"x", "more_body": False}],
    )

    assert downstream_calls == 0
    assert downstream_receive_calls == 0
    assert receive_calls == 0
    assert sent[0]["status"] == 400
    assert json.loads(sent[1]["body"])["code"] == "invalid_request"


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
def test_no_body_method_with_verified_empty_event_reaches_non_reading_downstream(
    method,
) -> None:
    downstream_calls = 0

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        del scope, receive
        nonlocal downstream_calls
        downstream_calls += 1
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sent, receive_calls = _run_asgi(
        AuditHttpMiddleware(app, max_body_bytes=8),
        _scope(method=method),
        [{"type": "http.request", "body": b"", "more_body": False}],
    )

    assert downstream_calls == 1
    assert receive_calls == 1
    assert sent[0]["status"] == 204


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
@pytest.mark.parametrize(
    "frame",
    [
        {"type": "http.request", "body": b"headerless", "more_body": False},
        {"type": "http.request", "body": b"", "more_body": True},
    ],
)
def test_headerless_no_body_method_is_rejected_before_nonreading_downstream(
    method, frame
) -> None:
    downstream_calls = 0

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        del scope, receive
        nonlocal downstream_calls
        downstream_calls += 1
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sent, receive_calls = _run_asgi(
        AuditHttpMiddleware(app, max_body_bytes=8),
        _scope(method=method),
        [frame],
    )

    assert downstream_calls == 0
    assert receive_calls == 1
    assert sent[0]["status"] == 400
    assert json.loads(sent[1]["body"])["code"] == "invalid_request"


@pytest.mark.parametrize(
    "frame",
    [
        {"type": "http.disconnect"},
        {"type": "websocket.receive", "bytes": b"unexpected"},
        {"body": b"missing-type"},
    ],
)
def test_no_body_method_rejects_non_request_first_event_before_downstream(frame) -> None:
    downstream_calls = 0

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        del scope, receive
        nonlocal downstream_calls
        downstream_calls += 1
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sent, receive_calls = _run_asgi(
        AuditHttpMiddleware(app, max_body_bytes=8),
        _scope(method="GET"),
        [frame],
    )

    assert downstream_calls == 0
    assert receive_calls == 1
    assert sent[0]["status"] == 400
    assert json.loads(sent[1]["body"])["code"] == "invalid_request"


def test_verified_empty_no_body_event_is_replayed_if_downstream_reads() -> None:
    observed = []

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        del scope
        observed.append(await receive())
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    empty = {"type": "http.request", "body": b"", "more_body": False}
    sent, receive_calls = _run_asgi(
        AuditHttpMiddleware(app, max_body_bytes=8),
        _scope(method="OPTIONS"),
        [empty.copy()],
    )

    assert observed == [empty]
    assert receive_calls == 1
    assert sent[0]["status"] == 204


def test_access_logs_are_exact_metadata_only_across_all_outcomes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    query_canary = "QUERY-CANARY"
    exception_canary = "EXCEPTION-CANARY"
    path_canary = "PATH-CANARY"
    caplog.set_level(logging.INFO, logger="audit.http")

    success_service = _Service()
    success_client = TestClient(create_audit_app(success_service))
    success = success_client.get(f"/api/v1/audit/files?search={query_canary}")

    rejected_service = _Service()
    rejected_client = TestClient(create_audit_app(rejected_service))
    rejected = rejected_client.get("/api/v1/audit/files?" + "q=" + "x" * 9000)

    missing = success_client.get(f"/{path_canary}")

    failure_service = _Service(failure=RuntimeError(exception_canary))
    failure_client = TestClient(create_audit_app(failure_service), raise_server_exceptions=False)
    failure = failure_client.get("/api/v1/audit/files")

    assert [success.status_code, rejected.status_code, missing.status_code, failure.status_code] == [
        200,
        400,
        404,
        500,
    ]
    assert success_service.calls == 1
    assert rejected_service.calls == 0

    records = [
        record.msg
        for record in caplog.records
        if record.name == "audit.http"
    ]
    assert len(records) == 4
    for record in records:
        assert set(record) == {
            "method",
            "route_template",
            "status",
            "duration",
            "correlation_id",
        }
        assert record["method"] == "GET"
        assert type(record["status"]) is int
        assert type(record["duration"]) is float and record["duration"] >= 0
        assert isinstance(record["correlation_id"], str)
        assert 1 <= len(record["correlation_id"]) <= 32

    assert records[0]["route_template"] == "/api/v1/audit/files"
    assert records[1]["route_template"] == "<pre-routing>"
    assert records[2]["route_template"] == "<unmatched>"
    assert records[3]["route_template"] == "/api/v1/audit/files"
    rendered = json.dumps(records, sort_keys=True)
    assert query_canary not in rendered
    assert exception_canary not in rendered
    assert path_canary not in rendered


def test_raised_timeout_is_504_while_typed_degradation_remains_200() -> None:
    timeout = TestClient(
        create_audit_app(_Service(failure=AuditReadError("dependency_timeout")))
    ).get("/api/v1/audit/files")
    degraded = TestClient(
        create_audit_app(_Service(result=_Projection("unavailable")))
    ).get("/api/v1/audit/files")

    assert timeout.status_code == 504
    assert timeout.json() == {
        "schema_version": "audit-http/error/v1",
        "code": "dependency_timeout",
        "message": "audit dependency timed out",
        "resource": None,
    }
    assert degraded.status_code == 200
    assert degraded.json() == {"value": "unavailable"}


def test_injected_app_lifespan_closes_runtime_resources_once() -> None:
    events = []
    app = create_audit_app(_Service(), shutdown=lambda: events.append("closed"))

    with TestClient(app):
        assert events == []

    assert events == ["closed"]


