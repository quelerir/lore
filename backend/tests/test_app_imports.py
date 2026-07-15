import importlib


def test_app_imports(monkeypatch):
    monkeypatch.setenv("CHAINLIT_JWT_SECRET", "x")
    monkeypatch.setenv("CHAINLIT_JWT_ISSUER", "datacraft")
    monkeypatch.setenv("CHAINLIT_JWT_AUDIENCE", "chainlit")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    app = importlib.import_module("app")
    assert hasattr(app, "handle_message")
