from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from lore_splitter.contracts import ManifestDiagnostic

if TYPE_CHECKING:
    from lore_splitter.resolver import ResolvedInput


@dataclass(frozen=True)
class DocumentInputArtifact:
    source_id: str
    stream: str
    file_id: str
    source_path: str
    object_path: str
    mime_type: str
    size_bytes: int
    created_at: str | None
    updated_at: str | None
    source_url: str | None
    metadata: dict[str, Any]
    raw_record: dict[str, Any]
    local_path: str
    input_kind: str
    normalized_extension: str
    mime_family: str

    @property
    def source_identity(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "stream": self.stream,
            "file_id": self.file_id,
            "source_path": self.source_path,
            "object_path": self.object_path,
        }

    @classmethod
    def from_resolved_input(cls, resolved_input: ResolvedInput) -> DocumentInputArtifact:
        payload = resolved_input.to_dict()
        return cls(
            source_id=payload["source_id"],
            stream=payload["stream"],
            file_id=payload["file_id"],
            source_path=payload["source_path"],
            object_path=payload["object_path"],
            mime_type=payload["mime_type"],
            size_bytes=payload["size_bytes"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            source_url=payload["source_url"],
            metadata=payload["metadata"],
            raw_record=payload["raw_record"],
            local_path=payload["local_path"],
            input_kind=payload["input_kind"],
            normalized_extension=payload["normalized_extension"],
            mime_family=payload["mime_family"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "stream": self.stream,
            "file_id": self.file_id,
            "source_path": self.source_path,
            "object_path": self.object_path,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_url": self.source_url,
            "metadata": self.metadata,
            "raw_record": self.raw_record,
            "local_path": self.local_path,
            "input_kind": self.input_kind,
            "normalized_extension": self.normalized_extension,
            "mime_family": self.mime_family,
        }


@dataclass(frozen=True)
class DocumentRoutingResult:
    documents: tuple[DocumentInputArtifact, ...]
    diagnostics: tuple[ManifestDiagnostic, ...] = ()


@dataclass(frozen=True)
class DocumentMarkdownResult:
    source: DocumentInputArtifact
    document_format: str
    markdown: str
    document_checksum: str
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[ManifestDiagnostic, ...] = ()
    structure_signals: dict[str, Any] | None = None
    image_candidates: tuple[ImageToastCandidate, ...] = ()

    @property
    def source_identity(self) -> dict[str, Any]:
        return self.source.source_identity

    @property
    def local_path(self) -> str:
        return self.source.local_path

    @property
    def normalized_extension(self) -> str:
        return self.source.normalized_extension

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "source_identity": self.source_identity,
            "local_path": self.local_path,
            "normalized_extension": self.normalized_extension,
            "document_format": self.document_format,
            "markdown": self.markdown,
            "document_checksum": self.document_checksum,
            "warnings": list(self.warnings),
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "structure_signals": dict(self.structure_signals or {}),
            "image_candidates": [candidate.to_dict() for candidate in self.image_candidates],
        }


@dataclass(frozen=True)
class DocumentMarkdownConversionResult:
    documents: tuple[DocumentMarkdownResult, ...] = ()
    diagnostics: tuple[ManifestDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "documents": [document.to_dict() for document in self.documents],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


def route_document_inputs(
    resolved_inputs: Iterable[ResolvedInput],
) -> DocumentRoutingResult:
    return DocumentRoutingResult(
        documents=tuple(
            DocumentInputArtifact.from_resolved_input(resolved_input)
            for resolved_input in resolved_inputs
            if resolved_input.input_kind == "document"
        ),
    )


@dataclass(frozen=True)
class ImageSourceLocation:
    source_format: str
    page_number: int | None = None
    slide_number: int | None = None
    relationship_id: str | None = None
    shape_id: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        details: dict[str, Any] = {}
        if self.page_number is not None:
            details["page"] = self.page_number
        if self.slide_number is not None:
            details["slide"] = self.slide_number
        if self.relationship_id is not None:
            details["relationship_id"] = self.relationship_id
        if self.shape_id is not None:
            details["shape_id"] = self.shape_id
        if self.bbox is not None:
            details["bbox"] = list(self.bbox)
        details.update(dict(self.metadata or {}))
        return {self.source_format: details}


@dataclass(frozen=True)
class ImageToastOccurrence:
    source_identity: dict[str, Any]
    source_location: ImageSourceLocation

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_identity": dict(self.source_identity),
            "source_location": self.source_location.to_dict(),
        }


@dataclass(frozen=True)
class ImageToastCandidate:
    payload: bytes
    content_type: str
    extension: str
    byte_size: int
    checksum_sha256: str
    width_px: int | None
    height_px: int | None
    source_identity: dict[str, Any]
    source_location: ImageSourceLocation
    occurrences: tuple[ImageToastOccurrence, ...] = ()
    toast_id: str = ""
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        normalized_extension = (
            self.extension if self.extension.startswith(".") else f".{self.extension}"
        )
        object.__setattr__(self, "extension", normalized_extension.lower())
        if not self.toast_id:
            signature = hashlib.sha256(
                b"\0".join(
                    (
                        self.payload,
                        self.content_type.strip().lower().encode("utf-8"),
                        self.extension.strip().lower().lstrip(".").encode("utf-8"),
                    )
                )
            ).hexdigest()
            object.__setattr__(self, "toast_id", f"toast_img_{signature[:20]}")
        if not self.occurrences:
            object.__setattr__(
                self,
                "occurrences",
                (
                    ImageToastOccurrence(
                        source_identity=self.source_identity,
                        source_location=self.source_location,
                    ),
                ),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "toast_id": self.toast_id,
            "content_type": self.content_type,
            "extension": self.extension,
            "byte_size": self.byte_size,
            "checksum_sha256": self.checksum_sha256,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "source_identity": dict(self.source_identity),
            "source_location": self.source_location.to_dict(),
            "occurrences": [occurrence.to_dict() for occurrence in self.occurrences],
            "warnings": list(self.warnings),
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class ImageSkip:
    candidate: ImageToastCandidate
    reason: str
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "reason": self.reason,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class DocumentImageExtractionResult:
    candidates: tuple[ImageToastCandidate, ...] = ()
    unique_candidates: tuple[ImageToastCandidate, ...] = ()
    occurrences: tuple[ImageToastOccurrence, ...] = ()
    skips: tuple[ImageSkip, ...] = ()
    diagnostics: tuple[ManifestDiagnostic, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "unique_candidates": [candidate.to_dict() for candidate in self.unique_candidates],
            "occurrences": [occurrence.to_dict() for occurrence in self.occurrences],
            "skips": [skip.to_dict() for skip in self.skips],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "warnings": list(self.warnings),
        }
