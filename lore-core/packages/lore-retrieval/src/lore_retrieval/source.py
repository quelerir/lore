import json

from pydantic import BaseModel


class SourceChunk(BaseModel):
    chunk_id: str
    document_id: str
    run_id: str
    chunk_type: str
    position: int
    heading_path: tuple[str, ...]
    vector_text: str
    fulltext: str
    vector_text_hash: str
    fulltext_hash: str

    @property
    def is_table(self) -> bool:
        return self.chunk_type == "table_payload"


def row_to_source_chunk(row: dict) -> SourceChunk:
    coords = row.get("coordinates") or {}
    if isinstance(coords, str):
        coords = json.loads(coords)
    heading = tuple(coords.get("heading_path") or ())
    run_id = row["run_id"]
    return SourceChunk(
        chunk_id=row["chunk_id"],
        # A processing_run maps to one source document; run_id is the spike
        # document boundary. P1 may join processing_runs -> logical_file_key
        # for a cross-run-stable document_id.
        document_id=run_id,
        run_id=run_id,
        chunk_type=row["chunk_type"],
        position=row["ordinal"],
        heading_path=heading,
        vector_text=row["vector_text"],
        fulltext=row["fulltext"],
        vector_text_hash=row["vector_text_hash"],
        fulltext_hash=row["fulltext_hash"],
    )


async def fetch_chunks(
    dsn: str, *, run_id: str | None = None, limit: int = 500
) -> list[SourceChunk]:
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("BEGIN TRANSACTION READ ONLY")
        where = "WHERE run_id = $1" if run_id else ""
        args = [run_id, limit] if run_id else [limit]
        limit_pos = "$2" if run_id else "$1"
        rows = await conn.fetch(
            f"""
            SELECT chunk_id, run_id::text AS run_id, ordinal, chunk_type,
                   coordinates, vector_text, fulltext,
                   vector_text_hash, fulltext_hash
            FROM lore_core.chunks
            {where}
            ORDER BY run_id, ordinal
            LIMIT {limit_pos}
            """,
            *args,
        )
        await conn.execute("COMMIT")
    finally:
        await conn.close()

    return [row_to_source_chunk(dict(r)) for r in rows]
