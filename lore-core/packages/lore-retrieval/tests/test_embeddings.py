from lore_retrieval.embeddings import EmbeddingBackend, Neo4jGraphRagEmbedder


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
