"""ChunkContextLoader over the lore_core Postgres read side.

Loads the source rows for a bounded set of already-retrieved chunk ids
(`WHERE chunk_id = ANY(...)`), so the pipeline can derive per-query maps
(position / text / heading path / payloads) without ever holding the whole
corpus. Thin asyncpg wrapper reusing ``row_to_source_chunk``.
"""
from lore_retrieval.source import SourceChunk, row_to_source_chunk


class PostgresChunkContextLoader:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def load(self, chunk_ids: list[str]) -> list[SourceChunk]:
        if not chunk_ids:
            return []
        import asyncpg

        conn = await asyncpg.connect(self._dsn)
        try:
            async with conn.transaction(readonly=True):
                rows = await conn.fetch(
                    """
                    SELECT chunk_id, run_id::text AS run_id, ordinal, chunk_type,
                           coordinates, vector_text, fulltext, display_text, payload_refs,
                           vector_text_hash, fulltext_hash
                    FROM lore_core.chunks
                    WHERE chunk_id = ANY($1::text[])
                    """,
                    chunk_ids,
                )
        finally:
            await conn.close()
        return [row_to_source_chunk(dict(r)) for r in rows]
