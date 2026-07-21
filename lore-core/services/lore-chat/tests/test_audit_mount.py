from typing import Any

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from lore_audit_api.http.auth import install_audit_auth_handler
from lore_audit_api.http.errors import install_safe_error_handlers

import audit_mount
from audit_auth import chat_auth_dependency


class _FakeService:
    """Duck-typed audit service stub — satisfies create_audit_app's duck-typed service arg.

    Every method call returns a Falsy sentinel so the router can be built and
    mounted without hitting a real database; requests that would exercise service
    methods are stopped by auth before they reach the service layer.
    """

    def __getattr__(self, name: str) -> Any:
        def _noop(*args: Any, **kwargs: Any) -> None:  # pragma: no cover
            raise AssertionError(f"service.{name} called unexpectedly in auth test")

        return _noop


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


def test_real_create_audit_app_with_prefix_empty_enforces_auth(monkeypatch):
    """Regression: create_audit_app MUST accept prefix="" without TypeError.

    Previously `create_audit_app` had no `prefix` parameter but `audit_mount.py`
    called it with `prefix=""`, causing a TypeError at chat startup.  This test
    calls the REAL `create_audit_app` (not a stub) with `prefix=""` and confirms:
      1. No TypeError is raised during app construction.
      2. Auth is enforced — unauthenticated GET /api/v1/audit/files returns 401.

    `build_audit_service` is monkeypatched to avoid a real DB; all other wiring
    (create_audit_app, router, error/auth handlers, middleware) is real.
    """
    app = FastAPI()

    monkeypatch.setattr(audit_mount, "get_settings", lambda: _Settings())
    # Inject a fake service so no real DB connection is attempted.
    monkeypatch.setattr(audit_mount, "build_audit_service", lambda **kw: _FakeService())
    # Do NOT monkeypatch create_audit_app — exercise the real seam.

    result = audit_mount.attach_audit_router(app)
    assert result is True, "audit router should attach when DSN is configured"

    client = TestClient(app, raise_server_exceptions=True)
    response = client.get("/api/v1/audit/files")
    assert response.status_code == 401, (
        f"Expected 401 Unauthorized, got {response.status_code}: {response.text}"
    )
