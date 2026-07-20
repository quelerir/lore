"""Optional HTTP transport surface for audit reads."""

from audit.http_api.contracts import AuditHttpErrorEnvelope
from audit.http_api.errors import (
    install_safe_error_handlers,
    normalize_http_error,
)
from audit.http_api.factory import create_audit_app
from audit.http_api.limits import AuditHttpLimits
from audit.http_api.routes import create_audit_router

# Note: runtime.py (create_airflow_audit_app) is intentionally NOT vendored — it is
# the Airflow-coupled composition path. This monolith uses create_audit_router/app.

__all__ = [
    "AuditHttpErrorEnvelope",
    "AuditHttpLimits",
    "create_audit_app",
    "create_audit_router",
    "install_safe_error_handlers",
    "normalize_http_error",
]
