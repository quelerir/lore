"""Markdown/document output bundle + run-manifest builders.

Re-export shim: the implementation lives in ``_impl`` (moved intact from the
former single-file ``output.py``). A clean by-concern split was assessed but
deferred — the workbook/document/metadata paths share a dense web of private
helpers (``_storage_*``, ``_manifest_*``, ``_add_*``) whose partitioning risks
behavior for pure layout gain. Public import path ``lore_splitter.markdown.output``
is preserved by re-exporting the module's full (public) surface, identical to the
former single file.
"""

from lore_splitter.markdown.output._impl import *  # noqa: F401,F403
from lore_splitter.markdown.output._impl import (  # noqa: F401
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

__all__ = [
    "MetadataConfig",
    "build_document_output_bundle",
    "build_embedding_metadata",
    "build_full_metadata",
    "build_workbook_output_bundle",
    "metadata_json_bytes",
    "write_document_outputs",
    "write_run_manifest",
    "write_workbook_outputs",
]
