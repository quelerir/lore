from __future__ import annotations

import hashlib
from io import BytesIO

from PIL import Image

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover - older PyMuPDF import path.
    import fitz

from lore_splitter.documents.contracts import (
    DocumentInputArtifact,
    ImageSourceLocation,
    ImageToastCandidate,
)


def extract_pdf_images(document: DocumentInputArtifact) -> tuple[ImageToastCandidate, ...]:
    candidates: list[ImageToastCandidate] = []
    doc = fitz.open(document.local_path)
    try:
        for page_index in range(doc.page_count):
            page = doc[page_index]
            for info in page.get_images(full=True):
                xref = info[0]
                extracted = doc.extract_image(xref)
                payload = extracted.get("image", b"")
                if not payload:
                    continue
                rects = page.get_image_rects(xref)
                if not rects:
                    rects = [None]
                for rect in rects:
                    bbox = None
                    if rect is not None:
                        bbox = (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))
                    width, height = _image_size(
                        payload,
                        extracted.get("width"),
                        extracted.get("height"),
                    )
                    ext = extracted.get("ext") or "bin"
                    candidates.append(
                        ImageToastCandidate(
                            payload=payload,
                            content_type=_content_type(ext),
                            extension=f".{ext}",
                            byte_size=len(payload),
                            checksum_sha256=hashlib.sha256(payload).hexdigest(),
                            width_px=width,
                            height_px=height,
                            source_identity=document.source_identity,
                            source_location=ImageSourceLocation(
                                source_format="pdf",
                                page_number=page_index + 1,
                                bbox=bbox,
                                metadata={"xref": xref},
                            ),
                        )
                    )
    finally:
        doc.close()
    return tuple(candidates)


def _image_size(
    payload: bytes,
    width: int | None,
    height: int | None,
) -> tuple[int | None, int | None]:
    if width and height:
        return int(width), int(height)
    with Image.open(BytesIO(payload)) as image:
        return image.size


def _content_type(extension: str) -> str:
    normalized = extension.lower().lstrip(".")
    return "image/jpeg" if normalized in {"jpg", "jpeg"} else f"image/{normalized}"
