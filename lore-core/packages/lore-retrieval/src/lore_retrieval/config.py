from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _repo_root() -> Path:
    """Walk up to the single shared repo root (marked by docker-compose.yml/.git)
    so we read ONE root .env, not per-package config files."""
    start = Path(__file__).resolve()
    for parent in [start, *start.parents]:
        if (parent / "docker-compose.yml").exists() or (parent / ".git").exists():
            return parent
    return start.parents[5]  # known depth fallback: …/lore/lore-core/packages/lore-retrieval/src/lore_retrieval


_ROOT = _repo_root()


class Settings(BaseSettings):
    # Reads real env vars first, then the shared root .env / .env.local
    # (RETRIEVAL_NEO4J_* / RETRIEVAL_LORE_CORE_DSN live there, prefix-namespaced).
    model_config = SettingsConfigDict(
        env_prefix="RETRIEVAL_",
        env_file=(str(_ROOT / ".env"), str(_ROOT / ".env.local")),
        env_file_encoding="utf-8",
        # compose passes unset vars as empty strings (${VAR:-}); treat "" as unset
        # so an empty entry never clobbers a default.
        env_ignore_empty=True,
        extra="ignore",
    )

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    lore_core_dsn: str = ""

    # Non-prefixed so the container honors compose's OLLAMA_BASE_URL
    # (host.docker.internal); otherwise it falls back to localhost:11434 — no
    # Ollama there — and every embed connect-refuses (vector_search_failed).
    ollama_base_url: str = Field(
        default="http://localhost:11434", validation_alias="OLLAMA_BASE_URL"
    )
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024

    # Active Neo4j projection the chat queries (a separate indexing job populates
    # it). v2 = full current lore_core corpus (19k chunks); v1 kept in Neo4j as
    # rollback. Override per-env with RETRIEVAL_INDEX_VERSION.
    index_version: str = "v2"

    # --- Chat (OpenRouter) — reuse the SAME shared-root .env vars lore-chat uses
    # (non-prefixed via validation_alias), so we never duplicate the key. ---
    openrouter_api_key: str = Field(default="", validation_alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(
        default="anthropic/claude-haiku-4.5", validation_alias="OPENROUTER_MODEL"
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", validation_alias="OPENROUTER_BASE_URL"
    )
    llm_max_tokens: int | None = Field(default=None, validation_alias="LLM_MAX_TOKENS")

    # Table lane SQL generator (a stronger model than the chat/arbitration model).
    sql_model: str = Field(default="anthropic/claude-sonnet-4.6", validation_alias="SQL_MODEL")
    sql_max_queries: int = Field(default=3, validation_alias="SQL_MAX_QUERIES")
    sql_candidates_per_round: int = Field(default=2, validation_alias="SQL_CANDIDATES_PER_ROUND")

    # --- lore_core corpus lives on the TOAST/audit instance; reuse those
    # components to build the read-side DSN when RETRIEVAL_LORE_CORE_DSN is unset. ---
    toast_db_host: str | None = Field(default=None, validation_alias="TOAST_DB_HOST")
    toast_db_port: int = Field(default=5432, validation_alias="TOAST_DB_PORT")
    toast_db_user: str | None = Field(default=None, validation_alias="TOAST_DB_USER")
    toast_db_password: str | None = Field(default=None, validation_alias="TOAST_DB_PASSWORD")
    toast_db_name: str | None = Field(default=None, validation_alias="TOAST_DB_NAME")

    @property
    def lore_core_effective_dsn(self) -> str:
        """Read-side DSN for lore_core.chunks: explicit RETRIEVAL_LORE_CORE_DSN
        wins, else derived from the TOAST_DB_* components (same instance as audit).
        Empty string when neither is configured."""
        if self.lore_core_dsn:
            return self.lore_core_dsn
        if all([self.toast_db_host, self.toast_db_user, self.toast_db_password, self.toast_db_name]):
            user = quote(self.toast_db_user or "", safe="")
            pwd = quote(self.toast_db_password or "", safe="")
            return f"postgresql://{user}:{pwd}@{self.toast_db_host}:{self.toast_db_port}/{self.toast_db_name}"
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
