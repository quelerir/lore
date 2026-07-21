from enum import Enum

from pydantic import BaseModel


class LedgerStatus(str, Enum):
    pending = "pending"
    indexing = "indexing"
    ready = "ready"
    failed = "failed"
    superseded = "superseded"


class DerivedIndexRecord(BaseModel):
    run_id: str
    index_version: str
    chunk_schema_version: str
    section_projection_version: str
    embedding_model_version: str
    fulltext_analyzer_version: str
    graph_schema_version: str
    neo4j_server_version: str
    neo4j_graphrag_version: str
    reranker_version: str
    status: LedgerStatus = LedgerStatus.pending
    started_at: str | None = None
    completed_at: str | None = None
    error_summary: str | None = None
