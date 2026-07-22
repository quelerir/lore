"""Assemble a fully offline pipeline from a chunk corpus, in one call.

DRYs the fake wiring the tests and the lore-chat demo repeat. The real pipeline
uses the same ``RetrievalPipeline`` with Neo4j/OpenRouter/toast backends injected
instead of these fakes.
"""
from collections.abc import Callable

from lore_retrieval.fakes import (
    FakeChatModel,
    FakeFileKeyResolver,
    FakeReranker,
    FakeSqlRunner,
    IdentityReranker,
    InMemoryChunkContextLoader,
    InMemoryChunkSearchBackend,
    InMemoryEvidenceResolver,
    InMemoryGraphExpansion,
)
from lore_retrieval.pipeline.graph import RetrievalPipeline
from lore_retrieval.projection_model import build_structural_projection
from lore_retrieval.source import SourceChunk


def build_offline_pipeline(
    chunks: list[SourceChunk],
    *,
    chat_responder: Callable[[str], str] | None = None,
    sql_outcomes: dict | None = None,
    file_keys: dict[str, str] | None = None,
    tracer=None,
    **overrides,
) -> RetrievalPipeline:
    projection = build_structural_projection(chunks)
    backend = InMemoryChunkSearchBackend(chunks)
    kwargs = dict(
        chunk_search=backend,
        graph_expansion=InMemoryGraphExpansion(projection),
        reranker=FakeReranker(),
        resolver=InMemoryEvidenceResolver(chunks),
        table_search=backend,
        sql_runner=FakeSqlRunner(sql_outcomes or {}),
        chat_model=FakeChatModel(chat_responder),
        context_loader=InMemoryChunkContextLoader(chunks),
        file_key_resolver=FakeFileKeyResolver(file_keys) if file_keys else None,
        tracer=tracer,
    )
    kwargs.update(overrides)
    return RetrievalPipeline(**kwargs)


def build_live_pipeline(
    *,
    driver,
    database: str,
    dsn: str,
    embedder,
    chat_model,
    index_version: str,
    file_key_resolver=None,
    sql_runner=None,
    reranker=None,
    **overrides,
) -> RetrievalPipeline:
    """Assemble a production RetrievalPipeline: Neo4j search/expansion + bge-m3
    embedder + lore_core Postgres resolver/file-keys/context-loader + the injected
    ChatModel. Assumes Neo4j is ALREADY projected under ``index_version`` (a
    separate indexing job) — this only queries. P0 has no reranker (identity) and
    no live TOAST binding (empty SqlRunner); both are injectable via overrides.
    Local imports keep the offline factory free of neo4j/asyncpg at import time.
    """
    from lore_retrieval.adapters.context_postgres import PostgresChunkContextLoader
    from lore_retrieval.adapters.evidence_postgres import PostgresEvidenceResolver
    from lore_retrieval.adapters.file_keys import PostgresFileKeyResolver
    from lore_retrieval.adapters.neo4j_backends import (
        Neo4jChunkSearchBackend,
        Neo4jGraphExpansionBackend,
        Neo4jTableSearchBackend,
    )

    kwargs = dict(
        chunk_search=Neo4jChunkSearchBackend(driver, database, index_version, embedder),
        graph_expansion=Neo4jGraphExpansionBackend(driver, database, index_version),
        reranker=reranker or IdentityReranker(),  # P0: no cross-encoder; keep fusion order
        resolver=PostgresEvidenceResolver(dsn),
        table_search=Neo4jTableSearchBackend(driver, database, index_version, embedder),
        sql_runner=sql_runner or FakeSqlRunner({}),  # text-lane citations: no live TOAST
        chat_model=chat_model,
        context_loader=PostgresChunkContextLoader(dsn),
        file_key_resolver=file_key_resolver or PostgresFileKeyResolver(dsn),
        index_version=index_version,
    )
    kwargs.update(overrides)
    return RetrievalPipeline(**kwargs)
