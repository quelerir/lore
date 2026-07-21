"""Markdown and TOAST metadata public API."""

# NOTE(task-1): output, render, table_data, table_markdown impl deferred.
# NOTE(task-2): profile.py and toast.py added to support storage layer tests.
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
from lore_splitter.markdown.profile import profile_table
from lore_splitter.markdown.toast import (
    ToastThresholds,
    classify_table,
    content_signature,
    toast_id,
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
    "ToastThresholds",
    "WorkbookOutputBundle",
    "XlsxTableLocation",
    "classify_table",
    "content_signature",
    "profile_table",
    "toast_id",
    # trimmed: "MarkdownTableExtractionResult",  # markdown/table_markdown.py
    # trimmed: "MarkdownTableOccurrence",         # markdown/table_markdown.py
    # trimmed: "MetadataConfig",                  # markdown/output.py
    # trimmed: "build_document_output_bundle",    # markdown/output.py
    # trimmed: "build_embedding_metadata",        # markdown/output.py
    # trimmed: "build_full_metadata",             # markdown/output.py
    # trimmed: "build_workbook_output_bundle",    # markdown/output.py
    # trimmed: "extract_table_data",              # markdown/table_data.py
    # trimmed: "extract_markdown_document_tables",# markdown/table_markdown.py
    # trimmed: "metadata_json_bytes",             # markdown/output.py
    # trimmed: "render_workbook_markdown",        # markdown/render.py
    # trimmed: "render_toast_reference",          # markdown/toast.py
    # trimmed: "write_document_outputs",          # markdown/output.py
    # trimmed: "write_run_manifest",              # markdown/output.py
    # trimmed: "write_workbook_outputs",          # markdown/output.py
]
