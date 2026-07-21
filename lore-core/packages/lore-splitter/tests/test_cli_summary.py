import json
import subprocess
import sys
from pathlib import Path

from lore_splitter.manifest import load_manifest

_TESTS_DIR = Path(__file__).parent
FIXTURE_MANIFEST = _TESTS_DIR / "fixtures" / "internal2_manifest.jsonl"
FIXTURE_ROOT = _TESTS_DIR / "fixtures" / "materialized"
MIXED_MANIFEST = _TESTS_DIR / "fixtures" / "xlsx_manifest.jsonl"
MIXED_ROOT = _TESTS_DIR / "fixtures"


def test_internal2_manifest_fixture_has_expected_scale() -> None:
    manifest = load_manifest(FIXTURE_MANIFEST)

    assert len(manifest.records) == 222
    assert manifest.declared_size_bytes == 3220000000


def test_manifest_summary_cli_reports_mixed_stream_diagnostics() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "lore_splitter",
            "manifest-summary",
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
    assert payload["total_records"] == 222
    assert payload["declared_size_bytes"] == 3220000000
    assert payload["processed_files"] == 1
    assert payload["skipped_files"] >= 1
    assert payload["missing_files"] >= 1
    assert payload["invalid_records"] == 0
    assert {item["reason"] for item in payload["diagnostics"]} >= {
        "unsupported_type",
        "missing_local_file",
    }
    assert payload["processed"][0]["raw_record"]["file_id"] == "xlsx-present"


def test_manifest_summary_cli_reports_document_routing_metadata() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "lore_splitter",
            "manifest-summary",
            "--manifest",
            str(MIXED_MANIFEST),
            "--input-root",
            str(MIXED_ROOT),
            "--json",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["workbook_count"] == 2
    assert payload["document_count"] == 1

    processed_by_id = {
        item["file_id"]: item
        for item in payload["processed"]
    }
    assert processed_by_id["cli-workbook"]["input_kind"] == "workbook"
    assert processed_by_id["cli-workbook"]["normalized_extension"] == ".xlsx"
    assert processed_by_id["cli-workbook"]["mime_family"] == "spreadsheet"

    document = processed_by_id["policy-markdown"]
    assert document["input_kind"] == "document"
    assert document["normalized_extension"] == ".md"
    assert document["mime_family"] == "markdown"
    assert document["source_url"] == "https://drive.google.com/file/d/policy-markdown"
