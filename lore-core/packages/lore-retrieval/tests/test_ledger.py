from lore_retrieval.ledger import DerivedIndexRecord, LedgerStatus


def test_record_defaults_to_pending():
    r = DerivedIndexRecord(
        run_id="r1", index_version="v3", chunk_schema_version="cs1",
        section_projection_version="sp1", embedding_model_version="bge-m3",
        fulltext_analyzer_version="russian", graph_schema_version="g1",
        neo4j_server_version="5.26", neo4j_graphrag_version="1.3",
        reranker_version="none",
    )
    assert r.status is LedgerStatus.pending


def test_status_accepts_terminal_values():
    assert LedgerStatus("ready") is LedgerStatus.ready
    assert LedgerStatus("superseded") is LedgerStatus.superseded
