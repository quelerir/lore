"""Early ASGI resource caps and disclosure-safe audit access logging."""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_LOGGER = logging.getLogger("audit.http")
_ALLOWED_METHODS = frozenset({"GET", "POST", "HEAD", "OPTIONS"})
_NO_BODY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_PRE_ROUTING = "<pre-routing>"
_UNMATCHED = "<unmatched>"
_BOUNDS_BODY = json.dumps(
    {
        "schema_version": "audit-http/error/v1",
        "code": "bounds_exceeded",
        "message": "audit request exceeds configured bounds",
        "resource": None,
    },
    separators=(",", ":"),
).encode("utf-8")
_INVALID_REQUEST_BODY = json.dumps(
    {
        "schema_version": "audit-http/error/v1",
        "code": "invalid_request",
        "message": "audit request is invalid",
        "resource": None,
    },
    separators=(",", ":"),
).encode("utf-8")


class _BodyTooLarge(Exception):
    """Private control-flow signal raised before forwarding an oversized frame."""


def _positive_limit(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("invalid audit HTTP byte limit")
    return value


def _declared_body_too_large(scope: Scope, limit: int) -> bool:
    for name, value in scope.get("headers", ()):  # ASGI headers are raw bytes.
        if name.lower() != b"content-length" or not value.isdigit():
            continue
        try:
            if int(value) > limit:
                return True
        except ValueError:
            continue
    return False


def _read_method_declares_body(scope: Scope) -> bool:
    if scope.get("method") not in _NO_BODY_METHODS:
        return False
    for name, value in scope.get("headers", ()):
        lowered = name.lower()
        if lowered == b"transfer-encoding":
            return True
        if lowered == b"content-length" and (not value.isdigit() or int(value) != 0):
            return True
    return False


def _safe_method(scope: Scope) -> str:
    method = scope.get("method")
    return method if type(method) is str and method in _ALLOWED_METHODS else "OTHER"


def _route_template(scope: Scope, *, pre_routing: bool) -> str:
    if pre_routing:
        return _PRE_ROUTING
    route = scope.get("route")
    template = getattr(route, "path", None)
    if type(template) is str and template.startswith("/") and len(template) <= 512:
        return template
    return _UNMATCHED


async def _send_bounds_error(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 400,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_BOUNDS_BODY)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _BOUNDS_BODY})


async def _send_invalid_request(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 400,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_INVALID_REQUEST_BODY)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": _INVALID_REQUEST_BODY})


class AuditHttpMiddleware:
    """Bound raw targets and streamed bodies without materializing request content."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_path_bytes: int = 2_048,
        max_query_bytes: int = 8_192,
        max_body_bytes: int = 1_048_576,
    ) -> None:
        self._app = app
        self._max_path_bytes = _positive_limit(max_path_bytes)
        self._max_query_bytes = _positive_limit(max_query_bytes)
        self._max_body_bytes = _positive_limit(max_body_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        started = time.perf_counter()
        correlation_id = secrets.token_hex(16)
        status = 500
        response_started = False
        pre_routing = False

        async def observe_send(message: Message) -> None:
            nonlocal response_started, status
            if message["type"] == "http.response.start":
                response_started = True
                status = int(message["status"])
            await send(message)

        raw_path = scope.get("raw_path", b"")
        query = scope.get("query_string", b"")
        target_too_large = (
            not isinstance(raw_path, bytes)
            or not isinstance(query, bytes)
            or len(raw_path) > self._max_path_bytes
            or len(query) > self._max_query_bytes
            or _declared_body_too_large(scope, self._max_body_bytes)
        )

        try:
            if target_too_large:
                pre_routing = True
                status = 400
                await _send_bounds_error(observe_send)
                return
            if _read_method_declares_body(scope):
                pre_routing = True
                status = 400
                await _send_invalid_request(observe_send)
                return

            received = 0

            async def bounded_receive() -> Message:
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    body = message.get("body", b"")
                    if not isinstance(body, bytes):
                        raise _BodyTooLarge
                    received += len(body)
                    if received > self._max_body_bytes:
                        raise _BodyTooLarge
                return message

            try:
                app_receive = bounded_receive
                if scope.get("method") in _NO_BODY_METHODS:
                    first_event = await receive()
                    body = first_event.get("body", b"")
                    if (
                        first_event.get("type") != "http.request"
                        or not isinstance(body, bytes)
                        or body
                        or first_event.get("more_body", False) is not False
                    ):
                        pre_routing = True
                        status = 400
                        await _send_invalid_request(observe_send)
                        return
                    replay_pending = True

                    async def replay_receive() -> Message:
                        nonlocal replay_pending
                        if replay_pending:
                            replay_pending = False
                            return first_event
                        return await bounded_receive()

                    app_receive = replay_receive
                await self._app(scope, app_receive, observe_send)
            except _BodyTooLarge:
                if response_started:
                    raise
                status = 400
                await _send_bounds_error(observe_send)
        finally:
            record: dict[str, Any] = {
                "method": _safe_method(scope),
                "route_template": _route_template(scope, pre_routing=pre_routing),
                "status": status,
                "duration": round(time.perf_counter() - started, 6),
                "correlation_id": correlation_id,
            }
            _LOGGER.info(record)


__all__ = ["AuditHttpMiddleware"]
