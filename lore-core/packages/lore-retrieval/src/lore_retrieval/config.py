from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Package root (…/lore-retrieval): src/lore_retrieval/config.py -> parents[2].
_PKG_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Reads real env vars first, then a gitignored .env / .env.local in the
    # package root (put RETRIEVAL_NEO4J_* / RETRIEVAL_LORE_CORE_DSN there).
    model_config = SettingsConfigDict(
        env_prefix="RETRIEVAL_",
        env_file=(str(_PKG_ROOT / ".env"), str(_PKG_ROOT / ".env.local")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    neo4j_database: str = "neo4j"

    lore_core_dsn: str = ""

    ollama_base_url: str = "http://localhost:11434"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
