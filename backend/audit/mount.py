"""Mount the isolated audit sub-app onto the host (Chainlit) FastAPI app."""

from __future__ import annotations

from fastapi import FastAPI

from audit.assembly import build_audit_app
from config import get_settings

AUDIT_MOUNT_PATH = "/api/v1/audit"


def attach_audit_router(app: FastAPI) -> bool:
    """Mount the audit sub-app at /api/v1/audit if configured. True when attached.

    A mounted sub-application keeps its own exception handlers and middleware, so
    the audit safe-error envelope never leaks onto the host app's routes.
    """
    subapp = build_audit_app(get_settings())
    if subapp is None:
        return False
    app.mount(AUDIT_MOUNT_PATH, subapp)
    return True
