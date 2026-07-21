"""Markdown and TOAST metadata public API."""

# NOTE(task-1): trimmed — output, profile, render, table_data, table_markdown, toast
# impl modules arrive in later tasks. Restore full exports when those modules are added.
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

__all__ = [
    "ColumnProfile",
    "DocumentOutputBundle",
    "MarkdownTableLocation",
    "RunOutputManifest",
    "TableData",
    "TableDataExtractionResult",
    "TableProfile",
    "ToastDecision",
    "WorkbookOutputBundle",
    "XlsxTableLocation",
    # trimmed: "MarkdownTableExtractionResult",  # markdown/table_markdown.py
    # trimmed: "MarkdownTableOccurrence",         # markdown/table_markdown.py
    # trimmed: "MetadataConfig",                  # markdown/output.py
    # trimmed: "build_document_output_bundle",    # markdown/output.py
    # trimmed: "build_embedding_metadata",        # markdown/output.py
    # trimmed: "build_full_metadata",             # markdown/output.py
    # trimmed: "build_workbook_output_bundle",    # markdown/output.py
    # trimmed: "ToastThresholds",                 # markdown/toast.py
    # trimmed: "classify_table",                  # markdown/toast.py
    # trimmed: "content_signature",               # markdown/toast.py
    # trimmed: "extract_table_data",              # markdown/table_data.py
    # trimmed: "extract_markdown_document_tables",# markdown/table_markdown.py
    # trimmed: "profile_table",                   # markdown/profile.py
    # trimmed: "metadata_json_bytes",             # markdown/output.py
    # trimmed: "render_workbook_markdown",        # markdown/render.py
    # trimmed: "render_toast_reference",          # markdown/toast.py
    # trimmed: "toast_id",                        # markdown/toast.py
    # trimmed: "write_document_outputs",          # markdown/output.py
    # trimmed: "write_run_manifest",              # markdown/output.py
    # trimmed: "write_workbook_outputs",          # markdown/output.py
]
