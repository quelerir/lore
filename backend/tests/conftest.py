"""Общие фикстуры тестов бэкенда.

baseline-env даёт 4 обязательных поля Settings, чтобы любой потребитель
get_settings() конструировался. Загрузка env-файлов отключается, чтобы
тесты не зависели от локального .env.local разработчика. Кэш get_settings
чистится вокруг каждого теста.
"""

import pytest

import config

_BASELINE = {
    "DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/db",
    "CHAINLIT_JWT_SECRET": "test-secret-that-is-32-bytes-long!!",
    "CHAINLIT_JWT_AUDIENCE": "chainlit",
    "CHAINLIT_JWT_ISSUER": "datacraft",
}


@pytest.fixture(autouse=True)
def _config_env(monkeypatch):
    # Не читать файлы .env/.env.local в тестах.
    monkeypatch.setitem(config.Settings.model_config, "env_file", None)
    for k, v in _BASELINE.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()
