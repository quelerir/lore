from __future__ import annotations

from pathlib import Path

from lore_splitter.contracts import ManifestDiagnostic
from lore_splitter.documents.contracts import (
    DocumentInputArtifact,
    DocumentMarkdownResult,
)
from lore_splitter.documents.normalize import normalize_markdown_source


def test_normalize_markdown_source_only_normalizes_line_endings_and_final_newline() -> None:
    source = "# Title\r\n\r\n- One\r\n- Two\r\n\r\n```python\r\nprint('hi')\r\n```\r"

    assert normalize_markdown_source(source) == (
        "# Title\n\n- One\n- Two\n\n```python\nprint('hi')\n```\n"
    )


def test_normalize_markdown_source_preserves_markdown_constructs_byte_for_byte() -> None:
    markdown = "\n".join(
        [
            "# Policy",
            "",
            "## Details",
            "",
            "- Keep headings",
            "- Keep [links](https://example.com?q=1|2)",
            "",
            "```sql",
            "select 'a|b' as value;",
            "```",
            "",
            "| Region | Amount |",
            "| --- | ---: |",
            "| North | 10 |",
            "",
            "![diagram](images/flow.png)",
        ]
    )

    assert normalize_markdown_source(markdown) == f"{markdown}\n"


def test_document_markdown_result_serializes_source_markdown_and_diagnostics() -> None:
    diagnostic = ManifestDiagnostic(
        reason="weak_heading_structure",
        message="Only one heading was detected",
        source_id="google-drive",
        stream="policies",
        file_id="doc-123",
        source_path="Policies/source.md",
        object_path="/objects/policies/source.md",
    )
    result = DocumentMarkdownResult(
        source=_document_artifact(),
        document_format="markdown",
        markdown="# Policy\n\nBody\n",
        document_checksum="b" * 64,
        warnings=("weak_heading_structure",),
        diagnostics=(diagnostic,),
        structure_signals={"headings": ["Policy"], "title": "Policy"},
    )

    assert result.to_dict() == {
        "source": _document_artifact().to_dict(),
        "source_identity": {
            "source_id": "google-drive",
            "stream": "policies",
            "file_id": "doc-123",
            "source_path": "Policies/source.md",
            "object_path": "/objects/policies/source.md",
        },
        "local_path": "/tmp/materialized/policies/source.md",
        "normalized_extension": ".md",
        "document_format": "markdown",
        "markdown": "# Policy\n\nBody\n",
        "document_checksum": "b" * 64,
        "warnings": ["weak_heading_structure"],
        "diagnostics": [diagnostic.to_dict()],
        "structure_signals": {"headings": ["Policy"], "title": "Policy"},
        "image_candidates": [],
    }


def _document_artifact(
    *,
    file_id: str = "doc-123",
    source_path: str = "Policies/source.md",
    object_path: str = "/objects/policies/source.md",
) -> DocumentInputArtifact:
    return DocumentInputArtifact(
        source_id="google-drive",
        stream="policies",
        file_id=file_id,
        source_path=source_path,
        object_path=object_path,
        mime_type="text/markdown",
        size_bytes=128,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        source_url="https://drive.example/doc-123",
        metadata={"owner": "hr"},
        raw_record={"id": file_id},
        local_path=str(Path("/tmp/materialized/policies/source.md")),
        input_kind="document",
        normalized_extension=".md",
        mime_family="markdown",
    )
