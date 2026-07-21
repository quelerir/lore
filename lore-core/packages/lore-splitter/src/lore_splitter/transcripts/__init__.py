"""Airflow-independent contracts and parsing for MyMeet transcripts."""

# NOTE(task-1): trimmed — lane and rendering impl modules arrive in later tasks.
# Restore full exports when transcripts/lane.py, transcripts/rendering.py are added.
from lore_splitter.transcripts.contracts import (
    DiscardedOccurrence,
    DiscardReason,
    InternalBoundary,
    LaneResult,
    ParsedTranscript,
    ParserDiagnostic,
    ParserDiagnosticCode,
    TranscriptMetadata,
    TranscriptSlot,
)

__all__ = [
    "DiscardReason",
    "DiscardedOccurrence",
    "InternalBoundary",
    "LaneResult",
    "ParserDiagnostic",
    "ParserDiagnosticCode",
    "ParsedTranscript",
    "TranscriptMetadata",
    "TranscriptSlot",
    # trimmed: "process_transcript",    # transcripts/lane.py
    # trimmed: "render_group",          # transcripts/rendering.py
    # trimmed: "run_transcript_lane",   # transcripts/lane.py
]
