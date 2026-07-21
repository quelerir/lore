"""Mount the canonical lore-audit-api ASGI app onto the host (Chainlit) app.

Thin chat-side wiring: derive the DSN + cursor key from the chat's own settings,
build the read service via the package factory, and inject the chat cookie+ticket
auth dependency. A mounted sub-app keeps its own middleware/handlers, so the audit
safe-error envelope never leaks onto the chat's routes. No-op (returns False) when
the audit DB (Toast instance) is unconfigured, so the chat runs unchanged.
"""

from __future__ import annotations

import hashlib

from fastapi import FastAPI
from lore_audit_api.factory import build_audit_service, create_audit_app
from starlette.routing import Mount

from audit_auth import chat_auth_dependency
from config import get_settings

AUDIT_MOUNT_PATH = "/api/v1/audit"


def _derive_cursor_key(jwt_secret: str) -> bytes:
    """Stable, domain-separated 32-byte HMAC key for pagination cursors.

    Derived from the existing JWT secret so no separate secret is provisioned;
    the prefix keeps it distinct from the raw secret and stable across restarts,
    which the cursor codec requires. Matches the standalone sidecar derivation.
    """
    return hashlib.sha256(b"audit-cursor-v1|" + jwt_secret.encode("utf-8")).digest()


def attach_audit_router(app: FastAPI) -> bool:
    """Mount the audit sub-app at /api/v1/audit if configured. True when attached.

    The mount is inserted at the FRONT of the route table: Chainlit registers a
    catch-all that serves the SPA for unknown paths, and Starlette matches routes
    in order, so appending would let that catch-all shadow /api/v1/audit.
    """
    settings = get_settings()
    dsn = settings.audit_db_dsn
    if not dsn:
        return False
    service = build_audit_service(
        dsn=dsn,
        cursor_key=_derive_cursor_key(settings.jwt_secret),
    )
    # prefix="" — the Mount below supplies /api/v1/audit, so the router must be
    # prefix-less to avoid a doubled /api/v1/audit/api/v1/audit.
    audit_app = create_audit_app(
        service=service,
        auth_dependency=chat_auth_dependency,
        prefix="",
    )
    app.router.routes.insert(0, Mount(AUDIT_MOUNT_PATH, app=audit_app))
    return True
