from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from audit.auth_dep import install_audit_auth_handler, require_audit_identity
from audit.http_api.errors import install_safe_error_handlers
from audit.mount import attach_audit_router


def _fake_subapp() -> FastAPI:
    """A stand-in for build_audit_app: prefix-less router + safe handlers + auth."""
    sub = FastAPI()
    router = APIRouter()

    @router.get("/ping")
    def ping():
        return {"ok": True}

    sub.include_router(router, dependencies=[Depends(require_audit_identity)])
    # Safe handlers register catch-alls for Exception/StarletteHTTPException; the
    # auth handler must still win for AuditAuthError (more specific in the MRO).
    install_safe_error_handlers(sub)
    install_audit_auth_handler(sub)
    return sub


def test_mount_guards_with_auth(monkeypatch):
    app = FastAPI()
    monkeypatch.setattr("audit.mount.build_audit_app", lambda s: _fake_subapp())
    monkeypatch.setattr("audit.mount.get_settings", lambda: object())
    monkeypatch.setattr(
        "audit.auth_dep.verify_ticket", lambda t: {"sub": "u", "username": "u"}
    )
    assert attach_audit_router(app) is True

    client = TestClient(app)
    unauth = client.get("/api/v1/audit/ping")
    assert unauth.status_code == 401
    assert unauth.json()["code"] == "unauthorized"

    ok = client.get("/api/v1/audit/ping", headers={"Authorization": "Bearer good"})
    assert ok.status_code == 200 and ok.json() == {"ok": True}


def test_mount_noop_when_unconfigured(monkeypatch):
    app = FastAPI()
    monkeypatch.setattr("audit.mount.build_audit_app", lambda s: None)
    monkeypatch.setattr("audit.mount.get_settings", lambda: object())
    assert attach_audit_router(app) is False
    assert TestClient(app).get("/api/v1/audit/ping").status_code == 404
