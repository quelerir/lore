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


class HttpEmbeddingBackend:
    """bge-m3 served over HTTP (BGEM3 server): ``POST /embed {"texts": [...]}`` →
    ``{"dense_vecs": [[...]], ...}``. Reachable from host AND container over the
    VPN, so it replaces the host-only Ollama path uniformly (removing the
    ``host.docker.internal`` fragility). Produces the SAME 1024-d bge-m3 vectors as
    the Ollama backend (cosine 1.0), so it's drop-in against the existing projection.

    Sync (like the protocol) — the pipeline runs ``embed_query`` off the event loop
    via ``asyncio.to_thread``. One ``httpx.Client`` per instance (kept-alive pool).
    """

    def __init__(self, base_url: str, dim: int = 1024, timeout: float = 30.0) -> None:
        import httpx

        self.dim = dim
        self._url = base_url.rstrip("/") + "/embed"
        self._client = httpx.Client(timeout=timeout)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.post(self._url, json={"texts": texts})
        resp.raise_for_status()
        vecs = resp.json().get("dense_vecs")
        if not isinstance(vecs, list) or len(vecs) != len(texts):
            raise ValueError("embedding endpoint returned no/mismatched dense_vecs")
        return vecs

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


def build_embedder(
    *, endpoint: str, model: str, base_url: str, dim: int
) -> EmbeddingBackend:
    """Pick the embedding backend: HTTP bge-m3 service when ``endpoint`` is set
    (host+container uniform), else Ollama (host-only fallback). Same vectors either
    way, so callers can switch via ``EMBEDDING_ENDPOINT`` without re-projecting."""
    if endpoint:
        return HttpEmbeddingBackend(endpoint, dim)
    return OllamaEmbeddingBackend(model, base_url, dim)


class Neo4jGraphRagEmbedder:
    """Adapts an EmbeddingBackend to neo4j_graphrag's Embedder interface."""

    def __init__(self, backend: EmbeddingBackend) -> None:
        self._backend = backend

    def embed_query(self, text: str) -> list[float]:
        return self._backend.embed_query(text)
