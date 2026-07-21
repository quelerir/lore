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
    payload_by_chunk = {
        c.chunk_id: c.payload_refs[0]["payload_id"]
        for c in chunks
        if c.is_table and c.payload_refs and "payload_id" in c.payload_refs[0]
    }
    kwargs = dict(
        chunk_search=backend,
        graph_expansion=InMemoryGraphExpansion(projection),
        reranker=FakeReranker(),
        resolver=InMemoryEvidenceResolver(chunks),
        table_search=backend,
        sql_runner=FakeSqlRunner(sql_outcomes or {}),
        chat_model=FakeChatModel(chat_responder),
        projection=projection,
        positions={c.chunk_id: c.position for c in chunks},
        text_by_id={c.chunk_id: c.fulltext for c in chunks},
        payload_by_chunk=payload_by_chunk,
        file_key_resolver=FakeFileKeyResolver(file_keys) if file_keys else None,
        tracer=tracer,
    )
    kwargs.update(overrides)
    return RetrievalPipeline(**kwargs)
