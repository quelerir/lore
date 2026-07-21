"""Closed safe error vocabulary returned at the audit read application boundary."""

from __future__ import annotations

_ERROR_MESSAGES = {
    "invalid_request": "audit read request is invalid",
    "invalid_cursor": "audit read cursor is invalid",
    "not_found": "audit read resource was not found",
    "membership_mismatch": "audit read resource membership is invalid",
    "bounds_exceeded": "audit read request exceeds configured bounds",
    "registration_invalid": "audit read payload registration is invalid",
    "capability_unavailable": "audit read capability is unavailable",
    "dependency_timeout": "audit read dependency timed out",
    "read_failed": "audit read failed",
}


class AuditReadError(RuntimeError):
    """Closed safe error returned at the application boundary."""

    def __init__(self, code: str, *, resource: str | None = None) -> None:
        if code not in _ERROR_MESSAGES:
            code = "read_failed"
        self.code = code
        self.resource = resource
        super().__init__(_ERROR_MESSAGES[code])


__all__ = ["AuditReadError"]
