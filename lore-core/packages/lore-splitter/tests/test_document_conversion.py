from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest
from lore_splitter.documents import __all__ as document_exports
from lore_splitter.documents.contracts import DocumentInputArtifact
from lore_splitter.documents.conversion import (
    DocumentMarkdownConverter,
    convert_document_inputs,
)
from tests.fixtures.documents.generate_contract_fixtures import create_document_contract_fixtures


def test_markdown_input_uses_normalizer_and_bypasses_markitdown(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "documents" / "sample.md"
    markdown_path = tmp_path / "sample.md"
    markdown_path.write_text(
        source.read_text(encoding="utf-8").replace("\n", "\r\n"),
        encoding="utf-8",
    )
    converter = DocumentMarkdownConverter(markitdown_factory=_raising_factory)

    result = converter.convert(_document_artifact(markdown_path, mime_family="markdown"))

    assert result.document_format == "markdown"
    assert result.markdown == source.read_text(encoding="utf-8")
    assert result.document_checksum == _checksum(result.markdown)
    assert result.warnings == ()


@pytest.mark.parametrize(
    ("filename", "mime_family", "markdown"),
    [
        ("contract.docx", "word-processing", "# Contract\n\nDOCX body\n"),
        ("slides.pptx", "presentation", "# Slide 1\n\nPPTX body\n"),
        ("manual.pdf", "pdf", "# Page 1\n\nPDF body\n"),
    ],
)
def test_injected_converter_returns_deterministic_results_and_checksums(
    tmp_path: Path,
    filename: str,
    mime_family: str,
    markdown: str,
) -> None:
    document_path = tmp_path / filename
    document_path.write_bytes(b"document bytes")
    fake_markitdown = _FakeMarkItDown({document_path: markdown})
    converter = DocumentMarkdownConverter(markitdown_factory=lambda: fake_markitdown)

    result = converter.convert(_document_artifact(document_path, mime_family=mime_family))

    assert fake_markitdown.paths == [document_path]
    assert result.markdown == markdown
    assert result.document_checksum == _checksum(markdown)
    assert result.source.local_path == str(document_path)
    assert result.diagnostics == ()


def test_real_markitdown_backed_fixtures_convert_docx_pptx_and_text_pdf(
    tmp_path: Path,
) -> None:
    fixtures = create_document_contract_fixtures(tmp_path)
    converter = DocumentMarkdownConverter()

    docx = converter.convert(_document_artifact(fixtures.docx, mime_family="word-processing"))
    pptx = converter.convert(_document_artifact(fixtures.pptx, mime_family="presentation"))
    pdf = converter.convert(_document_artifact(fixtures.pdf, mime_family="pdf"))

    assert "Contract" in docx.markdown
    assert "Deterministic" in docx.markdown
    assert "Slide" in pptx.markdown
    assert "Deterministic" in pptx.markdown
    assert "Contract Manual" in pdf.markdown
    assert "deterministic PDF text" in pdf.markdown


def test_fixture_helper_creates_deterministic_contract_documents_without_extra_dependencies(
    tmp_path: Path,
) -> None:
    fixtures = create_document_contract_fixtures(tmp_path)

    assert zipfile.is_zipfile(fixtures.docx)
    assert zipfile.is_zipfile(fixtures.pptx)
    assert fixtures.pdf.read_bytes().startswith(b"%PDF-1.4")
    assert fixtures.empty_pdf.read_bytes().startswith(b"%PDF-1.4")
    assert fixtures.corrupt.read_bytes() == b"not a valid office document or pdf"

    helper_source = (
        Path(__file__).parent / "fixtures" / "documents" / "generate_contract_fixtures.py"
    ).read_text(encoding="utf-8")
    assert "python-docx" not in helper_source
    assert "python-pptx" not in helper_source
    assert "pymupdf" not in helper_source.lower()
    assert "Pillow" not in helper_source


@pytest.mark.parametrize(
    ("filename", "mime_family", "markdown", "warning"),
    [
        ("slides.pptx", "presentation", "Agenda\n\nOnly raw slide text\n", "weak_slide_boundaries"),
        ("manual.pdf", "pdf", "Manual text without page markers\n", "weak_page_boundaries"),
    ],
)
def test_weak_presentation_and_pdf_boundaries_are_successful_with_warnings(
    tmp_path: Path,
    filename: str,
    mime_family: str,
    markdown: str,
    warning: str,
) -> None:
    document_path = tmp_path / filename
    document_path.write_bytes(b"document bytes")
    converter = DocumentMarkdownConverter(
        markitdown_factory=lambda: _FakeMarkItDown({document_path: markdown})
    )

    result = converter.convert(_document_artifact(document_path, mime_family=mime_family))

    assert result.markdown == markdown
    assert warning in result.warnings


def test_empty_exceptions_and_corrupt_inputs_return_source_scoped_diagnostics(
    tmp_path: Path,
) -> None:
    ok_path = tmp_path / "ok.docx"
    empty_path = tmp_path / "empty.pdf"
    error_path = tmp_path / "error.pptx"
    for path in (ok_path, empty_path, error_path):
        path.write_bytes(b"document bytes")
    converter = DocumentMarkdownConverter(
        markitdown_factory=lambda: _FakeMarkItDown(
            {
                ok_path: "# OK\n\nBody\n",
                empty_path: " \n \t",
                error_path: RuntimeError("broken presentation"),
            }
        )
    )

    result = convert_document_inputs(
        (
            _document_artifact(ok_path, mime_family="word-processing", file_id="ok"),
            _document_artifact(empty_path, mime_family="pdf", file_id="empty"),
            _document_artifact(error_path, mime_family="presentation", file_id="error"),
        ),
        converter=converter,
    )

    assert [document.source.file_id for document in result.documents] == ["ok"]
    assert [(item.reason, item.file_id) for item in result.diagnostics] == [
        ("no_extractable_text", "empty"),
        ("document_conversion_failed", "error"),
    ]
    assert all("Body" not in item.message for item in result.diagnostics)


def test_corrupt_real_fixture_returns_document_conversion_failed_diagnostic(
    tmp_path: Path,
) -> None:
    fixtures = create_document_contract_fixtures(tmp_path)

    result = convert_document_inputs(
        (_document_artifact(fixtures.corrupt, mime_family="word-processing", file_id="corrupt"),),
        converter=DocumentMarkdownConverter(),
    )

    assert result.documents == ()
    assert [(item.reason, item.file_id) for item in result.diagnostics] == [
        ("document_conversion_failed", "corrupt")
    ]


def test_documents_package_exports_public_conversion_api() -> None:
    assert "DocumentMarkdownConverter" in document_exports
    assert "convert_document_inputs" in document_exports


class _FakeMarkItDown:
    def __init__(self, outputs: dict[Path, str | Exception]) -> None:
        self.outputs = outputs
        self.paths: list[Path] = []

    def convert(self, path: str | Path) -> _FakeMarkItDownResult:
        resolved_path = Path(path)
        self.paths.append(resolved_path)
        output = self.outputs[resolved_path]
        if isinstance(output, Exception):
            raise output
        return _FakeMarkItDownResult(output)


class _FakeMarkItDownResult:
    def __init__(self, text_content: str) -> None:
        self.text_content = text_content


def _raising_factory() -> object:
    raise AssertionError("MarkItDown must not be instantiated for Markdown sources")


def _checksum(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _document_artifact(
    path: Path,
    *,
    mime_family: str,
    file_id: str | None = None,
) -> DocumentInputArtifact:
    extension = path.suffix.lower()
    return DocumentInputArtifact(
        source_id="google-drive",
        stream="documents",
        file_id=file_id or path.stem,
        source_path=f"Documents/{path.name}",
        object_path=f"/objects/documents/{path.name}",
        mime_type=_mime_type(extension),
        size_bytes=path.stat().st_size,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        source_url=f"https://drive.example/{path.stem}",
        metadata={"owner": "hr"},
        raw_record={"id": file_id or path.stem},
        local_path=str(path),
        input_kind="document",
        normalized_extension=extension,
        mime_family=mime_family,
    )


def _mime_type(extension: str) -> str:
    return {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pdf": "application/pdf",
        ".md": "text/markdown",
    }[extension]
