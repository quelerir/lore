"""Единый реестр переменных окружения бэкенда.

Поля, которые читает наш Python, — обязательные или с дефолтами. Поля с
пометкой «читает Chainlit» существуют только для реестра: функционально их
читает сам фреймворк из окружения. Значения берутся из окружения (compose)
и опциональных файлов .env / .env.local (см. приоритет ниже).
"""

from enum import Enum
from functools import lru_cache
from urllib.parse import quote

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def build_dsn(scheme: str, user: str, password: str,
              host: str, port: int, name: str) -> str:
    """Собрать DSN, экранируя логин и пароль (спецсимволы в URL, включая '/')."""
    return (
        f"{scheme}://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{name}"
    )


class ModelProvider(str, Enum):
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
        # compose передаёт незаданные переменные пустыми строками
        # (`${VAR:-}`) — считаем их незаданными, иначе '' затирает дефолты
        # и из пяти пустых TOAST_DB_* собирается мусорный DSN.
        env_ignore_empty=True,
        # Порядок приоритета файлов (побеждает последний): .env → .env.local.
        # Реальные переменные окружения (compose) важнее любого файла.
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
    )

    # --- Chainlit data layer (компоненты; DSN собирается свойством) ---
    chainlit_db_host: str = Field(validation_alias="CHAINLIT_DB_HOST")
    chainlit_db_port: int = Field(default=5432, validation_alias="CHAINLIT_DB_PORT")
    chainlit_db_user: str = Field(validation_alias="CHAINLIT_DB_USER")
    chainlit_db_password: str = Field(validation_alias="CHAINLIT_DB_PASSWORD")
    chainlit_db_name: str = Field(validation_alias="CHAINLIT_DB_NAME")

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
    # Явный предел токенов ответа для OpenRouter-моделей: без него OpenRouter
    # резервирует ПОЛНОЕ окно вывода модели (напр. 65536 у sonnet) и отклоняет
    # запрос с 402, если кредитов меньше резерва. Ответы графа/агента короткие.
    llm_max_tokens: int = Field(default=2000, validation_alias="LLM_MAX_TOKENS")
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

    # --- Toast БД для SQL-инструмента (компоненты; фича-флаг) ---
    toast_db_host: str | None = Field(default=None, validation_alias="TOAST_DB_HOST")
    toast_db_port: int = Field(default=5432, validation_alias="TOAST_DB_PORT")
    toast_db_user: str | None = Field(default=None, validation_alias="TOAST_DB_USER")
    toast_db_password: str | None = Field(
        default=None, validation_alias="TOAST_DB_PASSWORD"
    )
    toast_db_name: str | None = Field(default=None, validation_alias="TOAST_DB_NAME")

    # --- SQL-демо: таблица и описания для профиля «SQL (демо)» (demo-ветка) ---
    sql_demo_table: str = Field(
        default="toast_tbl_ec48a6d52d16ab405f95",
        validation_alias="SQL_DEMO_TABLE",
    )
    sql_demo_desc_vector: str = Field(
        default="юристы Adventum, ФИО и должности",
        validation_alias="SQL_DEMO_DESC_VECTOR",
    )
    sql_demo_desc_full: str = Field(
        default=(
            "Table payload: Лист1 A15:R16. Реестр юристов: ФИО, должность, email."
        ),
        validation_alias="SQL_DEMO_DESC_FULL",
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

    @property
    def database_url(self) -> str:
        """DSN Chainlit data-layer (SQLAlchemy async)."""
        return build_dsn(
            "postgresql+asyncpg", self.chainlit_db_user, self.chainlit_db_password,
            self.chainlit_db_host, self.chainlit_db_port, self.chainlit_db_name,
        )

    @property
    def toast_dsn(self) -> str | None:
        """DSN Toast-БД (asyncpg). None, если компоненты заданы не полностью."""
        host, user = self.toast_db_host, self.toast_db_user
        password, name = self.toast_db_password, self.toast_db_name
        if host is None or user is None or password is None or name is None:
            return None
        return build_dsn("postgresql", user, password, host,
                         self.toast_db_port, name)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
