"""Markdown-document table extraction (pipe + HTML tables).

Re-export shim: the implementation lives in ``_impl`` (moved intact from the
former single-file ``table_markdown.py``). A clean pipe/html/classify split was
assessed but deferred — the pipe and HTML candidate builders share the ``_Candidate``
type and a web of scanning helpers (``_scan_candidates``, ``_fenced_code_lines``,
``_split_pipe_row``), so partitioning risks behavior for pure layout gain. Public
import path ``lore_splitter.markdown.table_markdown`` is preserved by re-exporting
the module's full (public) surface, identical to the former single file.
"""

from lore_splitter.markdown.table_markdown._impl import *  # noqa: F401,F403
from lore_splitter.markdown.table_markdown._impl import (  # noqa: F401
    MarkdownTableExtractionResult,
    MarkdownTableOccurrence,
    extract_markdown_document_tables,
)

__all__ = [
    "MarkdownTableExtractionResult",
    "MarkdownTableOccurrence",
    "extract_markdown_document_tables",
]
