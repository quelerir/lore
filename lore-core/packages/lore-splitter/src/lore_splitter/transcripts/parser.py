"""Deterministic cleanup and source-slot parsing for MyMeet Markdown."""

from __future__ import annotations

import re
from collections import Counter

from lore_splitter.transcripts.contracts import (
    DiscardedOccurrence,
    DiscardReason,
    ParsedTranscript,
    ParserDiagnostic,
    ParserDiagnosticCode,
    TranscriptMetadata,
    TranscriptSlot,
)

_TITLE_RE = re.compile(r"^\s*\*\*(?P<title>[^*]+?)\*\*\s*$")
_MARKER_RE = re.compile(
    r"^\s*(?:\[(?P<bracket>\d{1,2}:\d{2}(?::\d{2})?)\]|"
    r"\*{0,2}(?P<plain>\d{1,2}:\d{2}(?::\d{2})?)\*{0,2})"
    r"\s*(?:[-–—|]\s*)?(?P<speaker>[^:]{1,80}):\s*(?P<body>.*)$"
)
_TIME_PREFIX_RE = re.compile(r"^\s*(?:\[)?\d{1,2}:\d{2}(?::\d{2})?")
_SUMMARY_HEADINGS = ("супер краткое содержание", "краткое содержание", "summary")
_METADATA_HEADINGS = ("метаданные", "metadata", "информация о встрече")
_TRANSCRIPT_HEADINGS = ("транскрипт", "расшифровка", "transcript")
_ADMIN_PATTERNS = (
    re.compile(r"\bпривет(?:ствие)?\b|\bвсем привет\b", re.I),
    re.compile(r"\bдо свидания\b|\bвсем пока\b|\bпрощани", re.I),
    re.compile(r"\bслышно меня\b|\bне слышно\b|\bповтори(?:те)?\b", re.I),
)


def _milliseconds(value: str) -> int:
    parts = tuple(int(part) for part in value.split(":"))
    if len(parts) == 2:
        minutes, seconds = parts
        hours = 0
    else:
        hours, minutes, seconds = parts
    if minutes > 59 or seconds > 59:
        raise ValueError("invalid_timecode")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000


def _heading_kind(line: str) -> str | None:
    normalized = re.sub(r"^[#>*\s-]+", "", line).strip().casefold().rstrip(":")
    if any(normalized.startswith(item) for item in _SUMMARY_HEADINGS):
        return "summary"
    if any(normalized.startswith(item) for item in _METADATA_HEADINGS):
        return "metadata"
    if any(normalized.startswith(item) for item in _TRANSCRIPT_HEADINGS):
        return "transcript"
    return None


def _is_administrative(text: str) -> DiscardReason | None:
    if any(pattern.search(text) for pattern in _ADMIN_PATTERNS):
        if "слышно" in text.casefold() or "повтори" in text.casefold():
            return DiscardReason.TECHNICAL_FAILURE
        if "привет" in text.casefold() or "прощ" in text.casefold() or "пока" in text.casefold():
            return DiscardReason.GREETING_OR_CLOSING
    return None


def parse_transcript(
    text: str,
    *,
    max_diagnostics: int = 32,
    max_removed_sections: int = 16,
) -> ParsedTranscript:
    """Remove generated MyMeet sections and return parser-owned source slots.

    The parser accepts only local ``timecode + speaker: text`` markers. Lines without
    a marker continue the preceding slot; before the first valid marker they are
    treated as front matter and never become model input.
    """
    if not isinstance(text, str):
        raise TypeError("transcript_text_must_be_string")

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title: str | None = None
    section_counts: Counter[str] = Counter()
    diagnostics: list[ParserDiagnostic] = []
    candidates: list[tuple[int, int, str, str]] = []
    mode: str | None = None
    in_generated_section = False
    removed_section_limit_hit = False

    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if title is None:
            title_match = _TITLE_RE.match(line)
            if title_match:
                title = title_match.group("title").strip()
                continue

        heading_kind = _heading_kind(line) if line else None
        if heading_kind:
            mode = heading_kind
            in_generated_section = heading_kind in {"summary", "metadata"}
            if in_generated_section:
                if len(section_counts) < max_removed_sections or heading_kind in section_counts:
                    section_counts[heading_kind] += 1
                elif not removed_section_limit_hit:
                    diagnostics.append(ParserDiagnostic(ParserDiagnosticCode.REMOVED_SECTION))
                    removed_section_limit_hit = True
            continue

        if in_generated_section:
            continue

        marker = _MARKER_RE.match(raw_line)
        if marker:
            raw_time = marker.group("bracket") or marker.group("plain")
            try:
                start_ms = _milliseconds(raw_time)
            except ValueError:
                if len(diagnostics) < max_diagnostics:
                    diagnostics.append(
                        ParserDiagnostic(
                            ParserDiagnosticCode.INVALID_COORDINATE,
                            line_number=line_number,
                        )
                    )
                continue
            speaker = marker.group("speaker").strip()
            body = marker.group("body").strip()
            if not body:
                if len(diagnostics) < max_diagnostics:
                    diagnostics.append(
                        ParserDiagnostic(
                            ParserDiagnosticCode.MALFORMED_MARKER,
                            line_number=line_number,
                        )
                    )
                continue
            candidates.append((line_number, start_ms, speaker, body))
            continue

        if _TIME_PREFIX_RE.match(raw_line) and len(diagnostics) < max_diagnostics:
            diagnostics.append(
                ParserDiagnostic(ParserDiagnosticCode.MALFORMED_MARKER, line_number=line_number)
            )
        elif candidates and line:
            line_number, start_ms, speaker, body = candidates[-1]
            candidates[-1] = (line_number, start_ms, speaker, f"{body}\n{line}")
        elif (
            not candidates
            and mode == "transcript"
            and ":" in line
            and len(diagnostics) < max_diagnostics
        ):
            diagnostics.append(
                ParserDiagnostic(ParserDiagnosticCode.MALFORMED_MARKER, line_number=line_number)
            )

    slots: list[TranscriptSlot] = []
    discarded: list[DiscardedOccurrence] = []
    for ordinal, (line_number, start_ms, speaker, source_text) in enumerate(candidates):
        end_ms = candidates[ordinal + 1][1] if ordinal + 1 < len(candidates) else None
        slot = TranscriptSlot(
            f"s{ordinal + 1:04d}", ordinal, speaker, start_ms, end_ms, source_text
        )
        reason = _is_administrative(source_text)
        if reason is None:
            slots.append(slot)
        else:
            discarded.append(
                DiscardedOccurrence(slot.slot_id, slot.speaker, slot.start_ms, slot.end_ms, reason)
            )

    if not slots:
        diagnostics.append(ParserDiagnostic(ParserDiagnosticCode.NO_RELIABLE_SLOTS))

    return ParsedTranscript(
        metadata=TranscriptMetadata(title, tuple(section_counts.items())),
        slots=tuple(slots),
        diagnostics=tuple(diagnostics[:max_diagnostics]),
        discarded=tuple(discarded),
        skipped=not slots,
    )
