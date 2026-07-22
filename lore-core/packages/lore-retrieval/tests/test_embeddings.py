import pytest

from lore_retrieval.embeddings import (
    EmbeddingBackend,
    HttpEmbeddingBackend,
    Neo4jGraphRagEmbedder,
    OllamaEmbeddingBackend,
    build_embedder,
)


class FakeBackend:
    dim = 3

    def embed_documents(self, texts):
        return [[float(len(t)), 0.0, 1.0] for t in texts]

    def embed_query(self, text):
        return [float(len(text)), 0.0, 1.0]


def test_backend_satisfies_protocol():
    b = FakeBackend()
    assert isinstance(b, EmbeddingBackend)


def test_graphrag_embedder_delegates_query():
    embedder = Neo4jGraphRagEmbedder(FakeBackend())
    assert embedder.embed_query("abcd") == [4.0, 0.0, 1.0]


class _FakeResp:
    def __init__(self, vecs):
        self._vecs = vecs

    def raise_for_status(self):
        return None

    def json(self):
        return {"dense_vecs": self._vecs, "lexical_weights": None, "colbert_vecs": None}


class _FakeClient:
    def __init__(self):
        self.calls = []

    def post(self, url, json):
        self.calls.append((url, json))
        n = len(json["texts"])
        return _FakeResp([[float(i)] * 3 for i in range(n)])


def test_http_backend_satisfies_protocol_and_parses_dense_vecs():
    b = HttpEmbeddingBackend("http://svc:8340/", dim=3)
    b._client = _FakeClient()
    assert isinstance(b, EmbeddingBackend)
    assert b.embed_documents(["a", "b"]) == [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]
    assert b.embed_query("q") == [0.0, 0.0, 0.0]
    # trailing slash trimmed, single /embed path
    assert b._client.calls[-1][0] == "http://svc:8340/embed"


def test_http_backend_rejects_mismatched_dense_vecs():
    b = HttpEmbeddingBackend("http://svc:8340", dim=3)

    class _Bad(_FakeClient):
        def post(self, url, json):
            return _FakeResp([[1.0, 2.0, 3.0]])  # 1 vec for 2 texts

    b._client = _Bad()
    with pytest.raises(ValueError):
        b.embed_documents(["a", "b"])


def test_build_embedder_selects_http_or_ollama():
    http = build_embedder(
        endpoint="http://svc:8340", model="bge-m3",
        base_url="http://localhost:11434", dim=1024,
    )
    assert isinstance(http, HttpEmbeddingBackend)
    ollama = build_embedder(
        endpoint="", model="bge-m3", base_url="http://localhost:11434", dim=1024,
    )
    assert isinstance(ollama, OllamaEmbeddingBackend)
