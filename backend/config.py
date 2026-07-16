"""Единый реестр переменных окружения бэкенда.

Поля, которые читает наш Python, — обязательные или с дефолтами. Поля с
пометкой «читает Chainlit» существуют только для реестра: функционально их
читает сам фреймворк из окружения. Значения берутся из окружения (compose)
и опциональных файлов .env / .env.local (см. приоритет ниже).
"""

from enum import Enum
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelProvider(str, Enum):
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        # Порядок приоритета файлов (побеждает последний): .env → .env.local.
        # Реальные переменные окружения (compose) важнее любого файла.
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
    )

    # --- Chainlit data layer (читает app.py) ---
    database_url: str = Field(validation_alias="DATABASE_URL")

    # --- JWT-тикеты datacraft (читает auth.py) ---
    jwt_secret: str = Field(validation_alias="CHAINLIT_JWT_SECRET")
    jwt_audience: str = Field(validation_alias="CHAINLIT_JWT_AUDIENCE")
    jwt_issuer: str = Field(validation_alias="CHAINLIT_JWT_ISSUER")

    # --- Модель / провайдер (читает agents/base.py) ---
    model_provider: ModelProvider = Field(
        default=ModelProvider.OPENROUTER, validation_alias="MODEL_PROVIDER"
    )
    openrouter_model: str = Field(
        default="anthropic/claude-haiku-4.5", validation_alias="OPENROUTER_MODEL"
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias="OPENROUTER_BASE_URL",
    )
    openrouter_api_key: str | None = Field(
        default=None, validation_alias="OPENROUTER_API_KEY"
    )
    ollama_model: str = Field(default="gemma3", validation_alias="OLLAMA_MODEL")
    ollama_base_url: str = Field(
        default="http://ollama:11434", validation_alias="OLLAMA_BASE_URL"
    )

    # --- SQL-инструмент (отдельная «умная» модель через OpenRouter) ---
    sql_model: str = Field(
        default="anthropic/claude-sonnet-4.6", validation_alias="SQL_MODEL"
    )
    sql_max_queries: int = Field(default=3, validation_alias="SQL_MAX_QUERIES")
    sql_candidates_per_round: int = Field(
        default=2, validation_alias="SQL_CANDIDATES_PER_ROUND"
    )

    # --- TOAST-таблицы (DSN для SQL-инструмента; фича-флаг) ---
    toast_database_url: str | None = Field(
        default=None, validation_alias="TOAST_DATABASE_URL"
    )

    # --- OAuth generic: CLIENT_ID читает app.py, остальное — Chainlit ---
    oauth_generic_client_id: str | None = Field(
        default=None, validation_alias="OAUTH_GENERIC_CLIENT_ID"
    )

    # --- Passthrough: читает сам Chainlit, здесь — для единого реестра.
    # Имена полей совпадают с env (без учёта регистра), alias не нужен. ---
    chainlit_auth_secret: str | None = None
    chainlit_url: str | None = None
    oauth_generic_client_secret: str | None = None
    oauth_generic_auth_url: str | None = None
    oauth_generic_token_url: str | None = None
    oauth_generic_user_info_url: str | None = None
    oauth_generic_scopes: str | None = None
    oauth_generic_user_identifier: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
