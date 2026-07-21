from __future__ import annotations

from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from lore_splitter.contracts import ManifestDiagnostic, SourceFile
from lore_splitter.documents.contracts import (
    DocumentInputArtifact,
    DocumentMarkdownResult,
)
from lore_splitter.markdown.contracts import (
    MarkdownTableLocation,
    TableData,
    TableProfile,
    ToastDecision,
)
from lore_splitter.markdown.profile import profile_table
from lore_splitter.markdown.toast import (
    CLASSIFICATION_INLINE,
    CLASSIFICATION_SKIPPED,
    CLASSIFICATION_TOAST,
    ToastThresholds,
    classify_table,
    render_toast_reference,
)

DIAGNOSTIC_MALFORMED_PIPE_TABLE = "malformed_pipe_table"
DIAGNOSTIC_UNSUPPORTED_HTML_TABLE = "unsupported_html_table"
DIAGNOSTIC_MARKDOWN_TABLE_EXTRACTION_FAILED = "markdown_table_extraction_failed"
SKIP_MARKER_UNSUPPORTED_HTML_TABLE = "[TABLE_SKIPPED: unsupported_html_table]"

_SUPPORTED_HTML_TABLE_TAGS = frozenset({"table", "thead", "tbody", "tr", "th", "td"})
_UNSUPPORTED_HTML_TABLE_ATTRS = frozenset({"rowspan", "colspan"})


@dataclass(frozen=True)
class MarkdownTableOccurrence:
    source: DocumentInputArtifact
    location: MarkdownTableLocation
    table_format: str
    table: TableData | None = None
    profile: TableProfile | None = None
    decision: ToastDecision | None = None
    skip_reason: str | None = None

    @property
    def content_signature(self) -> str | None:
        return self.decision.content_signature if self.decision is not None else None

    @property
    def toast_id(self) -> str | None:
        return self.decision.toast_id if self.decision is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.source_identity,
            "location": self.location.to_dict(),
            "table_format": self.table_format,
            "content_signature": self.content_signature,
            "toast_id": self.toast_id,
            "classification": self.decision.classification if self.decision else None,
            "skip_reason": self.skip_reason,
        }


