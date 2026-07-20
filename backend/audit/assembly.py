"""Wire config into a mounted audit read router. Image reader deferred (no S3)."""

from __future__ import annotations

from typing import Any

from audit.http_api.limits import AuditHttpLimits
from audit.http_api.routes import create_audit_router
from audit.pool import AuditConnectionPool, build_audit_pool
from audit.read_adapters import PostgresRegisteredTableReader
from audit.read_cursor import CursorCodec
from audit.read_repositories import PostgresAuditReadRepository
from audit.read_service import AuditReadService


def build_audit_service(
    settings: Any,
) -> tuple[AuditReadService, AuditConnectionPool] | None:
    """Return (service, pool) or None when the audit DB/cursor key is not configured."""
    dsn = settings.audit_db_dsn
    key = settings.audit_cursor_key
    if not dsn or not key:
        return None
    pool = build_audit_pool(dsn)
    codec = CursorCodec(key.encode("utf-8"))
    repository = PostgresAuditReadRepository(pool, codec)
    service = AuditReadService(
        repository,
        manifest_target_cap=settings.audit_manifest_target_cap,
        table_reader=PostgresRegisteredTableReader(pool, codec),
        # image_reader deferred to the S3 phase; source_reader deferred until a
        # source-object loader exists. Both capabilities degrade gracefully.
    )
    return service, pool


def build_audit_router(settings: Any):
    """Return a mounted audit router, or None when audit is not configured."""
    built = build_audit_service(settings)
    if built is None:
        return None
    service, _pool = built
    return create_audit_router(service, AuditHttpLimits())
