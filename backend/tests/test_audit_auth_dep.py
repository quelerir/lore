import pytest

from audit.auth_dep import AuditAuthError, require_audit_identity


class _Req:
    """Minimal stand-in for a Starlette Request (headers + cookies)."""

    def __init__(self, headers=None, cookies=None):
        self.headers = headers or {}
        self.cookies = cookies or {}


class _User:
    def __init__(self, identifier):
        self.identifier = identifier


def test_no_token_raises_auth_error():
    with pytest.raises(AuditAuthError):
        require_audit_identity(_Req())


def test_session_cookie_is_accepted(monkeypatch):
    # Chainlit session: token in the access_token cookie, validated by decode_jwt.
    monkeypatch.setattr("audit.auth_dep.decode_jwt", lambda t: _User("alice"))
    identity = require_audit_identity(_Req(cookies={"access_token": "sess"}))
    assert identity == {"identifier": "alice", "username": "alice"}


def test_datacraft_ticket_header_is_accepted(monkeypatch):
    # Not a Chainlit JWT -> decode_jwt fails -> fall back to verify_ticket.
    def _bad_jwt(_t):
        raise ValueError("not a chainlit jwt")

    monkeypatch.setattr("audit.auth_dep.decode_jwt", _bad_jwt)
    monkeypatch.setattr(
        "audit.auth_dep.verify_ticket", lambda t: {"sub": "u1", "username": "bob"}
    )
    identity = require_audit_identity(_Req(headers={"Authorization": "Bearer tkt"}))
    assert identity == {"identifier": "bob", "username": "bob", "sub": "u1"}


def test_invalid_credentials_raise_auth_error(monkeypatch):
    def _bad_jwt(_t):
        raise ValueError("bad")

    def _bad_ticket(_t):
        raise ValueError("bad")

    monkeypatch.setattr("audit.auth_dep.decode_jwt", _bad_jwt)
    monkeypatch.setattr("audit.auth_dep.verify_ticket", _bad_ticket)
    with pytest.raises(AuditAuthError):
        require_audit_identity(_Req(headers={"Authorization": "Bearer nope"}))
