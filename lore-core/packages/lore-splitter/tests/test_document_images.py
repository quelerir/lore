from __future__ import annotations

from pathlib import Path

import pytest
from lore_splitter.documents.contracts import (
    DocumentImageExtractionResult,
    DocumentInputArtifact,
    DocumentMarkdownResult,
    ImageSkip,
    ImageSourceLocation,
    ImageToastCandidate,
    ImageToastOccurrence,
)
from lore_splitter.documents.conversion import DocumentMarkdownConverter
from lore_splitter.documents.images import (
    build_image_storage_plans,
    classify_image_candidate,
    extract_document_images,
)
from lore_splitter.documents.pdf_images import extract_pdf_images
from tests.fixtures.documents.generate_image_fixtures import (
    create_image_contract_fixtures,
    file_sha256,
)


def test_image_fixture_helper_creates_deterministic_docx_pptx_pdf_inputs(tmp_path: Path) -> None:
    first = create_image_contract_fixtures(tmp_path / "first")
    second = create_image_contract_fixtures(tmp_path / "second")

    assert first.docx.suffix == ".docx"
    assert first.pptx.suffix == ".pptx"
    assert first.pdf.read_bytes().startswith(b"%PDF")
    assert first.scanned_pdf.read_bytes().startswith(b"%PDF")
    assert file_sha256(first.content_image) == file_sha256(second.content_image)
    assert file_sha256(first.decorative_logo) == file_sha256(second.decorative_logo)


def test_image_contracts_serialize_source_location_candidates_and_skips() -> None:
    location = ImageSourceLocation(
        source_format="pdf",
        page_number=1,
        bbox=(72.0, 137.0, 392.0, 317.0),
        metadata={"xref": 7},
    )
    occurrence = ImageToastOccurrence(
        source_identity={"file_id": "manual"},
        source_location=location,
    )
    candidate = ImageToastCandidate(
        payload=b"payload",
        content_type="image/png",
        extension=".png",
        byte_size=7,
        checksum_sha256="239f59ed55e737c77147cf55ad0c1b030b6d7ee748a7426952f9b852d5a935e5",
        width_px=320,
        height_px=180,
        source_identity={"file_id": "manual"},
        source_location=location,
        occurrences=(occurrence,),
    )
    skip = ImageSkip(candidate=candidate, reason="decorative_tiny", diagnostics=("small",))
    result = DocumentImageExtractionResult(
        candidates=(candidate,),
        unique_candidates=(candidate,),
        occurrences=(occurrence,),
        skips=(skip,),
        diagnostics=(),
        warnings=("filtered",),
    )

    data = result.to_dict()

    assert data["candidates"][0]["source_location"]["pdf"]["page"] == 1
    assert data["unique_candidates"][0]["checksum_sha256"] == candidate.checksum_sha256
    assert data["occurrences"][0]["source_identity"] == {"file_id": "manual"}
    assert data["skips"][0]["reason"] == "decorative_tiny"
    assert "markdown" not in data


def test_docx_pptx_conversion_collects_images_and_pdf_sidecar_extracts_fixture_content_images(
    tmp_path: Path,
) -> None:
    fixtures = create_image_contract_fixtures(tmp_path)
    converter = DocumentMarkdownConverter(
        markitdown_factory=lambda: _FakeMarkItDown("Image Policy\nImage Slide\nPDF text")
    )

    docx = converter.convert(_document_artifact(fixtures.docx, "word-processing"))
    pptx = converter.convert(_document_artifact(fixtures.pptx, "presentation"))
    pdf = converter.convert(_document_artifact(fixtures.pdf, "pdf"))
    pdf_candidates = extract_pdf_images(pdf.source)

    assert "Image Policy" in docx.markdown
    assert docx.image_candidates
    assert {candidate.source_location.source_format for candidate in docx.image_candidates} == {
        "docx"
    }
    assert "Image Slide" in pptx.markdown
    assert pptx.image_candidates
    assert {candidate.source_location.source_format for candidate in pptx.image_candidates} == {
        "pptx"
    }
    assert pdf.image_candidates == ()
    assert pdf_candidates
    assert {candidate.source_location.source_format for candidate in pdf_candidates} == {"pdf"}
    assert all(candidate.content_type == "image/png" for candidate in pdf_candidates)


