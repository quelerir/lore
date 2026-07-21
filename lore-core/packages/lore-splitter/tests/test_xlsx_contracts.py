from pathlib import Path

from lore_splitter.contracts import ManifestDiagnostic, SourceFile
from lore_splitter.xlsx import (
    CellRange,
    SheetExtraction,
    WorkbookExtraction,
    WorkbookExtractionResult,
)


def test_cell_range_serializes_coordinates_and_a1_range() -> None:
    cell_range = CellRange(min_row=2, max_row=8, min_column=3, max_column=5, a1_range="C2:E8")

    assert cell_range.to_dict() == {
        "min_row": 2,
        "max_row": 8,
        "min_column": 3,
        "max_column": 5,
        "a1_range": "C2:E8",
    }


def test_sheet_extraction_serializes_sheet_metadata_with_empty_table_candidates() -> None:
    sheet = SheetExtraction(
        name="Hidden lookup",
        index=2,
        hidden=True,
        max_row=25,
        max_column=6,
        merged_ranges=(CellRange(1, 1, 1, 3, "A1:C1"),),
    )

    assert sheet.to_dict() == {
        "name": "Hidden lookup",
        "index": 2,
        "hidden": True,
        "max_row": 25,
        "max_column": 6,
        "merged_ranges": [
            {
                "min_row": 1,
                "max_row": 1,
                "min_column": 1,
                "max_column": 3,
                "a1_range": "A1:C1",
            }
        ],
        "table_candidates": [],
    }


def test_workbook_extraction_serializes_source_identity_checksum_and_sheets() -> None:
    source_file = SourceFile(
        source_id="google-drive",
        stream="regulations",
        file_id="file-123",
        source_path="Finance/report.xlsx",
        object_path="/staging/files/report__file-123.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=4096,
    )
    sheet = SheetExtraction(
        name="Summary",
        index=1,
        hidden=False,
        max_row=10,
        max_column=4,
        merged_ranges=(),
    )
    workbook = WorkbookExtraction(
        source_file=source_file,
        local_path=Path("/tmp/materialized/staging/files/report__file-123.xlsx"),
        workbook_checksum="a" * 64,
        sheets=(sheet,),
    )

    assert workbook.to_dict() == {
        "source_id": "google-drive",
        "stream": "regulations",
        "file_id": "file-123",
        "source_path": "Finance/report.xlsx",
        "object_path": "/staging/files/report__file-123.xlsx",
        "local_path": "/tmp/materialized/staging/files/report__file-123.xlsx",
        "workbook_checksum": "a" * 64,
        "sheets": [sheet.to_dict()],
    }


def test_workbook_extraction_result_serializes_workbooks_and_diagnostics() -> None:
    source_file = SourceFile(
        source_id="google-drive",
        stream="regulations",
        file_id="file-123",
        source_path="Finance/report.xlsx",
        object_path="/staging/files/report__file-123.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=4096,
    )
    result = WorkbookExtractionResult(
        workbooks=(),
        diagnostics=(
            ManifestDiagnostic.for_source(
                "unreadable_workbook",
                "Could not open workbook",
                source_file,
            ),
        ),
    )

    assert result.to_dict() == {
        "workbooks": [],
        "diagnostics": [
            {
                "reason": "unreadable_workbook",
                "message": "Could not open workbook",
                "source_id": "google-drive",
                "stream": "regulations",
                "file_id": "file-123",
                "source_path": "Finance/report.xlsx",
                "object_path": "/staging/files/report__file-123.xlsx",
            }
        ],
    }
