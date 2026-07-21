from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


@dataclass(frozen=True)
class DocumentContractFixtures:
    docx: Path
    pptx: Path
    pdf: Path
    empty_pdf: Path
    corrupt: Path


def create_document_contract_fixtures(root: Path) -> DocumentContractFixtures:
    root.mkdir(parents=True, exist_ok=True)
    docx = root / "contract-policy.docx"
    pptx = root / "contract-slides.pptx"
    pdf = root / "contract-manual.pdf"
    empty_pdf = root / "empty-manual.pdf"
    corrupt = root / "corrupt-document.docx"

    _write_docx(docx)
    _write_pptx(pptx)
    _write_text_pdf(
        pdf,
        (
            "Contract Manual\n"
            "Page 1 contains deterministic PDF text for document conversion.\n"
            "Page 2 contains a second reading-order marker.\n"
        ),
    )
    _write_text_pdf(empty_pdf, "")
    corrupt.write_bytes(b"not a valid office document or pdf")

    return DocumentContractFixtures(
        docx=docx,
        pptx=pptx,
        pdf=pdf,
        empty_pdf=empty_pdf,
        corrupt=corrupt,
    )


def _write_docx(path: Path) -> None:
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" '
            'Target="word/document.xml"/>'
            "</Relationships>"
        ),
        "word/document.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>Contract Policy</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>"
            "Deterministic DOCX body text for MarkItDown conversion."
            "</w:t></w:r></w:p>"
            "<w:sectPr/></w:body></w:document>"
        ),
    }
    _write_zip(path, files)


def _write_pptx(path: Path) -> None:
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/ppt/presentation.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            '<Override PartName="/ppt/slides/slide1.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" '
            'Target="ppt/presentation.xml"/>'
            "</Relationships>"
        ),
        "ppt/presentation.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            "<p:sldIdLst><p:sldId id=\"256\" r:id=\"rId1\"/></p:sldIdLst>"
            '<p:sldSz cx="9144000" cy="6858000" type="screen4x3"/>'
            '<p:notesSz cx="6858000" cy="9144000"/>'
            "</p:presentation>"
        ),
        "ppt/_rels/presentation.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
            'Target="slides/slide1.xml"/>'
            "</Relationships>"
        ),
        "ppt/slides/slide1.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            "<p:cSld><p:spTree>"
            "<p:nvGrpSpPr>"
            '<p:cNvPr id="1" name=""/>'
            "<p:cNvGrpSpPr/>"
            "<p:nvPr/>"
            "</p:nvGrpSpPr>"
            "<p:grpSpPr>"
            "<a:xfrm>"
            '<a:off x="0" y="0"/>'
            '<a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/>'
            '<a:chExt cx="0" cy="0"/>'
            "</a:xfrm>"
            "</p:grpSpPr>"
            "<p:sp>"
            "<p:nvSpPr>"
            '<p:cNvPr id="2" name="Title 1"/>'
            "<p:cNvSpPr/>"
            "<p:nvPr/>"
            "</p:nvSpPr>"
            "<p:spPr>"
            "<a:xfrm>"
            '<a:off x="914400" y="914400"/>'
            '<a:ext cx="7315200" cy="1828800"/>'
            "</a:xfrm>"
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            "</p:spPr>"
            "<p:txBody><a:bodyPr/><a:lstStyle/>"
            "<a:p><a:r><a:t>Slide 1: Conversion Contract</a:t></a:r></a:p>"
            "<a:p><a:r><a:t>Deterministic PPTX body text.</a:t></a:r></a:p>"
            "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
        ),
    }
    _write_zip(path, files)


def _write_text_pdf(path: Path, text: str) -> None:
    stream = _pdf_escape(text)
    content = f"BT /F1 12 Tf 72 720 Td ({stream}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 4 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Length "
            + str(len(content)).encode("ascii")
            + b" >>\nstream\n"
            + content
            + b"\nendstream"
        ),
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(bytes(output))


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\n", "\\n")


def _write_zip(path: Path, files: dict[str, str]) -> None:
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.writestr(name, files[name])
