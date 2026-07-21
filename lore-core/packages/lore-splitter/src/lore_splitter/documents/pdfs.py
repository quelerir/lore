"""Deterministic, non-rendering PDF classification, cleanup, and chunking."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lore_splitter.chunks import Chunk, ChunkBudget, ChunkCoordinates, build_chunk

PDF_RULE_VERSION = "pdf-classifier/v1"


@dataclass(frozen=True)
class PDFConfig:
    min_text_chars: int = 24
    min_usable_page_ratio: float = 0.25
    repeated_fragment_pages: int = 3
    max_cleanup_fragments: int = 32
    max_pages: int = 2000


@dataclass(frozen=True)
class PDFPage:
    number: int
    text: str
    blocks: tuple[dict[str, Any], ...] = ()
    has_raster: bool = False


@dataclass(frozen=True)
class PDFClassification:
    kind: str
    evidence: dict[str, Any]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "rule_version": PDF_RULE_VERSION,
            "evidence": dict(self.evidence),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class PDFResult:
    classification: PDFClassification
    pages: tuple[PDFPage, ...]
    diagnostics: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class PDFChunkResult:
    chunks: tuple[Chunk, ...]
    classification: PDFClassification
    diagnostics: tuple[dict[str, Any], ...] = ()


def read_pdf(path: str | Path, *, config: PDFConfig | None = None) -> PDFResult:
    config = config or PDFConfig()
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pdf_dependency_missing") from exc
    try:
        document = fitz.open(str(path))
    except Exception:  # noqa: BLE001
        return PDFResult(
            PDFClassification(
                "scanned_or_unsupported", {"reason": "unreadable"}, ("pdf_unreadable",)
            ),
            (),
            ({"code": "pdf_unreadable"},),
        )
    pages: list[PDFPage] = []
    diagnostics: list[dict[str, Any]] = []
    try:
        if len(document) > config.max_pages:
            diagnostics.append({"code": "pdf_page_limit", "limit": config.max_pages})
        for number, page in enumerate(document, 1):
            if number > config.max_pages:
                break
            raw = page.get_text("dict")
            blocks = tuple(block for block in raw.get("blocks", ()) if block.get("type") == 0)
            text = "\n".join(
                span.get("text", "")
                for block in blocks
                for line in block.get("lines", ())
                for span in line.get("spans", ())
            ).strip()
            pages.append(PDFPage(number, text, blocks, bool(page.get_images(full=True))))
    finally:
        document.close()
    classification = classify_pdf(pages, config=config)
    return PDFResult(classification, tuple(pages), tuple(diagnostics))


def classify_pdf(
    pages: tuple[PDFPage, ...] | list[PDFPage], *, config: PDFConfig | None = None
) -> PDFClassification:
    config = config or PDFConfig()
    pages = tuple(pages)
    usable = [page for page in pages if len(page.text) >= config.min_text_chars]
    raster_only = sum(not page.text and page.has_raster for page in pages)
    short_pages = sum(bool(page.text) and len(page.text) < config.min_text_chars for page in pages)
    headings = sum(
        bool(re.search(r"(?m)^(?:[A-Z][^.!?]{2,80}|\d+(?:\.\d+)*\s+\S+)$", page.text))
        for page in pages
    )
    one_block_pages = sum(len(page.blocks) <= 3 for page in usable)
    ratio = len(usable) / len(pages) if pages else 0.0
    presentation_score = (one_block_pages / len(usable) if usable else 0.0) + (
        0.25 if headings == 0 else 0
    )
    document_score = (headings / len(usable) if usable else 0.0) + (0.2 if short_pages == 0 else 0)
    warnings: list[str] = []
    if not pages or ratio < config.min_usable_page_ratio:
        kind = "scanned_or_unsupported"
    elif abs(presentation_score - document_score) < 0.25:
        kind = "presentation_like"
        warnings.append("pdf_ambiguous_classification")
    elif presentation_score > document_score:
        kind = "presentation_like"
    else:
        kind = "document_like"
    return PDFClassification(
        kind,
        {
            "page_count": len(pages),
            "usable_pages": len(usable),
            "usable_ratio": round(ratio, 4),
            "raster_only_pages": raster_only,
            "short_text_pages": short_pages,
            "heading_pages": headings,
            "layout_score": round(presentation_score, 4),
        },
        tuple(warnings),
    )


def clean_pdf_pages(
    pages: tuple[PDFPage, ...] | list[PDFPage], *, config: PDFConfig | None = None
) -> tuple[tuple[PDFPage, ...], tuple[dict[str, Any], ...]]:
    config = config or PDFConfig()
    pages = tuple(pages)
    fragments = Counter()
    for page in pages:
        lines = page.text.splitlines()
        # Only the outermost lines are layout candidates.  The second line
        # can be real content on short pages and must not be discarded merely
        # because it repeats across pages.
        for line in ((lines[0],) if lines else ()) + ((lines[-1],) if len(lines) > 1 else ()):
            normalized = _normalize_fragment(line)
            if normalized:
                fragments[normalized] += 1
    repeated = {
        fragment for fragment, count in fragments.items() if count >= config.repeated_fragment_pages
    }
    repeated = set(sorted(repeated)[: config.max_cleanup_fragments])
    warnings: list[dict[str, Any]] = []
    if len(fragments) > config.max_cleanup_fragments:
        warnings.append({"code": "pdf_cleanup_limit", "limit": "max_cleanup_fragments"})
    cleaned: list[PDFPage] = []
    for page in pages:
        original_lines = page.text.splitlines()
        lines = [
            line
            for index, line in enumerate(original_lines)
            if not (index in {0, len(original_lines) - 1} and _normalize_fragment(line) in repeated)
        ]
        text = _repair_lines(lines)
        cleaned.append(PDFPage(page.number, text, page.blocks, page.has_raster))
    return tuple(cleaned), tuple(warnings)


def build_pdf_chunks(
    *,
    run_id: str,
    file_id: str,
    pdf: PDFResult | str | Path,
    budget: ChunkBudget | None = None,
    config: PDFConfig | None = None,
) -> PDFChunkResult:
    budget = budget or ChunkBudget()
    config = config or PDFConfig()
    result = read_pdf(pdf, config=config) if isinstance(pdf, (str, Path)) else pdf
    pages, cleanup_diagnostics = clean_pdf_pages(result.pages, config=config)
    diagnostics = list(result.diagnostics) + list(cleanup_diagnostics)
    diagnostics.extend(
        {"code": "pdf_scanned_page", "page": page.number} for page in pages if not page.text
    )
    if result.classification.kind == "scanned_or_unsupported":
        diagnostics.append({"code": "pdf_skipped_scanned_or_unsupported"})
        return PDFChunkResult((), result.classification, tuple(diagnostics))
    chunks: list[Chunk] = []
    for ordinal, page in enumerate(page for page in pages if page.text):
        text = page.text
        heading = _first_heading(text) if result.classification.kind == "document_like" else ""
        coordinates = ChunkCoordinates(
            heading_path=(heading,) if heading else (),
            page=page.number,
            page_start=page.number,
            page_end=page.number,
            internal_boundaries=(f"page:{page.number}",),
        )
        built = build_chunk(
            run_id=run_id,
            file_id=file_id,
            ordinal=ordinal,
            pipeline_type="pdf",
            chunk_type=result.classification.kind,
            display_text=f"Page {page.number}\n{text}",
            vector_text=f"{heading}\n\n{text}" if heading else text,
            fulltext=f"{heading}\n\n{text}" if heading else text,
            coordinates=coordinates,
            budget=budget,
        )
        chunks.extend(built if isinstance(built, list) else [built])
    return PDFChunkResult(tuple(chunks), result.classification, tuple(diagnostics))


def _normalize_fragment(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower().strip("-–—")


def _repair_lines(lines: list[str]) -> str:
    output: list[str] = []
    for line in lines:
        value = line.strip()
        if not value:
            if output and output[-1] != "":
                output.append("")
            continue
        if output and output[-1].endswith("-") and value[:1].islower():
            output[-1] = output[-1][:-1] + value
        else:
            output.append(value)
    return "\n".join(output).strip()


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        if 2 <= len(line) <= 100 and not line.endswith((".", ";", ":")):
            return line
    return ""
