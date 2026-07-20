"""Auth dependency for the audit router — reuses the chat's HS256 ticket."""

from __future__ import annotations

import jwt
from fastapi import Header, HTTPException

from auth import verify_ticket


def require_audit_identity(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Validate the same Bearer ticket the chat frontend already carries."""
    if not authorization:
        raise HTTPException(status_code=401, detail="missing authorization")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        return verify_ticket(token)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="invalid token") from None
