import pytest
from pydantic import ValidationError

from config import ModelProvider, Settings

# Полный набор env для конструирования Settings без файлов.
BASE = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
    "CHAINLIT_JWT_SECRET": "secret",
    "CHAINLIT_JWT_AUDIENCE": "chainlit",
    "CHAINLIT_JWT_ISSUER": "datacraft",
}


def test_required_fields_present(monkeypatch):
    for k, v in BASE.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.database_url.endswith("/db")
    assert s.jwt_secret == "secret"
    assert s.jwt_audience == "chainlit"
    assert s.jwt_issuer == "datacraft"


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
    assert s.toast_database_url is None


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
