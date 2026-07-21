from __future__ import annotations

# NOTE(task-1): trimmed — chunking, conversion, external_images, images impl modules
# arrive in later tasks. Restore full exports when those modules are added.
from lore_splitter.documents.contracts import (
    DocumentImageExtractionResult,
    DocumentInputArtifact,
    DocumentMarkdownConversionResult,
    DocumentMarkdownResult,
    DocumentRoutingResult,
    ImageSkip,
    ImageSourceLocation,
    ImageToastCandidate,
    ImageToastOccurrence,
    route_document_inputs,
)
from lore_splitter.documents.normalize import normalize_markdown_source

__all__ = [
    "DocumentImageExtractionResult",
    "DocumentInputArtifact",
    "DocumentMarkdownConversionResult",
    "DocumentMarkdownResult",
    "DocumentRoutingResult",
    "ImageSkip",
    "ImageSourceLocation",
    "ImageToastCandidate",
    "ImageToastOccurrence",
    "normalize_markdown_source",
    "route_document_inputs",
    # trimmed: "DocumentBlock",              # documents/chunking.py
    # trimmed: "DocumentChunkResult",        # documents/chunking.py
    # trimmed: "build_document_chunks",      # documents/chunking.py
    # trimmed: "parse_markdown_blocks",      # documents/chunking.py
    # trimmed: "FetchedImage",               # documents/external_images.py
    # trimmed: "fetch_external_image",       # documents/external_images.py
    # trimmed: "DocumentMarkdownConverter",  # documents/conversion.py
    # trimmed: "convert_document_inputs",    # documents/conversion.py
    # trimmed: "build_image_storage_plans",  # documents/images.py
    # trimmed: "classify_image_candidate",   # documents/images.py
    # trimmed: "extract_document_images",    # documents/images.py
]
