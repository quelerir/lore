"""Mount the isolated audit sub-app onto the host (Chainlit) FastAPI app."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.routing import Mount

from audit.assembly import build_audit_app
from config import get_settings

AUDIT_MOUNT_PATH = "/api/v1/audit"


def attach_audit_router(app: FastAPI) -> bool:
    """Mount the audit sub-app at /api/v1/audit if configured. True when attached.

    A mounted sub-application keeps its own exception handlers and middleware, so
    the audit safe-error envelope never leaks onto the host app's routes.

    The mount is inserted at the FRONT of the route table: Chainlit registers a
    catch-all that serves the SPA for unknown paths, and Starlette matches routes
    in order, so appending would let that catch-all shadow /api/v1/audit.
    """
    subapp = build_audit_app(get_settings())
    if subapp is None:
        return False
    app.router.routes.insert(0, Mount(AUDIT_MOUNT_PATH, app=subapp))
    return True