def test_pdf_helper_does_not_render_pages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fixtures = create_image_contract_fixtures(tmp_path)
    import lore_splitter.documents.pdf_images as pdf_images

    def fail_get_pixmap(*args: object, **kwargs: object) -> object:
        raise AssertionError("PDF image extraction must not render pages")

    monkeypatch.setattr(pdf_images.fitz.Page, "get_pixmap", fail_get_pixmap)

    candidates = extract_pdf_images(_document_artifact(fixtures.pdf, "pdf"))

    assert candidates


def test_extract_document_images_filters_deduplicates_and_builds_stable_storage_plans(
    tmp_path: Path,
) -> None:
    fixtures = create_image_contract_fixtures(tmp_path)
    converter = DocumentMarkdownConverter(
        markitdown_factory=lambda: _FakeMarkItDown("Image Policy\nImage Slide\nPDF text")
    )
    documents = (
        converter.convert(_document_artifact(fixtures.docx, "word-processing", file_id="docx")),
        converter.convert(_document_artifact(fixtures.pptx, "presentation", file_id="pptx")),
        converter.convert(_document_artifact(fixtures.pdf, "pdf", file_id="pdf")),
        converter.convert(_document_artifact(fixtures.scanned_pdf, "pdf", file_id="scan")),
    )

    result = extract_document_images(documents)
    plans = build_image_storage_plans(result, bucket="splitter-image-toast")
    rerun = extract_document_images(documents)
    rerun_plans = build_image_storage_plans(rerun, bucket="splitter-image-toast")

    assert result.candidates
    assert result.unique_candidates
    assert any(skip.reason == "decorative_tiny" for skip in result.skips)
    assert any(skip.reason == "full_page_raster" for skip in result.skips)
    assert len({candidate.toast_id for candidate in result.unique_candidates}) == len(
        result.unique_candidates
    )
    assert [plan.to_dict() for plan in plans] == [plan.to_dict() for plan in rerun_plans]
    assert [skip.to_dict() for skip in result.skips] == [skip.to_dict() for skip in rerun.skips]
    assert all("schema_name" not in plan.to_dict() for plan in plans)
    assert all("![" not in document.markdown for document in documents)


@pytest.mark.parametrize(
    ("metadata", "expected_reason"),
    (
        ({"image_role": "repeated_decorative"}, "repeated_decorative"),
        ({"image_role": "background"}, "background_candidate"),
        ({"image_role": "icon"}, "icon_candidate"),
        ({"image_role": "bullet"}, "icon_candidate"),
        ({"image_role": "separator"}, "separator_candidate"),
        ({"image_role": "low_information"}, "low_information"),
        ({"image_role": "scanned_layer"}, "scanned_layer"),
    ),
)
def test_classify_image_candidate_exposes_decorative_reason_codes(
    metadata: dict[str, str],
    expected_reason: str,
) -> None:
    candidate = _image_candidate(metadata=metadata)

    assert classify_image_candidate(candidate) == expected_reason


def test_classify_image_candidate_detects_repeated_decorative_assets() -> None:
    candidate = _image_candidate(
        width_px=72,
        height_px=72,
        occurrence_count=3,
    )

    assert classify_image_candidate(candidate) == "repeated_decorative"


