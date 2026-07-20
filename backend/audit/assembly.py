"""Wire config into a mounted audit read router. Image reader deferred (no S3)."""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import Depends, FastAPI

from audit.auth_dep import install_audit_auth_handler, require_audit_identity
from audit.http_api.errors import install_safe_error_handlers
from audit.http_api.limits import AuditHttpLimits
from audit.http_api.middleware import AuditHttpMiddleware
from audit.http_api.routes import create_audit_router
from audit.pool import AuditConnectionPool, build_audit_pool
from audit.read_adapters import PostgresRegisteredTableReader
from audit.read_cursor import CursorCodec
from audit.read_repositories import PostgresAuditReadRepository
from audit.read_service import AuditReadService


def _derive_cursor_key(jwt_secret: str) -> bytes:
    """Stable HMAC key for pagination cursors, derived from the existing JWT secret.

    Avoids provisioning a separate secret: the domain-separated hash yields a
    distinct 32-byte key (never equal to the JWT secret) that is stable across
    restarts, which the cursor codec requires.
    """
    return hashlib.sha256(b"audit-cursor-v1|" + jwt_secret.encode("utf-8")).digest()


def build_audit_service(
    settings: Any,
) -> tuple[AuditReadService, AuditConnectionPool] | None:
    """Return (service, pool) or None when the audit DB (Toast instance) is unset."""
    dsn = settings.audit_db_dsn
    if not dsn:
        return None
    pool = build_audit_pool(dsn)
    codec = CursorCodec(_derive_cursor_key(settings.jwt_secret))
    repository = PostgresAuditReadRepository(pool, codec)
    service = AuditReadService(
        repository,
        table_reader=PostgresRegisteredTableReader(pool, codec),
        # image_reader deferred to the S3 phase; source_reader deferred until a
        # source-object loader exists. Both capabilities degrade gracefully.
    )
    return service, pool


def build_audit_router(settings: Any):
    """Return the audit router (default /api/v1/audit prefix), or None if unconfigured."""
    built = build_audit_service(settings)
    if built is None:
        return None
    service, _pool = built
    return create_audit_router(service, AuditHttpLimits())


def build_audit_app(settings: Any) -> FastAPI | None:
    """Build an isolated ASGI sub-app for the audit API, or None if unconfigured.

    Isolation is deliberate: the audit safe-error handlers and middleware live on
    this sub-app only, so mounting it never touches the host (Chainlit) app's own
    error handling. The router is prefix-less; the mount point supplies the path.
    """
    built = build_audit_service(settings)
    if built is None:
        return None
    service, _pool = built
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url="/openapi.json")
    app.include_router(
        create_audit_router(service, AuditHttpLimits(), prefix=""),
        dependencies=[Depends(require_audit_identity)],
    )
    install_safe_error_handlers(app)
    install_audit_auth_handler(app)
    app.add_middleware(AuditHttpMiddleware)
    return app
