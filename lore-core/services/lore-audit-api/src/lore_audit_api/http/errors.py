"""Safe exception projection for the optional audit HTTP boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHttpException

from lore_audit_api.http.contracts import AuditHttpErrorEnvelope
from lore_audit.read_contracts import AuditReadError

if TYPE_CHECKING:
    from fastapi import FastAPI, Request

_ERRORS = {
    "invalid_request": (400, "audit request is invalid"),
    "invalid_cursor": (400, "audit cursor is invalid"),
    "bounds_exceeded": (400, "audit request exceeds configured bounds"),
    "not_found": (404, "audit resource was not found"),
    "membership_mismatch": (409, "audit resource membership is invalid"),
    "registration_invalid": (409, "audit payload registration is invalid"),
    "capability_unavailable": (503, "audit capability is unavailable"),
    "dependency_timeout": (504, "audit dependency timed out"),
    "read_failed": (500, "audit read failed"),
}
_RESOURCES = frozenset({"file", "run", "chunk", "payload", "source", "comparison"})


def normalize_http_error(exc: Exception) -> tuple[int, AuditHttpErrorEnvelope]:
    """Project an exception without reading its message, values, cause, or context."""
    code = "read_failed"
    resource = None
    if isinstance(exc, AuditReadError):
        candidate = exc.code
        if candidate in _ERRORS:
            code = candidate
        if code != "read_failed" and exc.resource in _RESOURCES:
            resource = exc.resource
    elif isinstance(exc, RequestValidationError):
        code = "invalid_request"
    elif isinstance(exc, StarletteHttpException):
        code = "not_found" if exc.status_code == 404 else "invalid_request"

    status, message = _ERRORS[code]
    envelope = AuditHttpErrorEnvelope(
        schema_version="audit-http/error/v1",
        code=code,
        message=message,
        resource=resource,
    )
    return status, envelope


def _response(exc: Exception) -> JSONResponse:
    status, envelope = normalize_http_error(exc)
    return JSONResponse(status_code=status, content=envelope.model_dump())


async def _audit_read_error_handler(request: Request, exc: AuditReadError) -> JSONResponse:
    del request
    return _response(exc)


async def _validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    del request
    return _response(exc)


async def _framework_error_handler(
    request: Request, exc: StarletteHttpException
) -> JSONResponse:
    del request
    return _response(exc)


async def _unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    return _response(exc)


def install_safe_error_handlers(app: FastAPI) -> None:
    """Install the single safe public error contract on a FastAPI application."""
    app.add_exception_handler(AuditReadError, _audit_read_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHttpException, _framework_error_handler)
    app.add_exception_handler(Exception, _unexpected_error_handler)


__all__ = ["install_safe_error_handlers", "normalize_http_error"]
