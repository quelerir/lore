from lore_retrieval.config import get_settings


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_NEO4J_URI", "neo4j+s://example:7687")
    monkeypatch.setenv("RETRIEVAL_NEO4J_USER", "neo4j")
    monkeypatch.setenv("RETRIEVAL_NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("RETRIEVAL_LORE_CORE_DSN", "postgresql://ro@db/loreagent_test")
    get_settings.cache_clear()
    s = get_settings()
    assert s.neo4j_uri == "neo4j+s://example:7687"
    assert s.embedding_model == "bge-m3"
    assert s.embedding_dim == 1024
