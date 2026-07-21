from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from lore_splitter.contracts import ManifestDiagnostic, SourceFile
from lore_splitter.documents.contracts import (
    DocumentImageExtractionResult,
    DocumentInputArtifact,
    DocumentMarkdownResult,
    ImageSkip,
    ImageToastCandidate,
    ImageToastOccurrence,
)
from lore_splitter.documents.pdf_images import extract_pdf_images
from lore_splitter.storage import (
    ImageToastStoragePlan,
    image_object_key,
)

PAGE_WIDTH = 612.0
PAGE_HEIGHT = 792.0
DECORATIVE_IMAGE_ROLES = {
    "repeated_decorative": "repeated_decorative",
    "background": "background_candidate",
    "background_candidate": "background_candidate",
    "icon": "icon_candidate",
    "bullet": "icon_candidate",
    "separator": "separator_candidate",
    "low_information": "low_information",
    "scanned_layer": "scanned_layer",
}
REPEATED_DECORATIVE_MAX_AREA_PX = 16_384


def extract_document_images(
    documents: Iterable[DocumentMarkdownResult],
) -> DocumentImageExtractionResult:
    candidates: list[ImageToastCandidate] = []
    diagnostics: list[ManifestDiagnostic] = []
    for document in documents:
        candidates.extend(document.image_candidates)
        if document.normalized_extension.lower() == ".pdf":
            try:
                candidates.extend(extract_pdf_images(document.source))
            except Exception as exc:  # noqa: BLE001 - source-scoped document diagnostic.
                diagnostics.append(
                    _source_diagnostic(
                        document.source,
                        "image_extraction_failed",
                        f"Could not extract PDF images: {exc}",
                    )
                )

    unique_by_toast_id: dict[str, ImageToastCandidate] = {}
    occurrences_by_toast_id: dict[str, list[ImageToastOccurrence]] = {}
    skips: list[ImageSkip] = []

    for candidate in candidates:
        reason = classify_image_candidate(candidate)
        if reason is not None:
            skips.append(ImageSkip(candidate=candidate, reason=reason, diagnostics=(reason,)))
            continue
        occurrences_by_toast_id.setdefault(candidate.toast_id, []).extend(candidate.occurrences)
        if candidate.toast_id not in unique_by_toast_id:
            unique_by_toast_id[candidate.toast_id] = candidate

    for toast_id, occurrences in occurrences_by_toast_id.items():
        unique_by_toast_id[toast_id] = replace(
            unique_by_toast_id[toast_id],
            occurrences=tuple(occurrences),
        )

    unique_candidates = tuple(unique_by_toast_id.values())
    return DocumentImageExtractionResult(
        candidates=tuple(candidates),
        unique_candidates=unique_candidates,
        occurrences=tuple(
            occurrence
            for candidate in unique_candidates
            for occurrence in candidate.occurrences
        ),
        skips=tuple(skips),
        diagnostics=tuple(diagnostics),
    )


def classify_image_candidate(candidate: ImageToastCandidate) -> str | None:
    explicit_reason = _metadata_reason(candidate)
    if explicit_reason is not None:
        return explicit_reason
    area_ratio = _area_ratio(candidate)
    if area_ratio is not None and area_ratio > 0.75:
        return "full_page_raster"
    if candidate.width_px is not None and candidate.height_px is not None:
        pixel_area = candidate.width_px * candidate.height_px
        if candidate.width_px * candidate.height_px < 4096:
            return "decorative_tiny"
        if len(candidate.occurrences) >= 3 and pixel_area <= REPEATED_DECORATIVE_MAX_AREA_PX:
            return "repeated_decorative"
    return None


def build_image_storage_plans(
    result: DocumentImageExtractionResult,
    *,
    bucket: str,
) -> tuple[ImageToastStoragePlan, ...]:
    plans: list[ImageToastStoragePlan] = []
    for candidate in result.unique_candidates:
        plans.append(
            ImageToastStoragePlan(
                toast_id=candidate.toast_id,
                bucket=bucket,
                object_key=image_object_key(candidate.toast_id, candidate.extension),
                content_type=candidate.content_type,
                extension=candidate.extension,
                payload=candidate.payload,
                byte_size=candidate.byte_size,
                checksum_sha256=candidate.checksum_sha256,
                source=candidate.source_identity,
                source_kind="document_image",
                source_checksum=candidate.checksum_sha256,
                source_location=candidate.source_location.to_dict(),
                warnings=candidate.warnings,
                diagnostics=candidate.diagnostics,
            )
        )
    return tuple(plans)


def _area_ratio(candidate: ImageToastCandidate) -> float | None:
    bbox = candidate.source_location.bbox
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    return max(0.0, (x1 - x0) * (y1 - y0)) / (PAGE_WIDTH * PAGE_HEIGHT)


def _metadata_reason(candidate: ImageToastCandidate) -> str | None:
    metadata = candidate.source_location.metadata or {}
    role = str(metadata.get("image_role") or metadata.get("role") or "").strip().lower()
    if role in DECORATIVE_IMAGE_ROLES:
        return DECORATIVE_IMAGE_ROLES[role]
    for reason in candidate.diagnostics:
        normalized = reason.strip().lower()
        if normalized in DECORATIVE_IMAGE_ROLES.values():
            return normalized
    return None


def _source_diagnostic(
    document: DocumentInputArtifact,
    reason: str,
    message: str,
) -> ManifestDiagnostic:
    return ManifestDiagnostic.for_source(
        reason,
        message,
        SourceFile(
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
        ),
    )
