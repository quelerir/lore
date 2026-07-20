import pytest
from pydantic import ValidationError

from config import ModelProvider, Settings

# Полный набор env для конструирования Settings без файлов.
BASE = {
    "CHAINLIT_DB_HOST": "localhost",
    "CHAINLIT_DB_USER": "u",
    "CHAINLIT_DB_PASSWORD": "p",
    "CHAINLIT_DB_NAME": "db",
    "CHAINLIT_JWT_SECRET": "secret",
    "CHAINLIT_JWT_AUDIENCE": "chainlit",
    "CHAINLIT_JWT_ISSUER": "datacraft",
}


def test_required_fields_present(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.database_url == "postgresql+asyncpg://u:p@localhost:5432/db"
    assert s.jwt_secret == "secret"


def test_missing_required_raises(monkeypatch):
    for k in BASE:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_defaults_applied(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.model_provider is ModelProvider.OPENROUTER
    assert s.openrouter_model == "anthropic/claude-haiku-4.5"
    assert s.openrouter_base_url == "https://openrouter.ai/api/v1"
    assert s.openrouter_api_key is None
    assert s.ollama_model == "gemma3"
    assert s.ollama_base_url == "http://ollama:11434"
    assert s.toast_dsn is None


def test_toast_dsn_assembled(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("TOAST_DB_HOST", "th")
    monkeypatch.setenv("TOAST_DB_USER", "tu")
    monkeypatch.setenv("TOAST_DB_PASSWORD", "tp")
    monkeypatch.setenv("TOAST_DB_NAME", "tn")
    s = Settings(_env_file=None)
    assert s.toast_dsn == "postgresql://tu:tp@th:5432/tn"


def test_password_url_escaped(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("CHAINLIT_DB_PASSWORD", "p@ss/w:rd")
    s = Settings(_env_file=None)
    assert "p%40ss%2Fw%3Ard" in s.database_url


def test_bad_provider_rejected(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MODEL_PROVIDER", "garbage")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_validation_alias_maps_env(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OPENROUTER_API_KEY", "key-123")
    s = Settings(_env_file=None)
    assert s.model_provider is ModelProvider.OLLAMA
    assert s.openrouter_api_key == "key-123"


def test_sql_settings_defaults(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.sql_max_queries == 3
    assert s.sql_candidates_per_round == 2
    assert s.sql_model  # непустой дефолт
