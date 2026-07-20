import jwt
import pytest

from audit.auth_dep import AuditAuthError, require_audit_identity


def test_missing_header_raises_auth_error():
    with pytest.raises(AuditAuthError):
        require_audit_identity(None)


def test_invalid_token_raises_auth_error(monkeypatch):
    def _boom(_token):
        raise jwt.InvalidTokenError("bad")

    monkeypatch.setattr("audit.auth_dep.verify_ticket", _boom)
    with pytest.raises(AuditAuthError):
        require_audit_identity("Bearer nope")


def test_valid_token_returns_identity(monkeypatch):
    monkeypatch.setattr(
        "audit.auth_dep.verify_ticket", lambda t: {"sub": "u1", "username": "u1"}
    )
    assert require_audit_identity("Bearer good") == {"sub": "u1", "username": "u1"}