def test_extract_document_images_records_reason_codes_for_decorative_categories() -> None:
    candidates = (
        _image_candidate(metadata={"image_role": "icon"}, suffix="icon"),
        _image_candidate(metadata={"image_role": "separator"}, suffix="separator"),
        _image_candidate(metadata={"image_role": "low_information"}, suffix="low-info"),
        _image_candidate(metadata={"image_role": "scanned_layer"}, suffix="scan"),
    )
    document = DocumentMarkdownResult(
        source=_document_artifact_from_name("decorative.docx"),
        document_format="docx",
        markdown="Decorative image source",
        document_checksum="doc-checksum",
        image_candidates=candidates,
    )

    result = extract_document_images((document,))

    assert {skip.reason for skip in result.skips} == {
        "icon_candidate",
        "separator_candidate",
        "low_information",
        "scanned_layer",
    }


def test_unreadable_image_documents_emit_source_scoped_diagnostics(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4\nnot enough structure")

    result = extract_document_images(
        (
            DocumentMarkdownConverter(
                markitdown_factory=lambda: _FakeMarkItDown("PDF text")
            ).convert(_document_artifact(corrupt, "pdf", file_id="corrupt")),
        )
    )

    assert result.diagnostics
    assert result.diagnostics[0].reason == "image_extraction_failed"
    assert result.diagnostics[0].file_id == "corrupt"


def _image_candidate(
    *,
    metadata: dict[str, str] | None = None,
    width_px: int = 120,
    height_px: int = 80,
    occurrence_count: int = 1,
    suffix: str = "candidate",
) -> ImageToastCandidate:
    source_identity = {"file_id": suffix}
    source_location = ImageSourceLocation(
        source_format="docx",
        relationship_id=f"rId-{suffix}",
        metadata=metadata or {},
    )
    occurrences = tuple(
        ImageToastOccurrence(
            source_identity={**source_identity, "occurrence": index},
            source_location=source_location,
        )
        for index in range(occurrence_count)
    )
    return ImageToastCandidate(
        payload=f"payload-{suffix}".encode(),
        content_type="image/png",
        extension=".png",
        byte_size=len(f"payload-{suffix}"),
        checksum_sha256=f"{suffix:0<64}"[:64],
        width_px=width_px,
        height_px=height_px,
        source_identity=source_identity,
        source_location=source_location,
        occurrences=occurrences,
    )


def _document_artifact_from_name(name: str) -> DocumentInputArtifact:
    return DocumentInputArtifact(
        source_id="google-drive",
        stream="documents",
        file_id=Path(name).stem,
        source_path=f"Documents/{name}",
        object_path=f"/objects/documents/{name}",
        mime_type=_mime_type(Path(name).suffix.lower()),
        size_bytes=100,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        source_url=f"https://drive.example/{Path(name).stem}",
        metadata={"owner": "hr"},
        raw_record={"id": Path(name).stem},
        local_path=f"/tmp/{name}",
        input_kind="document",
        normalized_extension=Path(name).suffix.lower(),
        mime_family="word-processing",
    )


def _document_artifact(
    path: Path,
    mime_family: str,
    *,
    file_id: str | None = None,
) -> DocumentInputArtifact:
    return DocumentInputArtifact(
        source_id="google-drive",
        stream="documents",
        file_id=file_id or path.stem,
        source_path=f"Documents/{path.name}",
        object_path=f"/objects/documents/{path.name}",
        mime_type=_mime_type(path.suffix.lower()),
        size_bytes=path.stat().st_size,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        source_url=f"https://drive.example/{path.stem}",
        metadata={"owner": "hr"},
        raw_record={"id": file_id or path.stem},
        local_path=str(path),
        input_kind="document",
        normalized_extension=path.suffix.lower(),
        mime_family=mime_family,
    )


def _mime_type(extension: str) -> str:
    return {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pdf": "application/pdf",
    }[extension]


class _FakeMarkItDown:
    def __init__(self, markdown: str) -> None:
        self.markdown = markdown

    def convert(self, path: str | Path) -> object:
        return _FakeMarkItDownResult(self.markdown)


class _FakeMarkItDownResult:
    def __init__(self, markdown: str) -> None:
        self.markdown = markdown
