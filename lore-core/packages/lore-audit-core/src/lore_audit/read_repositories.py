"""Thin re-export shim — all public names now live in lore_audit.repository.

This module is preserved verbatim so every existing ``from lore_audit.read_repositories
import <anything>`` (incl. ``PostgresAuditReadRepository``) continues to work unchanged.
"""

from lore_audit.repository import (  # noqa: F401
    AuditCoreReadRepository,
    PayloadReadResult,
    PostgresAuditReadRepository,
    RegisteredPayloadToken,
    RegisteredSourceToken,
    SourceReadResult,
)

__all__ = [
    "AuditCoreReadRepository",
    "PayloadReadResult",
    "PostgresAuditReadRepository",
    "RegisteredPayloadToken",
    "RegisteredSourceToken",
    "SourceReadResult",
]
