from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any


class InputKind(Enum):
    WORKBOOK = "workbook"
    DOCUMENT = "document"
    UNSUPPORTED = "unsupported"


WORKBOOK_EXTENSIONS = frozenset({".xlsx", ".xlsm"})
DOCUMENT_EXTENSIONS = frozenset({".md", ".markdown", ".docx", ".pptx", ".pdf"})
SUPPORTED_EXTENSIONS = WORKBOOK_EXTENSIONS | DOCUMENT_EXTENSIONS

MIME_FAMILY_SPREADSHEET = "spreadsheet"
MIME_FAMILY_MARKDOWN = "markdown"
MIME_FAMILY_WORD_PROCESSING = "word-processing"
MIME_FAMILY_PRESENTATION = "presentation"
MIME_FAMILY_PDF = "pdf"
MIME_FAMILY_GENERIC = "generic"
MIME_FAMILY_UNKNOWN = "unknown"


@dataclass(frozen=True)
class InputClassification:
    input_kind: InputKind
    normalized_extension: str
    mime_family: str


@dataclass(frozen=True)
class SourceFile:
    source_id: str
    stream: str
    file_id: str
    source_path: str
    object_path: str
    mime_type: str
    size_bytes: int
    created_at: str | None = None
    updated_at: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_record: dict[str, Any] = field(default_factory=dict)

    @property
    def extension(self) -> str:
        return PurePosixPath(self.object_path).suffix.lower()

    @property
    def input_classification(self) -> InputClassification:
        return classify_source_file(self)

    @property
    def input_kind(self) -> str:
        return self.input_classification.input_kind.value

    @property
    def normalized_extension(self) -> str:
        return self.input_classification.normalized_extension

    @property
    def mime_family(self) -> str:
        return self.input_classification.mime_family

    @property
    def is_supported(self) -> bool:
        return self.input_classification.input_kind is not InputKind.UNSUPPORTED

    def identity_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "stream": self.stream,
            "file_id": self.file_id,
            "source_path": self.source_path,
            "object_path": self.object_path,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.identity_dict(),
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source_url": self.source_url,
            "metadata": self.metadata,
            "raw_record": self.raw_record,
            "input_kind": self.input_kind,
            "normalized_extension": self.normalized_extension,
            "mime_family": self.mime_family,
        }


@dataclass(frozen=True)
class ManifestDiagnostic:
    reason: str
    message: str
    source_id: str | None = None
    stream: str | None = None
    file_id: str | None = None
    source_path: str | None = None
    object_path: str | None = None

    @classmethod
    def for_source(cls, reason: str, message: str, source_file: SourceFile) -> ManifestDiagnostic:
        return cls(reason=reason, message=message, **source_file.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "message": self.message,
            "source_id": self.source_id,
            "stream": self.stream,
            "file_id": self.file_id,
            "source_path": self.source_path,
            "object_path": self.object_path,
        }


@dataclass(frozen=True)
class RunSummary:
    total_records: int
    processed_files: int
    skipped_files: int
    missing_files: int
    invalid_records: int
    declared_size_bytes: int

    @classmethod
    def from_results(
        cls,
        processed: list[SourceFile],
        diagnostics: list[ManifestDiagnostic],
        *,
        declared_size_bytes: int,
    ) -> RunSummary:
        skipped = sum(1 for item in diagnostics if item.reason == "unsupported_type")
        missing = sum(1 for item in diagnostics if item.reason == "missing_local_file")
        invalid = sum(1 for item in diagnostics if item.reason == "invalid_record")
        return cls(
            total_records=len(processed) + len(diagnostics),
            processed_files=len(processed),
            skipped_files=skipped,
            missing_files=missing,
            invalid_records=invalid,
            declared_size_bytes=declared_size_bytes,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "total_records": self.total_records,
            "processed_files": self.processed_files,
            "skipped_files": self.skipped_files,
            "missing_files": self.missing_files,
            "invalid_records": self.invalid_records,
            "declared_size_bytes": self.declared_size_bytes,
        }


def classify_source_file(source_file: SourceFile) -> InputClassification:
    extension = source_file.extension
    if extension in WORKBOOK_EXTENSIONS:
        return InputClassification(
            input_kind=InputKind.WORKBOOK,
            normalized_extension=extension,
            mime_family=MIME_FAMILY_SPREADSHEET,
        )
    if extension in DOCUMENT_EXTENSIONS:
        return InputClassification(
            input_kind=InputKind.DOCUMENT,
            normalized_extension=extension,
            mime_family=_document_mime_family(extension, source_file.mime_type),
        )
    return InputClassification(
        input_kind=InputKind.UNSUPPORTED,
        normalized_extension=extension,
        mime_family=_unsupported_mime_family(source_file.mime_type)
        if not extension
        else MIME_FAMILY_UNKNOWN,
    )


def _document_mime_family(extension: str, mime_type: str) -> str:
    extension_family = {
        ".md": MIME_FAMILY_MARKDOWN,
        ".markdown": MIME_FAMILY_MARKDOWN,
        ".docx": MIME_FAMILY_WORD_PROCESSING,
        ".pptx": MIME_FAMILY_PRESENTATION,
        ".pdf": MIME_FAMILY_PDF,
    }[extension]
    normalized_mime = mime_type.strip().lower()
    if not normalized_mime or _is_generic_mime(normalized_mime):
        return extension_family

    if "markdown" in normalized_mime or normalized_mime in {"text/plain", "text/x-markdown"}:
        return MIME_FAMILY_MARKDOWN
    if "wordprocessingml" in normalized_mime:
        return MIME_FAMILY_WORD_PROCESSING
    if "presentationml" in normalized_mime:
        return MIME_FAMILY_PRESENTATION
    if normalized_mime == "application/pdf":
        return MIME_FAMILY_PDF
    return extension_family


def _unsupported_mime_family(mime_type: str) -> str:
    normalized_mime = mime_type.strip().lower()
    if not normalized_mime:
        return MIME_FAMILY_UNKNOWN
    if _is_generic_mime(normalized_mime):
        return MIME_FAMILY_GENERIC
    if "spreadsheetml" in normalized_mime or "ms-excel" in normalized_mime:
        return MIME_FAMILY_SPREADSHEET
    if "markdown" in normalized_mime:
        return MIME_FAMILY_MARKDOWN
    if "wordprocessingml" in normalized_mime:
        return MIME_FAMILY_WORD_PROCESSING
    if "presentationml" in normalized_mime:
        return MIME_FAMILY_PRESENTATION
    if normalized_mime == "application/pdf":
        return MIME_FAMILY_PDF
    return MIME_FAMILY_UNKNOWN


def _is_generic_mime(mime_type: str) -> bool:
    return mime_type in {"application/octet-stream", "binary/octet-stream"}