@dataclass(frozen=True)
class MarkdownTableExtractionResult:
    documents: tuple[DocumentMarkdownResult, ...] = ()
    tables: tuple[TableData, ...] = ()
    unique_tables: tuple[TableData, ...] = ()
    profiles: tuple[TableProfile, ...] = ()
    decisions: tuple[ToastDecision, ...] = ()
    occurrences: tuple[MarkdownTableOccurrence, ...] = ()
    diagnostics: tuple[ManifestDiagnostic, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "documents": [document.to_dict() for document in self.documents],
            "tables": [table.to_dict() for table in self.tables],
            "unique_tables": [table.to_dict() for table in self.unique_tables],
            "profiles": [profile.to_dict() for profile in self.profiles],
            "decisions": [decision.to_dict() for decision in self.decisions],
            "occurrences": [occurrence.to_dict() for occurrence in self.occurrences],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class _Candidate:
    table_format: str
    start_index: int
    end_index: int
    location: MarkdownTableLocation
    columns: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()
    skip_reason: str | None = None
    diagnostic_message: str | None = None


def extract_markdown_document_tables(
    documents: tuple[DocumentMarkdownResult, ...] | list[DocumentMarkdownResult],
    thresholds: ToastThresholds | None = None,
) -> MarkdownTableExtractionResult:
    rewritten_documents: list[DocumentMarkdownResult] = []
    tables: list[TableData] = []
    profiles: list[TableProfile] = []
    decisions: list[ToastDecision] = []
    occurrences: list[MarkdownTableOccurrence] = []
    diagnostics: list[ManifestDiagnostic] = []
    warnings: list[str] = []

    for document in documents:
        try:
            document_result = _extract_document_tables(document, thresholds)
        except Exception as exc:  # pragma: no cover - defensive source isolation
            diagnostics.append(
                _diagnostic(
                    document,
                    DIAGNOSTIC_MARKDOWN_TABLE_EXTRACTION_FAILED,
                    f"failed to extract markdown tables: {exc}",
                )
            )
            rewritten_documents.append(document)
            continue

        rewritten_documents.append(document_result.documents[0])
        tables.extend(document_result.tables)
        profiles.extend(document_result.profiles)
        decisions.extend(document_result.decisions)
        occurrences.extend(document_result.occurrences)
        diagnostics.extend(document_result.diagnostics)
        warnings.extend(document_result.warnings)

    unique_tables = _unique_tables(tables, decisions)
    return MarkdownTableExtractionResult(
        documents=tuple(rewritten_documents),
        tables=tuple(tables),
        unique_tables=unique_tables,
        profiles=tuple(profiles),
        decisions=tuple(decisions),
        occurrences=tuple(occurrences),
        diagnostics=tuple(diagnostics),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _extract_document_tables(
    document: DocumentMarkdownResult,
    thresholds: ToastThresholds | None,
) -> MarkdownTableExtractionResult:
    lines = document.markdown.splitlines(keepends=True)
    candidates = _scan_candidates(lines)
    source_file = _source_file(document.source)

    tables: list[TableData] = []
    profiles: list[TableProfile] = []
    decisions: list[ToastDecision] = []
    occurrences: list[MarkdownTableOccurrence] = []
    diagnostics: list[ManifestDiagnostic] = []
    replacements: list[tuple[int, int, str]] = []

    for candidate in candidates:
        if candidate.skip_reason is not None:
            diagnostics.append(
                _diagnostic(
                    document,
                    candidate.skip_reason,
                    candidate.diagnostic_message
                    or (
                        f"skipped unsupported markdown table at line "
                        f"{candidate.location.line_start}-{candidate.location.line_end}"
                    ),
                )
            )
            replacements.append(
                (candidate.start_index, candidate.end_index, SKIP_MARKER_UNSUPPORTED_HTML_TABLE)
            )
            occurrences.append(
                MarkdownTableOccurrence(
                    source=document.source,
                    location=candidate.location,
                    table_format=candidate.table_format,
                    skip_reason=candidate.skip_reason,
                )
            )
            continue

        table = TableData(
            source_file=source_file,
            local_path=Path(document.local_path),
            source_kind="document",
            source_checksum=document.document_checksum,
            table_index=candidate.location.table_index,
            columns=candidate.columns,
            rows=candidate.rows,
            markdown=candidate.location,
        )
        profile = profile_table(table)
        decision = classify_table(table, profile, thresholds=thresholds)
        tables.append(table)
        profiles.append(profile)
        decisions.append(decision)
        occurrences.append(
            MarkdownTableOccurrence(
                source=document.source,
                location=candidate.location,
                table_format=candidate.table_format,
                table=table,
                profile=profile,
                decision=decision,
                skip_reason="classification_skipped"
                if decision.classification == CLASSIFICATION_SKIPPED
                else None,
            )
        )
        if decision.classification == CLASSIFICATION_TOAST:
            replacements.append(
                (candidate.start_index, candidate.end_index, render_toast_reference(decision))
            )
        elif decision.classification == CLASSIFICATION_SKIPPED:
            diagnostics.append(
                _diagnostic(
                    document,
                    CLASSIFICATION_SKIPPED,
                    (
                        f"skipped low-meaning markdown table at line "
                        f"{candidate.location.line_start}-{candidate.location.line_end}: "
                        f"{', '.join(decision.reasons)}"
                    ),
                )
            )
            replacements.append((candidate.start_index, candidate.end_index, ""))
        elif decision.classification != CLASSIFICATION_INLINE:
            diagnostics.append(
                _diagnostic(
                    document,
                    DIAGNOSTIC_MARKDOWN_TABLE_EXTRACTION_FAILED,
                    f"unknown table classification: {decision.classification}",
                )
            )

    rewritten_markdown = _apply_replacements(lines, replacements)
    rewritten_document = replace(document, markdown=rewritten_markdown)
    return MarkdownTableExtractionResult(
        documents=(rewritten_document,),
        tables=tuple(tables),
        unique_tables=_unique_tables(tables, decisions),
        profiles=tuple(profiles),
        decisions=tuple(decisions),
        occurrences=tuple(occurrences),
        diagnostics=tuple(diagnostics),
        warnings=tuple(dict.fromkeys(diagnostic.reason for diagnostic in diagnostics)),
    )


def _scan_candidates(lines: list[str]) -> tuple[_Candidate, ...]:
    fenced = _fenced_code_lines(lines)
    table_index = 1
    candidates: list[_Candidate] = []
    occupied: set[int] = set()

    html_ranges = _html_table_ranges(lines, fenced)
    for start, end in html_ranges:
        candidate = _html_candidate(lines, start, end, table_index)
        candidates.append(candidate)
        table_index += 1
        occupied.update(range(start, end + 1))

    line_index = 0
    while line_index < len(lines):
        if line_index in fenced or line_index in occupied:
            line_index += 1
            continue
        if line_index + 1 >= len(lines) or not _is_pipe_table_delimiter(lines[line_index + 1]):
            line_index += 1
            continue
        candidate = _pipe_candidate(lines, line_index, table_index)
        candidates.append(candidate)
        table_index += 1
        occupied.update(range(candidate.start_index, candidate.end_index + 1))
        line_index = candidate.end_index + 1

    return _renumber_candidates(
        tuple(sorted(candidates, key=lambda candidate: candidate.start_index))
    )


def _renumber_candidates(candidates: tuple[_Candidate, ...]) -> tuple[_Candidate, ...]:
    return tuple(
        replace(
            candidate,
            location=MarkdownTableLocation(
                table_index=index,
                line_start=candidate.location.line_start,
                line_end=candidate.location.line_end,
            ),
        )
        for index, candidate in enumerate(candidates, start=1)
    )


def _pipe_candidate(lines: list[str], start_index: int, table_index: int) -> _Candidate:
    end_index = start_index + 1
    while end_index + 1 < len(lines) and _looks_like_pipe_row(lines[end_index + 1]):
        end_index += 1

    header = _split_pipe_row(lines[start_index])
    delimiter = _split_pipe_row(lines[start_index + 1])
    rows = [_normalize_pipe_row(header, len(header))]
    malformed = not header or len(delimiter) != len(header)

    for index in range(start_index + 2, end_index + 1):
        cells = _split_pipe_row(lines[index])
        if len(cells) > len(header):
            malformed = True
            break
        rows.append(_normalize_pipe_row(cells, len(header)))

    location = MarkdownTableLocation(
        table_index=table_index,
        line_start=start_index + 1,
        line_end=end_index + 1,
    )
    if malformed:
        return _Candidate(
            table_format="pipe",
            start_index=start_index,
            end_index=end_index,
            location=location,
            skip_reason=DIAGNOSTIC_MALFORMED_PIPE_TABLE,
            diagnostic_message=(
                f"skipped malformed pipe table at line "
                f"{location.line_start}-{location.line_end}"
            ),
        )

    return _Candidate(
        table_format="pipe",
        start_index=start_index,
        end_index=end_index,
        location=location,
        columns=tuple(rows[0]),
        rows=tuple(tuple(row) for row in rows),
    )


def _html_candidate(
    lines: list[str],
    start_index: int,
    end_index: int,
    table_index: int,
) -> _Candidate:
    html = "".join(lines[start_index : end_index + 1])
    location = MarkdownTableLocation(
        table_index=table_index,
        line_start=start_index + 1,
        line_end=end_index + 1,
    )
    parser = _SimpleHtmlTableParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # pragma: no cover - HTMLParser should not normally raise here
        parser.reject(f"malformed HTML table: {exc}")

    rows = tuple(tuple(cell.strip() for cell in row) for row in parser.rows if any(row))
    if parser.unsupported_reason is not None:
        return _unsupported_html_candidate(
            start_index,
            end_index,
            location,
            parser.unsupported_reason,
        )
    if not rows or len(rows) < 2:
        return _unsupported_html_candidate(
            start_index,
            end_index,
            location,
            "layout-only HTML table",
        )
    column_count = len(rows[0])
    if column_count == 0 or any(len(row) != column_count for row in rows):
        return _unsupported_html_candidate(
            start_index,
            end_index,
            location,
            "irregular HTML table rows",
        )
    if not parser.has_header:
        return _unsupported_html_candidate(
            start_index,
            end_index,
            location,
            "HTML table has no header",
        )

    return _Candidate(
        table_format="html",
        start_index=start_index,
        end_index=end_index,
        location=location,
        columns=rows[0],
        rows=rows,
    )


def _unsupported_html_candidate(
    start_index: int,
    end_index: int,
    location: MarkdownTableLocation,
    reason: str,
) -> _Candidate:
    return _Candidate(
        table_format="html",
        start_index=start_index,
        end_index=end_index,
        location=location,
        skip_reason=DIAGNOSTIC_UNSUPPORTED_HTML_TABLE,
        diagnostic_message=(
            f"skipped unsupported HTML table at line {location.line_start}-{location.line_end}: "
            f"{reason}"
        ),
    )


class _SimpleHtmlTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.table_depth = 0
        self.current_row: list[str] | None = None
        self.current_cell: list[str] | None = None
        self.current_cell_is_header = False
        self.rows: list[tuple[str, ...]] = []
        self.has_header = False
        self.unsupported_reason: str | None = None

    def reject(self, reason: str) -> None:
        if self.unsupported_reason is None:
            self.unsupported_reason = reason

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if self.table_depth > 0 and normalized not in _SUPPORTED_HTML_TABLE_TAGS:
            self.reject(f"unsupported tag <{normalized}>")
        if normalized == "table":
            self.table_depth += 1
            if self.table_depth > 1:
                self.reject("nested table")
            return
        if self.table_depth == 0:
            return
        if any(name.lower() in _UNSUPPORTED_HTML_TABLE_ATTRS for name, _ in attrs):
            self.reject("rowspan or colspan")
        if normalized == "tr":
            if self.current_row is not None:
                self.reject("nested row")
            self.current_row = []
        elif normalized in {"th", "td"}:
            if self.current_row is None:
                self.reject("cell outside row")
            if self.current_cell is not None:
                self.reject("nested cell")
            self.current_cell = []
            self.current_cell_is_header = normalized == "th"

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized == "table":
            self.table_depth = max(0, self.table_depth - 1)
            return
        if self.table_depth == 0:
            return
        if normalized in {"th", "td"}:
            if self.current_cell is None or self.current_row is None:
                self.reject("cell close without open")
                return
            self.current_row.append("".join(self.current_cell).strip())
            if self.current_cell_is_header:
                self.has_header = True
            self.current_cell = None
            self.current_cell_is_header = False
        elif normalized == "tr":
            if self.current_row is None:
                self.reject("row close without open")
                return
            self.rows.append(tuple(self.current_row))
            self.current_row = None

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell.append(data)


def _html_table_ranges(lines: list[str], fenced: set[int]) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    depth = 0
    for index, line in enumerate(lines):
        if index in fenced:
            continue
        lowered = line.lower()
        open_count = lowered.count("<table")
        close_count = lowered.count("</table")
        if open_count and start is None:
            start = index
        depth += open_count
        if start is not None:
            depth -= close_count
            if depth <= 0:
                ranges.append((start, index))
                start = None
                depth = 0
    if start is not None:
        ranges.append((start, len(lines) - 1))
    return tuple(ranges)


def _fenced_code_lines(lines: list[str]) -> set[int]:
    fenced: set[int] = set()
    in_fence = False
    fence_marker: str | None = None
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = None
            fenced.add(index)
            continue
        if in_fence:
            fenced.add(index)
    return fenced


def _is_pipe_table_delimiter(line: str) -> bool:
    cells = _split_pipe_row(line)
    return bool(cells) and all(_is_delimiter_cell(cell) for cell in cells)


def _is_delimiter_cell(cell: str) -> bool:
    stripped = cell.strip()
    if not stripped:
        return False
    stripped = stripped.removeprefix(":").removesuffix(":")
    return len(stripped) >= 3 and set(stripped) == {"-"}


def _looks_like_pipe_row(line: str) -> bool:
    stripped = line.strip()
    return "|" in stripped and bool(_split_pipe_row(line))


def _split_pipe_row(line: str) -> tuple[str, ...]:
    text = line.strip().removesuffix("\n").removesuffix("\r")
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]

    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for character in text:
        if escaped:
            current.append(character)
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == "|":
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(character)
    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return tuple(cells)


def _normalize_pipe_row(cells: tuple[str, ...], column_count: int) -> tuple[str, ...]:
    return cells[:column_count] + tuple("" for _ in range(max(0, column_count - len(cells))))


def _apply_replacements(lines: list[str], replacements: list[tuple[int, int, str]]) -> str:
    if not replacements:
        return "".join(lines)
    rewritten = list(lines)
    for start_index, end_index, replacement in sorted(replacements, reverse=True):
        suffix = "\n" if _range_had_trailing_newline(lines[start_index : end_index + 1]) else ""
        rewritten[start_index : end_index + 1] = [replacement + suffix]
    return "".join(rewritten)


def _range_had_trailing_newline(lines: list[str]) -> bool:
    return bool(lines) and (lines[-1].endswith("\n") or lines[-1].endswith("\r"))


def _unique_tables(
    tables: list[TableData],
    decisions: list[ToastDecision],
) -> tuple[TableData, ...]:
    unique: dict[str, TableData] = {}
    for table, decision in zip(tables, decisions):
        unique.setdefault(decision.toast_id or decision.content_signature, table)
    return tuple(unique.values())


def _source_file(source: DocumentInputArtifact) -> SourceFile:
    return SourceFile(
        source_id=source.source_id,
        stream=source.stream,
        file_id=source.file_id,
        source_path=source.source_path,
        object_path=source.object_path,
        mime_type=source.mime_type,
        size_bytes=source.size_bytes,
        created_at=source.created_at,
        updated_at=source.updated_at,
        source_url=source.source_url,
        metadata=source.metadata,
        raw_record=source.raw_record,
    )


def _diagnostic(
    document: DocumentMarkdownResult,
    reason: str,
    message: str,
) -> ManifestDiagnostic:
    return ManifestDiagnostic.for_source(reason, message, _source_file(document.source))
