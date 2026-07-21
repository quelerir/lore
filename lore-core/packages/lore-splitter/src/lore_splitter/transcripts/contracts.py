"""Small, serializable contracts shared by transcript-lane stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ParserDiagnosticCode(StrEnum):
    """Stable parser outcomes safe to expose in metadata."""

    MALFORMED_MARKER = "TRAN-01-MALFORMED_MARKER"
    NO_RELIABLE_SLOTS = "TRAN-01-NO_RELIABLE_SLOTS"
    INVALID_COORDINATE = "TRAN-01-INVALID_COORDINATE"
    REMOVED_SECTION = "TRAN-01-REMOVED_SECTION"


class DiscardReason(StrEnum):
    """Allow-listed reasons for a later lane/model discard decision."""

    ADMINISTRATION = "administration"
    TECHNICAL_FAILURE = "technical_failure"
    GREETING_OR_CLOSING = "greeting_or_closing"
    OTHER_NON_CONTENT = "other_non_content"


@dataclass(frozen=True)
class TranscriptSlot:
    slot_id: str
    ordinal: int
    speaker: str
    start_ms: int
    end_ms: int | None
    source_text: str

    def __post_init__(self) -> None:
        if not self.slot_id or self.ordinal < 0 or not self.speaker.strip():
            raise ValueError("invalid_transcript_slot")
        if self.start_ms < 0 or (self.end_ms is not None and self.end_ms < self.start_ms):
            raise ValueError("invalid_transcript_coordinates")
        if not self.source_text.strip():
            raise ValueError("empty_transcript_slot")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParserDiagnostic:
    code: ParserDiagnosticCode
    count: int = 1
    line_number: int | None = None

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ValueError("invalid_diagnostic_count")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "count": self.count,
            **({"line_number": self.line_number} if self.line_number is not None else {}),
        }


@dataclass(frozen=True)
class TranscriptMetadata:
    title: str | None = None
    removed_sections: tuple[tuple[str, int], ...] = ()

    def __post_init__(self) -> None:
        if self.title is not None and not self.title.strip():
            raise ValueError("empty_transcript_title")
        if any(not name or count < 1 for name, count in self.removed_sections):
            raise ValueError("invalid_removed_section_counter")

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "removed_sections": {name: count for name, count in self.removed_sections},
        }


@dataclass(frozen=True)
class DiscardedOccurrence:
    slot_id: str
    speaker: str
    start_ms: int
    end_ms: int | None
    reason: DiscardReason

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "speaker": self.speaker,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "reason": self.reason.value,
        }


@dataclass(frozen=True)
class InternalBoundary:
    slot_id: str
    speaker: str
    start_ms: int
    end_ms: int | None
    continuation_of: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "speaker": self.speaker,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            **({"continuation_of": self.continuation_of} if self.continuation_of else {}),
        }


@dataclass(frozen=True)
class ParsedTranscript:
    metadata: TranscriptMetadata = field(default_factory=TranscriptMetadata)
    slots: tuple[TranscriptSlot, ...] = ()
    diagnostics: tuple[ParserDiagnostic, ...] = ()
    discarded: tuple[DiscardedOccurrence, ...] = ()
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "slots": [slot.to_dict() for slot in self.slots],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "discarded": [item.to_dict() for item in self.discarded],
            "skipped": self.skipped,
        }


@dataclass(frozen=True)
class LaneResult:
    """Later lane handoff; no model/client details belong in this contract yet."""

    status: str
    chunks: tuple[Any, ...] = ()
    diagnostics: tuple[ParserDiagnostic, ...] = ()
    persistence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "chunks": [
                chunk.to_dict() if hasattr(chunk, "to_dict") else chunk for chunk in self.chunks
            ],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "persistence": self.persistence,
        }
