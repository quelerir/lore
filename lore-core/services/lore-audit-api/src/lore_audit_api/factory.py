"""Injected ASGI application factory + read-service assembly for audit reads.

`create_audit_app` builds the mountable/standalone ASGI app. Auth is INJECTED:
the caller passes a FastAPI dependency callable (chat passes cookie+ticket,
standalone passes ticket-only). The package never imports chainlit or airflow.

`build_audit_service` assembles the read service from a DSN + cursor key. It owns
the pool construction so callers only supply configuration values, never wiring.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI

from lore_audit.read_adapters import PostgresRegisteredTableReader
from lore_audit.read_cursor import CursorCodec
from lore_audit.read_repositories import PostgresAuditReadRepository
from lore_audit.read_service import AuditReadService
from lore_audit_api.http.auth import install_audit_auth_handler
from lore_audit_api.http.errors import install_safe_error_handlers
from lore_audit_api.http.limits import AuditHttpLimits
from lore_audit_api.http.middleware import AuditHttpMiddleware
from lore_audit_api.http.routes import create_audit_router
from lore_audit_api.pool import build_audit_pool


def create_audit_app(
    *,
    service: AuditReadService,
    limits: AuditHttpLimits | None = None,
    auth_dependency: Callable[..., Any],
    shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    """Return a library ASGI app with injected service, limits, and auth.

    `auth_dependency` is a FastAPI dependency callable applied to every audit
    route. Identity extraction (cookie/ticket) lives outside this package; only
    the generic safe-error handlers are installed here. The caller installs the
    `AuditAuthError -> 401` handler paired with whatever the dependency raises.
    """

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
    install_audit_auth_handler(app)
    app.include_router(
        create_audit_router(service, limits or AuditHttpLimits()),
        dependencies=[Depends(auth_dependency)],
    )
    app.add_middleware(AuditHttpMiddleware)
    return app


def build_audit_service(
    *,
    dsn: str,
    cursor_key: bytes,
    table_reader: Any = None,
    image_reader: Any = None,
    source_reader: Any = None,
) -> AuditReadService:
    """Assemble the read service from a DSN + cursor key (builds the pool internally).

    The table reader defaults to the Postgres registered-table reader; the image
    and source readers degrade gracefully when unset (the S3/source-loader phases
    fill them in). No config/env import happens here.
    """
    pool = build_audit_pool(dsn)
    codec = CursorCodec(cursor_key)
    repository = PostgresAuditReadRepository(pool, codec)
    if table_reader is None:
        table_reader = PostgresRegisteredTableReader(pool, codec)
    return AuditReadService(
        repository,
        table_reader=table_reader,
        image_reader=image_reader,
        source_reader=source_reader,
    )


__all__ = ["create_audit_app", "build_audit_service"]
