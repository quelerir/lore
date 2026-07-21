from __future__ import annotations

import hashlib
import zipfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from lore_splitter.contracts import ManifestDiagnostic, SourceFile
from lore_splitter.documents.contracts import (
    DocumentInputArtifact,
    DocumentMarkdownConversionResult,
    DocumentMarkdownResult,
)
from lore_splitter.documents.markitdown_images import MarkItDownImageCollector
from lore_splitter.documents.normalize import normalize_markdown_source

MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
CONVERTED_DOCUMENT_EXTENSIONS = frozenset({".docx", ".pptx", ".pdf"})


class DocumentConversionError(RuntimeError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class DocumentMarkdownConverter:
    def __init__(
        self,
        *,
        markitdown_factory: Callable[[], Any] | None = None,
        image_collector: MarkItDownImageCollector | None = None,
    ) -> None:
        self._markitdown_factory = markitdown_factory or _default_markitdown_factory
        self._markitdown: Any | None = None
        self._validate_containers = markitdown_factory is None
        self._image_collector = image_collector or MarkItDownImageCollector()

    def convert(self, document: DocumentInputArtifact) -> DocumentMarkdownResult:
        extension = document.normalized_extension.lower()
        if extension in MARKDOWN_EXTENSIONS:
            markdown = normalize_markdown_source(
                Path(document.local_path).read_text(encoding="utf-8")
            )
            return _build_result(document, markdown, warnings=())

        if extension not in CONVERTED_DOCUMENT_EXTENSIONS:
            raise DocumentConversionError(
                "document_conversion_failed",
                f"Unsupported document extension for conversion: {extension or '<none>'}",
            )

        if self._validate_containers:
            _validate_document_container(document)
        converted_markdown = self._convert_with_markitdown(document)
        normalized_markdown = normalize_markdown_source(converted_markdown)
        warnings = _validation_warnings(document, normalized_markdown)
        image_candidates = self._collect_markitdown_images(document)
        return _build_result(
            document,
            normalized_markdown,
            warnings=warnings,
            image_candidates=image_candidates,
        )

    def _convert_with_markitdown(self, document: DocumentInputArtifact) -> str:
        markitdown = self._markitdown_instance()
        try:
            result = markitdown.convert(document.local_path)
        except Exception as exc:  # noqa: BLE001 - third-party conversion failures are source scoped.
            raise DocumentConversionError(
                "document_conversion_failed",
                f"Could not convert document with MarkItDown: {exc}",
            ) from exc

        markdown = getattr(result, "text_content", None)
        if markdown is None:
            markdown = getattr(result, "markdown", None)
        if markdown is None:
            markdown = str(result)
        return markdown

    def _markitdown_instance(self) -> Any:
        if self._markitdown is None:
            self._markitdown = self._markitdown_factory()
        return self._markitdown

    def _collect_markitdown_images(
        self,
        document: DocumentInputArtifact,
    ) -> tuple[Any, ...]:
        if document.normalized_extension.lower() not in {".docx", ".pptx"}:
            return ()
        try:
            return self._image_collector.collect(document)
        except Exception:  # noqa: BLE001 - image capture must not fail text conversion.
            return ()


def convert_document_inputs(
    documents: Iterable[DocumentInputArtifact],
    *,
    converter: DocumentMarkdownConverter | None = None,
) -> DocumentMarkdownConversionResult:
    active_converter = converter or DocumentMarkdownConverter()
    converted_documents: list[DocumentMarkdownResult] = []
    diagnostics: list[ManifestDiagnostic] = []

    for document in documents:
        try:
            result = active_converter.convert(document)
            if not _has_extractable_text(result.markdown):
                diagnostics.append(
                    _source_diagnostic(
                        document,
                        "no_extractable_text",
                        "Document conversion produced no extractable text.",
                    )
                )
                continue
            converted_documents.append(result)
        except DocumentConversionError as exc:
            diagnostics.append(_source_diagnostic(document, exc.reason, str(exc)))
        except Exception as exc:  # noqa: BLE001 - one document must not stop a batch.
            diagnostics.append(
                _source_diagnostic(
                    document,
                    "document_conversion_failed",
                    f"Could not convert document: {exc}",
                )
            )

    return DocumentMarkdownConversionResult(
        documents=tuple(converted_documents),
        diagnostics=tuple(diagnostics),
    )


def _default_markitdown_factory() -> Any:
    from markitdown import MarkItDown

    return MarkItDown(enable_plugins=False)


def _validate_document_container(document: DocumentInputArtifact) -> None:
    extension = document.normalized_extension.lower()
    path = Path(document.local_path)
    if extension in {".docx", ".pptx"} and not zipfile.is_zipfile(path):
        raise DocumentConversionError(
            "document_conversion_failed",
            f"Document is not a valid {extension.lstrip('.').upper()} container.",
        )
    if extension == ".pdf" and not path.read_bytes().startswith(b"%PDF-"):
        raise DocumentConversionError(
            "document_conversion_failed",
            "Document is not a valid PDF file.",
        )


def _build_result(
    document: DocumentInputArtifact,
    markdown: str,
    *,
    warnings: tuple[str, ...],
    image_candidates: tuple[Any, ...] = (),
) -> DocumentMarkdownResult:
    return DocumentMarkdownResult(
        source=document,
        document_format=_document_format(document),
        markdown=markdown,
        document_checksum=_markdown_checksum(markdown),
        warnings=warnings,
        structure_signals=_structure_signals(markdown),
        image_candidates=image_candidates,
    )


def _validation_warnings(document: DocumentInputArtifact, markdown: str) -> tuple[str, ...]:
    warnings: list[str] = []
    if _is_presentation(document) and not _has_slide_boundary(markdown):
        warnings.append("weak_slide_boundaries")
    if _is_pdf(document) and not _has_page_boundary(markdown):
        warnings.append("weak_page_boundaries")
    return tuple(warnings)


def _is_presentation(document: DocumentInputArtifact) -> bool:
    return (
        document.normalized_extension.lower() == ".pptx"
        or document.mime_family == "presentation"
    )


def _is_pdf(document: DocumentInputArtifact) -> bool:
    return document.normalized_extension.lower() == ".pdf" or document.mime_family == "pdf"


def _has_slide_boundary(markdown: str) -> bool:
    return any(
        line.strip().lower().startswith(("slide ", "# slide "))
        for line in markdown.splitlines()
    )


def _has_page_boundary(markdown: str) -> bool:
    return any(
        line.strip().lower().startswith(("page ", "# page "))
        for line in markdown.splitlines()
    )


def _has_extractable_text(markdown: str) -> bool:
    return bool(markdown.strip())


def _markdown_checksum(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _document_format(document: DocumentInputArtifact) -> str:
    extension = document.normalized_extension.lower()
    if extension in MARKDOWN_EXTENSIONS:
        return "markdown"
    return extension.lstrip(".") or document.mime_family


def _structure_signals(markdown: str) -> dict[str, Any]:
    headings = [
        line.lstrip("#").strip()
        for line in markdown.splitlines()
        if line.startswith("#") and line.lstrip("#").strip()
    ]
    return {
        "headings": headings[:20],
        "title": headings[0] if headings else None,
        "character_count": len(markdown),
        "line_count": len(markdown.splitlines()),
    }


def _source_diagnostic(
    document: DocumentInputArtifact,
    reason: str,
    message: str,
) -> ManifestDiagnostic:
    return ManifestDiagnostic.for_source(reason, message, _source_file(document))


def _source_file(document: DocumentInputArtifact) -> SourceFile:
    return SourceFile(
        source_id=document.source_id,
        stream=document.stream,
        file_id=document.file_id,
        source_path=document.source_path,
        object_path=document.object_path,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        created_at=document.created_at,
        updated_at=document.updated_at,
        source_url=document.source_url,
        metadata=document.metadata,
        raw_record=document.raw_record,
    )
