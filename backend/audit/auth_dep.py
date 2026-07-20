"""Auth for the audit router.

Accepts the two credentials the backend already issues, so the existing frontend
works unchanged:

1. The Chainlit **session** — a JWT the browser sends as the `access_token` cookie
   (OAuth/authentik login) or as a Bearer header. Validated via `decode_jwt`.
2. A datacraft **HS256 ticket** as a Bearer header — the embedded/header-auth path
   (`@cl.header_auth_callback`). Validated via `verify_ticket`.

Auth failures raise `AuditAuthError` (not `HTTPException`), so they are NOT swallowed
by the audit safe-error handlers (which remap every `StarletteHTTPException` to
`invalid_request`/400). A dedicated handler maps it to a clean 401.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chainlit.auth import decode_jwt
from chainlit.auth.cookie import get_token_from_cookies
from fastapi import Request
from fastapi.responses import JSONResponse

from auth import verify_ticket

if TYPE_CHECKING:
    from fastapi import FastAPI


class AuditAuthError(Exception):
    """Raised when the audit request carries no valid session/ticket. Mapped to 401."""


def _extract_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization") or request.headers.get(
        "authorization"
    )
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return get_token_from_cookies(request.cookies)


def require_audit_identity(request: Request) -> dict[str, str]:
    """Authorize via Chainlit session (cookie/header) or a datacraft HS256 ticket."""
    token = _extract_token(request)
    if not token:
        raise AuditAuthError("no session or ticket")

    # 1) Chainlit session JWT (the browser frontend's access_token cookie).
    try:
        user = decode_jwt(token)
        return {"identifier": user.identifier, "username": user.identifier}
    except Exception:
        pass

    # 2) datacraft HS256 ticket (embedded/header-auth path).
    try:
        claims = verify_ticket(token)
    except Exception:
        raise AuditAuthError("invalid session or ticket") from None
    return {
        "identifier": claims["username"],
        "username": claims["username"],
        "sub": claims["sub"],
    }


async def _audit_auth_error_handler(request: Request, exc: AuditAuthError) -> JSONResponse:
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
