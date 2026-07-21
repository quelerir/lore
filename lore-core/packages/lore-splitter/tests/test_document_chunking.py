from lore_splitter.documents.chunking import (
    build_document_chunks,
    parse_markdown_blocks,
)


def test_parser_preserves_heading_hierarchy_and_source_order():
    blocks = parse_markdown_blocks("# Root\n\nIntro\n\n## Child\n\nBody\n")
    assert [block.kind for block in blocks] == ["heading", "paragraph", "heading", "paragraph"]
    assert blocks[1].heading_path == ("Root",)
    assert blocks[3].heading_path == ("Root", "Child")


def test_document_chunks_repeat_heading_context_and_keep_display_source_like():
    result = build_document_chunks(
        run_id="run-a",
        file_id="file-a",
        markdown="# Root\n\nBody text.\n\n## Child\n\nChild text.",
        pipeline_type="docx",
    )
    assert result.diagnostics == ()
    assert result.chunks[1].display_text == "Body text.\n"
    assert result.chunks[1].vector_text.startswith("# Root\n")
    assert result.chunks[3].vector_text.startswith("# Root\n\n## Child\n")


def test_equivalent_content_signatures_are_stable_across_runs():
    first = build_document_chunks(run_id="run-a", file_id="file-a", markdown="# A\n\nText")
    second = build_document_chunks(run_id="run-b", file_id="file-b", markdown="# A\n\nText")
    assert first.chunks[1].content_signature == second.chunks[1].content_signature
    assert first.chunks[1].chunk_id != second.chunks[1].chunk_id
