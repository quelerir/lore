"""XLSX workbook extraction public API."""

# NOTE(task-1): trimmed — merged, regions, workbook impl modules arrive in later tasks.
# Restore full exports when xlsx/merged.py, xlsx/regions.py, xlsx/workbook.py are added.
from lore_splitter.xlsx.contracts import (
    CellRange,
    SheetExtraction,
    TableCandidate,
    WorkbookExtraction,
    WorkbookExtractionResult,
)

__all__ = [
    "CellRange",
    "SheetExtraction",
    "TableCandidate",
    "WorkbookExtraction",
    "WorkbookExtractionResult",
    # trimmed: "detect_table_candidates",  # xlsx/regions.py
    # trimmed: "expand_merged_values",     # xlsx/merged.py
    # trimmed: "extract_workbooks",        # xlsx/workbook.py
    # trimmed: "extract_merged_ranges",    # xlsx/merged.py
    # trimmed: "sha256_file",              # xlsx/workbook.py
]
