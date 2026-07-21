from lore_retrieval.adapters.evidence_postgres import rows_to_resolution


def _row(cid, run_id="run-1", fulltext_hash="fh"):
    return {
        "chunk_id": cid, "run_id": run_id, "fulltext": f"ft {cid}",
        "display_text": f"dt {cid}", "coordinates": {"heading_path": ["Root"]},
        "payload_refs": [{"payload_id": "p1"}], "fulltext_hash": fulltext_hash,
    }


def test_maps_rows_to_envelopes():
    rows = {"c1": _row("c1")}
    res = rows_to_resolution(rows, ["c1"], "spike1")
    e = res.resolved[0]
    assert e.chunk_id == "c1" and e.fulltext == "ft c1" and e.display_text == "dt c1"
    assert e.coordinates == {"heading_path": ["Root"]}
    assert e.payload_refs == [{"payload_id": "p1"}]
    assert e.index_version == "spike1"
    assert res.rejected == []


def test_missing_chunk_rejected():
    res = rows_to_resolution({}, ["ghost"], "spike1")
    assert res.rejected == [("ghost", "missing")]


def test_wrong_version_when_run_not_active():
    rows = {"c1": _row("c1", run_id="old-run")}
    res = rows_to_resolution(rows, ["c1"], "spike1", active_run_ids={"run-1"})
    assert res.rejected == [("c1", "wrong_version")]


def test_hash_mismatch_rejected():
    rows = {"c1": _row("c1", fulltext_hash="stored")}
    res = rows_to_resolution(rows, ["c1"], "spike1", expected_hash={"c1": "different"})
    assert res.rejected == [("c1", "hash_mismatch")]


def test_display_text_falls_back_to_fulltext():
    row = _row("c1")
    row["display_text"] = None
    res = rows_to_resolution({"c1": row}, ["c1"], "spike1")
    assert res.resolved[0].display_text == "ft c1"
