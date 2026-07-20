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


def test_audit_dsn_falls_back_to_toast(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setenv("AUDIT_CURSOR_KEY", "0123456789abcdef")
    monkeypatch.setenv("TOAST_DB_HOST", "db")
    monkeypatch.setenv("TOAST_DB_USER", "tu")
    monkeypatch.setenv("TOAST_DB_PASSWORD", "tp")
    monkeypatch.setenv("TOAST_DB_NAME", "lore")
    s = Settings(_env_file=None)
    assert s.audit_cursor_key == "0123456789abcdef"
    assert s.audit_db_dsn == "postgresql://tu:tp@db:5432/lore"


def test_audit_dsn_prefers_explicit_audit_db(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setenv("AUDIT_CURSOR_KEY", "0123456789abcdef")
    monkeypatch.setenv("TOAST_DB_HOST", "toast")
    monkeypatch.setenv("TOAST_DB_USER", "tu")
    monkeypatch.setenv("TOAST_DB_PASSWORD", "tp")
    monkeypatch.setenv("TOAST_DB_NAME", "toastdb")
    monkeypatch.setenv("AUDIT_DB_HOST", "audit-host")
    monkeypatch.setenv("AUDIT_DB_NAME", "lore_core_db")
    s = Settings(_env_file=None)
    # host/name from AUDIT_*, user/password fall back to TOAST_*.
    assert s.audit_db_dsn == "postgresql://tu:tp@audit-host:5432/lore_core_db"


def test_audit_dsn_none_without_db(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setenv("AUDIT_CURSOR_KEY", "0123456789abcdef")
    for k in ("TOAST_DB_HOST", "TOAST_DB_USER", "TOAST_DB_PASSWORD", "TOAST_DB_NAME",
              "AUDIT_DB_HOST", "AUDIT_DB_USER", "AUDIT_DB_PASSWORD", "AUDIT_DB_NAME"):
        monkeypatch.delenv(k, raising=False)
    s = Settings(_env_file=None)
    assert s.audit_db_dsn is None
