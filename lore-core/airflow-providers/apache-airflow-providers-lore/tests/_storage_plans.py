"""Provider-local test plan builders.

The source repo's flat test dir let `test_storage_airflow_hooks` reuse plan
helpers from sibling test modules. After the package split those helpers live
in `lore-splitter`'s own tests, so the small leaf builders this suite needs are
reconstructed here against the `lore_splitter` public surface.
"""

from __future__ import annotations

from pathlib import Path

from lore_splitter.contracts import SourceFile
from lore_splitter.markdown import (
    TableData,
    ToastThresholds,
    XlsxTableLocation,
    classify_table,
    profile_table,
)
from lore_splitter.storage import (
    ImageToastStoragePlan,
    TableToastStoragePlan,
    build_table_storage_plan,
    image_content_signature,
    image_object_key,
    image_toast_id,
)
from lore_splitter.xlsx import CellRange


def _image_plan(payload: bytes = b"image-payload") -> ImageToastStoragePlan:
    signature = image_content_signature(payload, "image/png", "png")
    toast_id = image_toast_id(signature)
    return ImageToastStoragePlan(
        toast_id=toast_id,
        bucket="splitter-image-toast",
        object_key=image_object_key(toast_id, "png"),
        content_type="image/png",
        extension=".png",
        payload=payload,
        byte_size=len(payload),
        checksum_sha256="82eefbe096f6ecd557e3aac27940dc126c64d71500b8853b316922539f1acb0c",
        source={"source_id": "google-drive"},
        source_kind="document_image",
        source_checksum="a" * 64,
        source_location={"docx": {"relationship_id": "rId7"}},
    )


def _source_file() -> SourceFile:
    return SourceFile(
        source_id="google-drive",
        stream="regulations",
        file_id="file-123",
        source_path="Finance/report.xlsx",
        object_path="/staging/files/report__file-123.xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size_bytes=4096,
    )


def _range(a1_range: str) -> CellRange:
    start, end = a1_range.split(":")
    return CellRange(
        min_row=int(start[1:]),
        max_row=int(end[1:]),
        min_column=ord(start[0]) - 64,
        max_column=ord(end[0]) - 64,
        a1_range=a1_range,
    )


def _table_data(
    sheet_name: str,
    sheet_index: int,
    a1_range: str,
    *,
    rows: tuple[tuple[object, ...], ...] = (("Region", "Amount"), ("North", 10), ("South", 25)),
) -> TableData:
    cell_range = _range(a1_range)
    return TableData(
        source_file=_source_file(),
        local_path=Path("/tmp/materialized/staging/files/report__file-123.xlsx"),
        source_kind="workbook",
        source_checksum="a" * 64,
        table_index=1,
        columns=tuple(str(value) for value in rows[0]),
        rows=rows,
        xlsx=XlsxTableLocation(
            workbook_checksum="a" * 64,
            sheet_name=sheet_name,
            sheet_index=sheet_index,
            range=cell_range,
            header_row=cell_range.min_row,
        ),
    )


def _storage_plan() -> TableToastStoragePlan:
    table = _table_data(
        "Summary",
        1,
        "A1:C4",
        rows=(
            ("Region", "Amount", "Invoice Date"),
            ("North", 125.5, "2026-02-01"),
            ("South", 50, "2026-02-02"),
            ("West", 75, "2026-02-03"),
        ),
    )
    profile = profile_table(table)
    decision = classify_table(
        table,
        profile,
        thresholds=ToastThresholds(max_inline_markdown_bytes=1),
    )
    return build_table_storage_plan(table, profile, decision)
