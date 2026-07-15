import agent


def test_build_agent_returns_streamable(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma3")
    a = agent.build_agent()
    assert hasattr(a, "astream")
