from lore_splitter.contracts import ManifestDiagnostic, RunSummary, SourceFile


def test_source_file_classifies_workbooks_documents_and_unsupported_extensions() -> None:
    cases = [
        (".xlsx", "workbook", "spreadsheet"),
        (".xlsm", "workbook", "spreadsheet"),
        (".md", "document", "markdown"),
        (".markdown", "document", "markdown"),
        (".docx", "document", "word-processing"),
        (".pptx", "document", "presentation"),
        (".pdf", "document", "pdf"),
        (".zip", "unsupported", "unknown"),
    ]

    for extension, input_kind, mime_family in cases:
        source_file = _source_file(
            f"file{extension}",
            mime_type="application/octet-stream" if input_kind == "document" else "",
        )

        assert source_file.normalized_extension == extension
        assert source_file.input_kind == input_kind
        assert source_file.mime_family == mime_family
        assert source_file.is_supported is (input_kind != "unsupported")


def test_source_file_classification_is_extension_first_for_weak_mime_metadata() -> None:
    weak_mime_records = [
        _source_file("policy.docx", mime_type=""),
        _source_file("slides.pptx", mime_type="application/octet-stream"),
        _source_file("manual.pdf", mime_type="binary/octet-stream"),
        _source_file("notes.md", mime_type="text/plain"),
    ]

    assert [source_file.input_kind for source_file in weak_mime_records] == [
        "document",
        "document",
        "document",
        "document",
    ]
    assert [source_file.mime_family for source_file in weak_mime_records] == [
        "word-processing",
        "presentation",
        "pdf",
        "markdown",
    ]


def test_legacy_doc_and_ppt_extensions_remain_unsupported() -> None:
    for filename in ("legacy.doc", "legacy.ppt"):
        source_file = _source_file(filename)

        assert source_file.input_kind == "unsupported"
        assert source_file.normalized_extension in {".doc", ".ppt"}
        assert source_file.mime_family == "unknown"
        assert not source_file.is_supported


def test_source_file_preserves_required_and_optional_manifest_metadata() -> None:
    raw = {"id": "raw-1", "extra": {"drive_id": "drive-123"}}

    source_file = SourceFile(
        source_id="google-drive",
        stream="regulations",
        file_id="file-123",
        source_path="HR/report.xlsx",
        object_path="/staging/files/report__file-123.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=4096,
        created_at="2026-07-01T10:00:00Z",
        updated_at="2026-07-02T10:00:00Z",
        source_url="https://drive.google.com/file/d/file-123",
        metadata={"drive_id": "drive-123"},
        raw_record=raw,
    )

    assert source_file.extension == ".xlsx"
    assert source_file.is_supported
    assert source_file.input_kind == "workbook"
    assert source_file.normalized_extension == ".xlsx"
    assert source_file.mime_family == "spreadsheet"
    assert source_file.raw_record is raw
    assert source_file.metadata == {"drive_id": "drive-123"}
    serialized = source_file.to_dict()
    assert serialized["source_url"] == "https://drive.google.com/file/d/file-123"
    assert serialized["metadata"] == {"drive_id": "drive-123"}
    assert serialized["raw_record"] is raw
    assert (
        serialized["mime_type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert serialized["input_kind"] == "workbook"
    assert serialized["normalized_extension"] == ".xlsx"
    assert serialized["mime_family"] == "spreadsheet"


def test_run_summary_counts_processed_skipped_missing_and_invalid_records() -> None:
    processed = [
        SourceFile(
            source_id="google-drive",
            stream="regulations",
            file_id="xlsx-1",
            source_path="ok.xlsx",
            object_path="/staging/files/ok.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=100,
        )
    ]
    diagnostics = [
        ManifestDiagnostic(
            reason="unsupported_type",
            message="Unsupported extension: .docx",
            source_id="google-drive",
            stream="regulations",
            file_id="doc-1",
            source_path="doc.docx",
            object_path="/staging/files/doc.docx",
        ),
        ManifestDiagnostic(
            reason="missing_local_file",
            message="File is not present under input root",
            source_id="google-drive",
            stream="regulations",
            file_id="missing-1",
            source_path="missing.xlsx",
            object_path="/staging/files/missing.xlsx",
        ),
        ManifestDiagnostic(
            reason="invalid_record",
            message="Missing required field: object_path",
        ),
    ]

    summary = RunSummary.from_results(processed, diagnostics, declared_size_bytes=3220000000)

    assert summary.total_records == 4
    assert summary.processed_files == 1
    assert summary.skipped_files == 1
    assert summary.missing_files == 1
    assert summary.invalid_records == 1
    assert summary.declared_size_bytes == 3220000000


def _source_file(filename: str, *, mime_type: str = "application/octet-stream") -> SourceFile:
    return SourceFile(
        source_id="google-drive",
        stream="regulations",
        file_id=filename,
        source_path=filename,
        object_path=f"/staging/files/{filename}",
        mime_type=mime_type,
        size_bytes=100,
    )
