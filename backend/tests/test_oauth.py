import asyncio
import importlib

import chainlit as cl


def _app(monkeypatch):
    monkeypatch.setenv("CHAINLIT_JWT_SECRET", "x")
    monkeypatch.setenv("CHAINLIT_JWT_ISSUER", "datacraft")
    monkeypatch.setenv("CHAINLIT_JWT_AUDIENCE", "chainlit")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    return importlib.import_module("app")


def test_oauth_user_maps_authentik_userinfo(monkeypatch):
    app = _app(monkeypatch)
    default = cl.User(identifier="alice")
    raw = {
        "sub": "alice",
        "preferred_username": "alice",
        "email": "alice@example.com",
        "name": "Alice Doe",
    }
    user = asyncio.run(app.oauth_user("generic", "token", raw, default))
    assert user is not None
    assert user.identifier == "alice"
    assert user.metadata["provider"] == "authentik"
    assert user.metadata["email"] == "alice@example.com"
    assert user.metadata["name"] == "Alice Doe"


def test_oauth_user_falls_back_to_default_identifier(monkeypatch):
    app = _app(monkeypatch)
    default = cl.User(identifier="fallback-id")
    user = asyncio.run(app.oauth_user("generic", "token", {}, default))
    assert user is not None
    assert user.identifier == "fallback-id"
