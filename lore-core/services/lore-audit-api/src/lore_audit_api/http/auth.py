"""Generic audit-auth error + its 401 handler (identity extraction is injected).

The package owns the *shape* of an auth failure (`AuditAuthError -> 401`) but not
the *mechanism* of extracting identity — callers inject that as a FastAPI
dependency. Raising `AuditAuthError` (not `HTTPException`) keeps auth failures
from being swallowed by the safe-error handlers, which remap every
`StarletteHTTPException` to `invalid_request`/400. This handler is more specific
in the MRO than the safe `Exception` catch-all, so it wins for auth failures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


class AuditAuthError(Exception):
    """Raised when the audit request carries no valid credential. Mapped to 401."""


async def _audit_auth_error_handler(request: "Request", exc: AuditAuthError) -> JSONResponse:
    del request, exc
    return JSONResponse(
        status_code=401,
        content={
            "schema_version": "audit-http/error/v1",
            "code": "unauthorized",
            "message": "authentication required",
            "resource": None,
        },
    )


def install_audit_auth_handler(app: "FastAPI") -> None:
    """Register the 401 handler. More specific than the safe Exception catch-all."""
    app.add_exception_handler(AuditAuthError, _audit_auth_error_handler)


__all__ = ["AuditAuthError", "install_audit_auth_handler"]
