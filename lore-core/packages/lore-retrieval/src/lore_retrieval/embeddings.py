from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingBackend(Protocol):
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbeddingBackend:
    def __init__(self, model: str, base_url: str, dim: int) -> None:
        from langchain_ollama import OllamaEmbeddings

        self.dim = dim
        self._model = model
        self._client = OllamaEmbeddings(model=model, base_url=base_url)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._client.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._client.embed_query(text)


class Neo4jGraphRagEmbedder:
    """Adapts an EmbeddingBackend to neo4j_graphrag's Embedder interface."""

    def __init__(self, backend: EmbeddingBackend) -> None:
        self._backend = backend

    def embed_query(self, text: str) -> list[float]:
        return self._backend.embed_query(text)
