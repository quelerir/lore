from functools import lru_cache
from pathlib import Path

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
