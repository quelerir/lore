import jwt
import pytest
from fastapi import HTTPException

from audit.auth_dep import require_audit_identity


def test_missing_header_raises_401():
    with pytest.raises(HTTPException) as exc:
        require_audit_identity(None)
    assert exc.value.status_code == 401


def test_invalid_token_raises_401(monkeypatch):
    def _boom(_token):
        raise jwt.InvalidTokenError("bad")

    monkeypatch.setattr("audit.auth_dep.verify_ticket", _boom)
    with pytest.raises(HTTPException) as exc:
        require_audit_identity("Bearer nope")
    assert exc.value.status_code == 401


def test_valid_token_returns_identity(monkeypatch):
    monkeypatch.setattr(
        "audit.auth_dep.verify_ticket", lambda t: {"sub": "u1", "username": "u1"}
    )
    assert require_audit_identity("Bearer good") == {"sub": "u1", "username": "u1"}
