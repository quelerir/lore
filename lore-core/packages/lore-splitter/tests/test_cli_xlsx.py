from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from lore_splitter.xlsx import sha256_file

# Fixtures are relative to the tests/ directory.
_TESTS_DIR = Path(__file__).parent
FIXTURE_MANIFEST = _TESTS_DIR / "fixtures" / "xlsx_manifest.jsonl"
FIXTURE_ROOT = _TESTS_DIR / "fixtures"
FIXTURE_WORKBOOK = _TESTS_DIR / "fixtures" / "xlsx" / "cli-workbook.xlsx"


def test_xlsx_summary_cli_reports_workbooks_candidates_and_diagnostics() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "lore_splitter",
            "xlsx-summary",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--input-root",
            str(FIXTURE_ROOT),
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)

    assert payload["workbook_count"] == 1
    assert payload["sheet_count"] == 3
    assert payload["candidate_table_count"] == 3
    assert {diagnostic["reason"] for diagnostic in payload["diagnostics"]} == {
        "unsupported_type",
        "missing_local_file",
        "unreadable_workbook",
    }
    unreadable_sources = {
        diagnostic["file_id"]
        for diagnostic in payload["diagnostics"]
        if diagnostic["reason"] == "unreadable_workbook"
    }
    assert unreadable_sources == {"corrupt-workbook"}
    assert "hidden_sheet" in payload["warnings"]
    assert "merged_cells_expanded" in payload["warnings"]

    workbook = payload["workbooks"][0]
    assert workbook["file_id"] == "cli-workbook"
    assert workbook["workbook_checksum"] == sha256_file(FIXTURE_WORKBOOK)

    summary = workbook["sheets"][0]
    assert summary["name"] == "Summary"
    assert summary["index"] == 1
    assert summary["hidden"] is False
    assert summary["max_row"] == 3
    assert summary["max_column"] == 3

    candidate = summary["table_candidates"][0]
    assert candidate["workbook_checksum"] == workbook["workbook_checksum"]
    assert candidate["sheet_name"] == "Summary"
    assert candidate["range"]["a1_range"] == "A1:C3"
    assert candidate["header_row"] == 1
    assert candidate["columns"] == ["Region", "Amount", "Owner"]

    merged = workbook["sheets"][1]
    assert [cell_range["a1_range"] for cell_range in merged["merged_ranges"]] == ["A1:B1"]
    assert merged["table_candidates"][0]["range"]["a1_range"] == "A1:C3"

    hidden = workbook["sheets"][2]
    assert hidden["name"] == "HiddenLookup"
    assert hidden["hidden"] is True
    assert hidden["table_candidates"][0]["warnings"] == ["hidden_sheet"]


def test_xlsx_summary_cli_returns_two_for_fatal_manifest_load_error(tmp_path) -> None:
    bad_manifest = tmp_path / "bad.jsonl"
    bad_manifest.write_text("{not-json", encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "lore_splitter",
            "xlsx-summary",
            "--manifest",
            str(bad_manifest),
            "--input-root",
            str(FIXTURE_ROOT),
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 2
    assert "Invalid JSONL" in completed.stderr
    assert completed.stdout == ""


def test_xlsx_summary_cli_text_output_reports_stable_counts() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "lore_splitter",
            "xlsx-summary",
            "--manifest",
            str(FIXTURE_MANIFEST),
            "--input-root",
            str(FIXTURE_ROOT),
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == (
        "workbooks=1 sheets=3 candidate_tables=3 diagnostics=3"
    )
