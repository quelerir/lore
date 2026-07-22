"""Общие фикстуры тестов бэкенда.

baseline-env даёт 4 обязательных поля Settings, чтобы любой потребитель
get_settings() конструировался. Загрузка env-файлов отключается, чтобы
тесты не зависели от локального .env.local разработчика. Кэш get_settings
чистится вокруг каждого теста.
"""

import os

import pytest

import config

# toast.sql_guardrails.ALLOWED_SCHEMA читается из окружения НА ИМПОРТЕ, а guardrail-
# тесты пингуют логику на фиксированном имени схемы. Пинним его до импорта модуля
# (fixture'ы — уже поздно), чтобы тесты не зависели от текущего деплой-дефолта.
os.environ["TOAST_SCHEMA"] = "splitter_toast"

_BASELINE = {
    "CHAINLIT_DB_HOST": "localhost",
    "CHAINLIT_DB_USER": "u",
    "CHAINLIT_DB_PASSWORD": "p",
    "CHAINLIT_DB_NAME": "db",
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
