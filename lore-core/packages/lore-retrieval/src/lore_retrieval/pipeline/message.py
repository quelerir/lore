"""Build the chat message payload from a pipeline result.

The lore-chat LangGraph ``cite`` node attaches this metadata to the assistant
message (``cl.Message(content=answer, metadata=to_message_metadata(result))``).
``citations`` is the snake_case shape the frontend's ``extractCitations`` reads.
Debug fields are gated so they never leak into the normal transcript.
"""
from lore_retrieval.contracts import PipelineResult


def to_message_metadata(result: PipelineResult, *, include_debug: bool = False) -> dict:
    metadata: dict = {"citations": [c.model_dump() for c in result.citations]}
    if include_debug:
        metadata["debug"] = {
            "note": result.decision.note,
            "degradations": result.degradations,
            "groups": len(result.groups),
            "sql_results": len(result.sql_results),
        }
    return metadata
