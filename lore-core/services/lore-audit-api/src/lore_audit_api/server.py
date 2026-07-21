"""Standalone uvicorn entrypoint for the audit read API (internal2 sidecar).

Ticket-only auth: the sidecar authorizes datacraft HS256 tickets (Bearer header)
and nothing else — no chainlit session cookies (that path belongs to the chat
mount). Run with `uvicorn lore_audit_api.server:app`.
"""

from __future__ import annotations

import jwt
from fastapi import Request

from lore_audit_api.factory import build_audit_service, create_audit_app
from lore_audit_api.http.auth import AuditAuthError
from lore_audit_api.settings import AuditApiSettings


def _bearer_token(request: Request) -> str | None:
    authorization = request.headers.get("Authorization") or request.headers.get(
        "authorization"
    )
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def build_ticket_auth_dependency(settings: AuditApiSettings):
    """A FastAPI dependency that authorizes datacraft HS256 tickets only."""
    require = ["exp", "sub", "aud", "iss"]
    options = {"require": require}
    verify_aud = settings.chainlit_jwt_audience is not None
    verify_iss = settings.chainlit_jwt_issuer is not None

    def require_ticket_identity(request: Request) -> dict[str, str]:
        token = _bearer_token(request)
        if not token:
            raise AuditAuthError("no ticket")
        try:
            payload = jwt.decode(
                token,
                settings.chainlit_jwt_secret,
                algorithms=["HS256"],
                audience=settings.chainlit_jwt_audience,
                issuer=settings.chainlit_jwt_issuer,
                options={
                    **options,
                    "verify_aud": verify_aud,
                    "verify_iss": verify_iss,
                },
            )
        except Exception:
            raise AuditAuthError("invalid ticket") from None
        sub = str(payload["sub"])
        username = str(payload.get("username", sub))
        return {"identifier": username, "username": username, "sub": sub}

    return require_ticket_identity


def build_app() -> "object":
    settings = AuditApiSettings()  # type: ignore[call-arg]
    service = build_audit_service(
        dsn=settings.audit_dsn(),
        cursor_key=settings.cursor_key(),
    )
    return create_audit_app(
        service=service,
        auth_dependency=build_ticket_auth_dependency(settings),
    )


app = build_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
