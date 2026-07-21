from lore_retrieval.adapters.file_keys import rows_to_file_keys


def test_maps_run_id_to_logical_file_key():
    rows = [
        {"run_id": "run-1", "logical_file_key": "manual.pdf"},
        {"run_id": "run-2", "logical_file_key": "grades.xlsx"},
    ]
    assert rows_to_file_keys(rows) == {"run-1": "manual.pdf", "run-2": "grades.xlsx"}


def test_empty_rows_give_empty_map():
    assert rows_to_file_keys([]) == {}
