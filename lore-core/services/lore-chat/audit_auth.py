"""Chat-side auth for the mounted audit router (cookie + ticket).

Accepts the two credentials the backend already issues, so the existing frontend
works unchanged:

1. The Chainlit **session** — a JWT the browser sends as the `access_token` cookie
   (OAuth/authentik login) or as a Bearer header. Validated via `decode_jwt`.
2. A datacraft **HS256 ticket** as a Bearer header — the embedded/header-auth path
   (`@cl.header_auth_callback`). Validated via `verify_ticket`.

Auth failures raise `AuditAuthError` (the package's error type, so they are NOT
swallowed by the audit safe-error handlers, and the package's dedicated 401
handler — installed by `create_audit_app` — maps them to a clean 401). Only the
identity-extraction dependency lives here; the error type and handler live in
`lore_audit_api`, keeping chainlit out of the package.
"""

from __future__ import annotations

import os

from chainlit.auth import decode_jwt
from chainlit.auth.cookie import get_token_from_cookies
from fastapi import Request
from lore_audit_api.http.auth import AuditAuthError

from auth import verify_ticket

__all__ = ["AuditAuthError", "chat_auth_dependency"]


def _extract_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization") or request.headers.get(
        "authorization"
    )
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return get_token_from_cookies(request.cookies)


def chat_auth_dependency(request: Request) -> dict[str, str]:
    """Authorize via Chainlit session (cookie/header) or a datacraft HS256 ticket."""
    # DEV ONLY: local demo bypass, off by default. Never set in production.
    if os.environ.get("AUDIT_DEV_ALLOW_ANON") in ("1", "true", "yes"):
        return {"identifier": "dev", "username": "dev"}

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
