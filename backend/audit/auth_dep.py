"""Auth for the audit router — reuses the chat's HS256 ticket.

Auth failures use a dedicated `AuditAuthError` rather than `HTTPException`, so
they are NOT swallowed by the audit safe-error handlers (which remap every
`StarletteHTTPException` to `invalid_request`/400). A dedicated, more-specific
exception handler maps it to a clean 401.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import jwt
from fastapi import Header
from fastapi.responses import JSONResponse

from auth import verify_ticket

if TYPE_CHECKING:
    from fastapi import FastAPI, Request


class AuditAuthError(Exception):
    """Raised when the audit request lacks a valid ticket. Mapped to HTTP 401."""


def require_audit_identity(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Validate the same Bearer ticket the chat frontend already carries."""
    if not authorization:
        raise AuditAuthError("missing authorization")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_ticket(token)
    except jwt.InvalidTokenError:
        raise AuditAuthError("invalid token") from None


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
