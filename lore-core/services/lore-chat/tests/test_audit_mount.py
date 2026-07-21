from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from lore_audit_api.http.auth import install_audit_auth_handler
from lore_audit_api.http.errors import install_safe_error_handlers

import audit_mount
from audit_auth import chat_auth_dependency


def _fake_audit_app() -> FastAPI:
    """A stand-in for create_audit_app: single route + safe handlers + injected auth."""
    sub = FastAPI()

    @sub.get("/ping", dependencies=[Depends(chat_auth_dependency)])
    def ping():
        return {"ok": True}

    # The real create_audit_app installs both; the auth handler must win for
    # AuditAuthError (more specific in the MRO than the safe Exception catch-all).
    install_safe_error_handlers(sub)
    install_audit_auth_handler(sub)
    return sub


class _Settings:
    audit_db_dsn = "postgresql://u:p@db:5432/lore"
    jwt_secret = "test-secret"


def test_mount_guards_with_auth(monkeypatch):
    app = FastAPI()

    class _User:
        identifier = "u"

    monkeypatch.setattr(audit_mount, "get_settings", lambda: _Settings())
    monkeypatch.setattr(audit_mount, "build_audit_service", lambda **kw: object())
    monkeypatch.setattr(audit_mount, "create_audit_app", lambda **kw: _fake_audit_app())
    # Simulate a valid Chainlit session token (cookie or Bearer header).
    monkeypatch.setattr("audit_auth.decode_jwt", lambda t: _User())
    assert audit_mount.attach_audit_router(app) is True

    client = TestClient(app)
    unauth = client.get("/api/v1/audit/ping")
    assert unauth.status_code == 401
    assert unauth.json()["code"] == "unauthorized"

    ok = client.get("/api/v1/audit/ping", headers={"Authorization": "Bearer good"})
    assert ok.status_code == 200 and ok.json() == {"ok": True}


def test_mount_noop_when_unconfigured(monkeypatch):
    app = FastAPI()

    class _Unconfigured:
        audit_db_dsn = None
        jwt_secret = "x"

    monkeypatch.setattr(audit_mount, "get_settings", lambda: _Unconfigured())
    assert audit_mount.attach_audit_router(app) is False
    assert TestClient(app).get("/api/v1/audit/ping").status_code == 404
