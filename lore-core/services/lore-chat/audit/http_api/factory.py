"""Injected ASGI application factory for audit reads."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from audit.http_api.errors import install_safe_error_handlers
from audit.http_api.limits import AuditHttpLimits
from audit.http_api.middleware import AuditHttpMiddleware
from audit.http_api.routes import create_audit_router
from lore_audit.read_service import AuditReadService


def create_audit_app(
    service: AuditReadService,
    limits: AuditHttpLimits | None = None,
    *,
    shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    """Return a library ASGI app with injected service and server-owned limits."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        try:
            yield
        finally:
            if shutdown is not None:
                shutdown()

    app = FastAPI(
        title="Lore Splitter Audit Read API",
        description="Bounded read-only inspection facade for persisted splitter evidence.",
        version="1.3.0",
        lifespan=lifespan,
    )
    install_safe_error_handlers(app)
    app.include_router(create_audit_router(service, limits or AuditHttpLimits()))
    app.add_middleware(AuditHttpMiddleware)
    return app


__all__ = ["create_audit_app"]
