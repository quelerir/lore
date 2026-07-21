import hashlib

from lore_splitter.documents.chunking import build_document_chunks


def test_large_markdown_table_has_resolvable_table_payload():
    markdown = "| name | value |\n| --- | --- |\n" + "".join(
        f"| row-{index} | {index} |\n" for index in range(60)
    )
    result = build_document_chunks(run_id="run", file_id="file", markdown=markdown)

    assert len(result.payload_plans) == 1
    reference = result.chunks[-1].payload_refs[0]
    assert reference.kind == "table"
    assert reference.compact() in result.chunks[-1].display_text
    assert result.chunks[-1].chunk_type == "text"
    assert any(chunk.chunk_type == "table_payload" for chunk in result.chunks)


def test_document_table_payload_uses_markdown_sha256_by_default():
    markdown = "| name | value |\n| --- | --- |\n" + "".join(
        f"| row-{index} | {index} |\n" for index in range(60)
    )

    result = build_document_chunks(run_id="run", file_id="google-file-id", markdown=markdown)

    assert result.payload_plans[0].source_checksum == hashlib.sha256(
        markdown.encode("utf-8")
    ).hexdigest()


def test_document_table_payload_accepts_converted_checksum_without_changing_toast_id():
    markdown = "| name | value |\n| --- | --- |\n" + "".join(
        f"| row-{index} | {index} |\n" for index in range(60)
    )
    converted_checksum = "a" * 64

    fallback = build_document_chunks(run_id="run-a", file_id="file-a", markdown=markdown)
    converted = build_document_chunks(
        run_id="run-b",
        file_id="file-b",
        markdown=markdown,
        document_checksum=converted_checksum,
    )

    assert converted.payload_plans[0].source_checksum == converted_checksum
    assert converted.payload_plans[0].toast_id == fallback.payload_plans[0].toast_id


def test_external_images_are_opt_in_and_injected():
    calls = []

    def fetch(url, limit):
        calls.append((url, limit))
        return b"image-bytes", "image/png"

    markdown = "![diagram](https://example.test/diagram.png)"
    disabled = build_document_chunks(
        run_id="run", file_id="file", markdown=markdown, image_fetcher=fetch
    )
    assert calls == []
    assert disabled.payload_plans == ()
    assert disabled.chunks[0].display_text == markdown + "\n"

    enabled = build_document_chunks(
        run_id="run",
        file_id="file",
        markdown=markdown,
        image_fetch_enabled=True,
        image_fetcher=fetch,
    )
    assert len(calls) == 1
    assert len(enabled.payload_plans) == 1
    assert enabled.chunks[0].payload_refs[0].kind == "image"


def test_external_image_failures_are_safe_source_diagnostics():
    def fail(_url, _limit):
        raise RuntimeError("secret=should-not-appear")

    result = build_document_chunks(
        run_id="run",
        file_id="file",
        markdown="![diagram](https://example.test/diagram.png)",
        image_fetch_enabled=True,
        image_fetcher=fail,
    )
    assert result.diagnostics[0]["code"] == "external_image_failed"
    assert "secret" not in str(result.diagnostics)
