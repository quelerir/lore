from __future__ import annotations

from lore_splitter.documents.contracts import (
    DocumentInputArtifact,
    DocumentMarkdownResult,
)
from lore_splitter.markdown import (
    MarkdownTableExtractionResult,
    MarkdownTableOccurrence,
)
from lore_splitter.markdown.table_markdown import (
    SKIP_MARKER_UNSUPPORTED_HTML_TABLE,
    ToastThresholds,
    extract_markdown_document_tables,
)


def test_pipe_tables_emit_document_table_data_and_markdown_location() -> None:
    document = _document(
        """Intro

| Region | Amount |
| --- | ---: |
| North | 10 |
| South | 25 |

After
"""
    )

    result = extract_markdown_document_tables((document,))

    assert len(result.tables) == 1
    table = result.tables[0]
    assert table.source_kind == "document"
    assert table.source_checksum == document.document_checksum
    assert table.table_index == 1
    assert table.columns == ("Region", "Amount")
    assert table.rows == (("Region", "Amount"), ("North", "10"), ("South", "25"))
    assert table.markdown is not None
    assert table.markdown.to_dict() == {"table_index": 1, "line_start": 3, "line_end": 6}
    assert table.xlsx is None
    assert result.documents[0].markdown == document.markdown
    assert result.diagnostics == ()


def test_code_fences_links_and_paragraph_pipes_are_preserved_not_tables() -> None:
    document = _document(
        """Before

```markdown
| Code | Fence |
| --- | --- |
| A | B |
```

See [a | b](https://example.test) and text | with | pipes.
"""
    )

    result = extract_markdown_document_tables((document,))

    assert result.tables == ()
    assert result.documents[0].markdown == document.markdown
    assert result.diagnostics == ()


def test_simple_html_tables_are_extracted_with_line_metadata() -> None:
    document = _document(
        """Before

<table>
<thead><tr><th>Name</th><th>Score</th></tr></thead>
<tbody><tr><td>Ada</td><td>9</td></tr><tr><td>Lin</td><td>8</td></tr></tbody>
</table>

After
"""
    )

    result = extract_markdown_document_tables((document,))

    assert len(result.tables) == 1
    table = result.tables[0]
    assert table.columns == ("Name", "Score")
    assert table.rows == (("Name", "Score"), ("Ada", "9"), ("Lin", "8"))
    assert table.markdown is not None
    assert table.markdown.line_start == 3
    assert table.markdown.line_end == 6
    assert result.documents[0].markdown == document.markdown
    assert result.diagnostics == ()


def test_unsupported_complex_html_table_is_replaced_with_skip_marker_and_diagnostic() -> None:
    document = _document(
        """Before

<table>
<tr><th>Name</th><th>Score</th></tr>
<tr><td rowspan="2">Ada</td><td>9</td></tr>
<tr><td>8</td></tr>
</table>

After
"""
    )

    result = extract_markdown_document_tables((document,))

    assert result.tables == ()
    assert result.documents[0].markdown == (
        f"Before\n\n{SKIP_MARKER_UNSUPPORTED_HTML_TABLE}\n\nAfter\n"
    )
    assert len(result.occurrences) == 1
    skipped = result.occurrences[0]
    assert skipped.skip_reason == "unsupported_html_table"
    assert skipped.location.to_dict() == {"table_index": 1, "line_start": 3, "line_end": 7}
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].reason == "unsupported_html_table"
    assert "line 3-7" in result.diagnostics[0].message


def test_extraction_contracts_are_available_from_markdown_public_api() -> None:
    assert MarkdownTableExtractionResult.__name__ == "MarkdownTableExtractionResult"
    assert MarkdownTableOccurrence.__name__ == "MarkdownTableOccurrence"


def test_inline_tables_preserve_original_author_markdown_formatting() -> None:
    document = _document(
        """Before

| Region | Amount |
| :--- | ---: |
| North | 10 |
| South | 25 |

After
"""
    )

    result = extract_markdown_document_tables((document,))

    assert result.documents[0].markdown == document.markdown
    assert result.decisions[0].classification == "inline"
    assert result.decisions[0].toast_id is None


def test_toast_tables_are_replaced_by_id_only_marker_without_summary_or_location() -> None:
    document = _document(
        """Before

| Region | Narrative |
| --- | --- |
| North | long narrative cell long narrative cell |
| South | another long narrative cell |

After
"""
    )

    result = extract_markdown_document_tables(
        (document,),
        thresholds=ToastThresholds(max_inline_markdown_bytes=80),
    )

    decision = result.decisions[0]
    assert decision.classification == "toast"
    assert decision.toast_id is not None
    assert result.documents[0].markdown == f"Before\n\n[TOAST: {decision.toast_id}]\n\nAfter\n"
    marker = f"[TOAST: {decision.toast_id}]"
    assert "Policies/source.md" not in marker
    assert "line" not in marker
    assert "Region" not in result.documents[0].markdown
    assert "Narrative" not in result.documents[0].markdown


def test_duplicate_identical_tables_share_toast_id_but_keep_occurrence_locations() -> None:
    table = """| Region | Narrative |
| --- | --- |
| North | long narrative cell long narrative cell |
| South | another long narrative cell |
"""
    document = _document(f"First\n\n{table}\nMiddle\n\n{table}\nLast\n")

    first = extract_markdown_document_tables(
        (document,),
        thresholds=ToastThresholds(max_inline_markdown_bytes=80),
    )
    second = extract_markdown_document_tables(
        (document,),
        thresholds=ToastThresholds(max_inline_markdown_bytes=80),
    )

    assert len(first.tables) == 2
    assert len(first.unique_tables) == 1
    assert first.decisions[0].toast_id == first.decisions[1].toast_id
    assert [occurrence.location.line_start for occurrence in first.occurrences] == [3, 10]
    assert [occurrence.location.line_end for occurrence in first.occurrences] == [6, 13]
    assert first.documents[0].markdown.count(f"[TOAST: {first.decisions[0].toast_id}]") == 2
    assert first.documents[0].markdown == second.documents[0].markdown
    assert [decision.to_dict() for decision in first.decisions] == [
        decision.to_dict() for decision in second.decisions
    ]
    assert [occurrence.to_dict() for occurrence in first.occurrences] == [
        occurrence.to_dict() for occurrence in second.occurrences
    ]


def _document(markdown: str) -> DocumentMarkdownResult:
    source = DocumentInputArtifact(
        source_id="google-drive",
        stream="regulations",
        file_id="doc-123",
        source_path="Policies/source.md",
        object_path="/staging/files/source__doc-123.md",
        mime_type="text/markdown",
        size_bytes=len(markdown.encode("utf-8")),
        created_at=None,
        updated_at=None,
        source_url=None,
        metadata={},
        raw_record={},
        local_path="/tmp/materialized/staging/files/source__doc-123.md",
        input_kind="document",
        normalized_extension=".md",
        mime_family="markdown",
    )
    return DocumentMarkdownResult(
        source=source,
        document_format="markdown",
        markdown=markdown,
        document_checksum="d" * 64,
    )
