"""Markdown and TOAST metadata public API."""

from lore_splitter.markdown.contracts import (
    ColumnProfile,
    DocumentOutputBundle,
    MarkdownTableLocation,
    RunOutputManifest,
    TableData,
    TableDataExtractionResult,
    TableProfile,
    ToastDecision,
    WorkbookOutputBundle,
    XlsxTableLocation,
)
from lore_splitter.markdown.output import (
    MetadataConfig,
    build_document_output_bundle,
    build_embedding_metadata,
    build_full_metadata,
    build_workbook_output_bundle,
    metadata_json_bytes,
    write_document_outputs,
    write_run_manifest,
    write_workbook_outputs,
)
from lore_splitter.markdown.profile import profile_table
from lore_splitter.markdown.render import render_workbook_markdown
from lore_splitter.markdown.table_data import extract_table_data
from lore_splitter.markdown.table_markdown import (
    MarkdownTableExtractionResult,
    MarkdownTableOccurrence,
    extract_markdown_document_tables,
)
from lore_splitter.markdown.toast import (
    ToastThresholds,
    classify_table,
    content_signature,
    render_toast_reference,
    toast_id,
)

__all__ = [
    "ColumnProfile",
    "DocumentOutputBundle",
    "MarkdownTableLocation",
    "MarkdownTableExtractionResult",
    "MarkdownTableOccurrence",
    "MetadataConfig",
    "RunOutputManifest",
    "TableData",
    "TableDataExtractionResult",
    "TableProfile",
    "ToastDecision",
    "WorkbookOutputBundle",
    "XlsxTableLocation",
    "build_document_output_bundle",
    "build_embedding_metadata",
    "build_full_metadata",
    "build_workbook_output_bundle",
    "ToastThresholds",
    "classify_table",
    "content_signature",
    "extract_table_data",
    "extract_markdown_document_tables",
    "profile_table",
    "metadata_json_bytes",
    "render_workbook_markdown",
    "render_toast_reference",
    "toast_id",
    "write_document_outputs",
    "write_run_manifest",
    "write_workbook_outputs",
]
