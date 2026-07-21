from lore_retrieval.source import row_to_source_chunk


def _row(**over):
    base = {
        "chunk_id": "c1",
        "run_id": "r1",
        "chunk_type": "text",
        "ordinal": 0,
        "coordinates": {"heading_path": ["Root", "Child"]},
        "vector_text": "векторный текст",
        "fulltext": "полный текст с кодом ABC-123",
        "vector_text_hash": "vh",
        "fulltext_hash": "fh",
    }
    base.update(over)
    return base


def test_mapping_reads_nested_heading_path():
    sc = row_to_source_chunk(_row())
    assert sc.heading_path == ("Root", "Child")
    assert sc.fulltext == "полный текст с кодом ABC-123"
    assert sc.position == 0
    assert sc.is_table is False


def test_document_id_defaults_to_run_id():
    # A processing_run maps to one document; run_id is the spike document boundary.
    sc = row_to_source_chunk(_row(run_id="run-xyz"))
    assert sc.document_id == "run-xyz"


def test_table_payload_flagged_as_table():
    sc = row_to_source_chunk(_row(chunk_type="table_payload"))
    assert sc.is_table is True


def test_missing_heading_path_defaults_empty():
    sc = row_to_source_chunk(_row(coordinates={}))
    assert sc.heading_path == ()
