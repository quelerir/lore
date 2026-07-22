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


def test_ollama_base_url_reads_non_prefixed_env(monkeypatch):
    """compose sets the NON-prefixed OLLAMA_BASE_URL (host.docker.internal) so the
    container reaches host Ollama; the setting must honor it, like OPENROUTER_*.
    Without it, the container falls back to localhost:11434 (no Ollama there) and
    every embed_query connect-refuses -> vector_search_failed / ConnectionError."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    get_settings.cache_clear()
    s = get_settings()
    assert s.ollama_base_url == "http://host.docker.internal:11434"
