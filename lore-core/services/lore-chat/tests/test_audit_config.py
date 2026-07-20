from config import Settings

# Minimal required env to construct Settings without .env files.
BASE = {
    "CHAINLIT_DB_HOST": "localhost",
    "CHAINLIT_DB_USER": "u",
    "CHAINLIT_DB_PASSWORD": "p",
    "CHAINLIT_DB_NAME": "db",
    "CHAINLIT_JWT_SECRET": "secret",
    "CHAINLIT_JWT_AUDIENCE": "chainlit",
    "CHAINLIT_JWT_ISSUER": "datacraft",
}


def _base(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)


def test_audit_dsn_mirrors_toast(monkeypatch):
    # Audit reads the same instance as Toast (schema lore_core); no separate env.
    _base(monkeypatch)
    monkeypatch.setenv("TOAST_DB_HOST", "db")
    monkeypatch.setenv("TOAST_DB_USER", "tu")
    monkeypatch.setenv("TOAST_DB_PASSWORD", "tp")
    monkeypatch.setenv("TOAST_DB_NAME", "lore")
    s = Settings(_env_file=None)
    assert s.audit_db_dsn == "postgresql://tu:tp@db:5432/lore"
    assert s.audit_db_dsn == s.toast_dsn


def test_audit_dsn_none_without_db(monkeypatch):
    _base(monkeypatch)
    for k in ("TOAST_DB_HOST", "TOAST_DB_USER", "TOAST_DB_PASSWORD", "TOAST_DB_NAME"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.audit_db_dsn is None
