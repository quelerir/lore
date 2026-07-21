"""SQL column strings and sort constants for the audit read repository."""

from __future__ import annotations

_RUN_COLUMNS = (
    "run_id::text, logical_file_key, status, source_content_hash, config_hash, "
    "claimed_at, finished_at, chunk_count, payload_count, warning_count, error_count"
)
_QUALIFIED_RUN_COLUMNS = (
    "pr.run_id::text, pr.logical_file_key, pr.status, pr.source_content_hash, "
    "pr.config_hash, pr.claimed_at, pr.finished_at, pr.chunk_count, pr.payload_count, "
    "pr.warning_count, pr.error_count"
)
_CHUNK_COLUMNS = (
    "chunk_id, run_id::text, ordinal, pipeline_type, chunk_type, vector_text, fulltext, "
    "display_text, coordinates, payload_refs, content_signature, vector_text_hash, fulltext_hash"
)
_DIAGNOSTIC_SORT = "origin,coalesce(diagnostic_key,''),diagnostic_id"

__all__ = [
    "_CHUNK_COLUMNS",
    "_DIAGNOSTIC_SORT",
    "_QUALIFIED_RUN_COLUMNS",
    "_RUN_COLUMNS",
]
