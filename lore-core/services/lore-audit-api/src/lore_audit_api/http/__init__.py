"""HTTP transport surface for audit reads."""

from lore_audit_api.http.auth import AuditAuthError, install_audit_auth_handler
from lore_audit_api.http.contracts import AuditHttpErrorEnvelope
from lore_audit_api.http.errors import (
    install_safe_error_handlers,
    normalize_http_error,
)
from lore_audit_api.http.limits import AuditHttpLimits
from lore_audit_api.http.routes import create_audit_router

__all__ = [
    "AuditAuthError",
    "AuditHttpErrorEnvelope",
    "AuditHttpLimits",
    "create_audit_router",
    "install_audit_auth_handler",
    "install_safe_error_handlers",
    "normalize_http_error",
]
