from lore_splitter.xlsx.merged import expand_merged_values, extract_merged_ranges
from lore_splitter.xlsx.regions import (
    build_sheet_regions,
    detect_table_candidates,
)


def test_detects_single_rectangular_table() -> None:
    candidates = detect_table_candidates(
        [
            ["Quarterly sales"],
            ["Region", "Amount", "Owner"],
            ["North", 10, "Ada"],
            ["South", 20, "Grace"],
        ],
        workbook_checksum="sha256",
        sheet_name="Summary",
        sheet_index=1,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.range.a1_range == "A2:C4"
    assert candidate.header_row == 2
    assert candidate.columns == ("Region", "Amount", "Owner")
    assert candidate.workbook_checksum == "sha256"
    assert candidate.sheet_name == "Summary"
    assert candidate.sheet_index == 1
    assert candidate.warnings == ()


def test_splits_tables_on_blank_row_or_column() -> None:
    candidates = detect_table_candidates(
        [
            ["Name", "Amount", None, "Code", "Label"],
            ["Alpha", 10, None, "A", "Active"],
            [None, None, None, None, None],
            ["Name", "Amount", None, None, None],
            ["Beta", 20, None, None, None],
        ],
        workbook_checksum="sha256",
        sheet_name="Mixed",
        sheet_index=2,
    )

    assert [candidate.range.a1_range for candidate in candidates] == [
        "A1:B2",
        "D1:E2",
        "A4:B5",
    ]


def test_filters_decorative_single_row_and_single_cell_fragments() -> None:
    candidates = detect_table_candidates(
        [
            ["One row note", None, None],
            [None, None, None],
            ["Only", "Headers", "Here"],
            [None, None, None],
            ["solo"],
        ],
        workbook_checksum="sha256",
        sheet_name="Notes",
        sheet_index=1,
    )

    assert candidates == ()


def test_generates_stable_headers_for_blanks_and_duplicates() -> None:
    candidates = detect_table_candidates(
        [
            ["Name", "Name", None],
            ["Alpha", "A", 10],
            ["Beta", "B", 20],
        ],
        workbook_checksum="sha256",
        sheet_name="Headers",
        sheet_index=1,
    )

    assert len(candidates) == 1
    assert candidates[0].columns == ("Name", "Name_2", "Column_3")
    assert candidates[0].warnings == ("duplicate_headers", "generated_headers")


def test_whole_sheet_fallback_for_ambiguous_data() -> None:
    candidates = detect_table_candidates(
        [
            ["Only one populated row", "with context", "but no body"],
            [None, None, None],
            [None, "Sparse note", None],
        ],
        workbook_checksum="sha256",
        sheet_name="Ambiguous",
        sheet_index=1,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.range.a1_range == "A1:C3"
    assert candidate.header_row == 1
    assert candidate.columns == ("Only one populated row", "with context", "but no body")
    assert "fallback_used" in candidate.warnings
    assert "sparse_shape" in candidate.warnings


def test_merged_cells_expand_for_detection_and_preserve_metadata(tmp_path) -> None:
    from openpyxl import Workbook

    workbook_path = tmp_path / "merged.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Merged"
    sheet.merge_cells("A1:B1")
    sheet["A1"] = "Region"
    sheet["C1"] = "Amount"
    sheet.append(["North", "North", 10])
    sheet.append(["South", "South", 20])
    workbook.save(workbook_path)
    workbook.close()

    merged_ranges = extract_merged_ranges(workbook_path, "Merged")
    expanded_rows, expanded = expand_merged_values(
        [
            ["Region", None, "Amount"],
            ["North", "North", 10],
            ["South", "South", 20],
        ],
        merged_ranges,
    )
    candidates = detect_table_candidates(
        expanded_rows,
        workbook_checksum="sha256",
        sheet_name="Merged",
        sheet_index=1,
        merged_cells_expanded=expanded,
    )

    assert [cell_range.a1_range for cell_range in merged_ranges] == ["A1:B1"]
    assert expanded_rows[0] == ["Region", "Region", "Amount"]
    assert len(candidates) == 1
    assert candidates[0].range.a1_range == "A1:C3"
    assert "merged_cells_expanded" in candidates[0].warnings


def test_build_sheet_regions_preserves_source_order_and_skips_decorative_fragments() -> None:
    rows = [
        ["Quarterly sales", None, None],
        ["Region", "Amount", None],
        ["North", 10, None],
        [None, None, None],
        ["note", None, None],
    ]
    candidates = detect_table_candidates(
        rows,
        workbook_checksum="sha256",
        sheet_name="Summary",
        sheet_index=1,
    )

    regions = build_sheet_regions(
        rows,
        candidates,
        workbook_checksum="sha256",
        sheet_name="Summary",
        sheet_index=1,
    )

    assert [region.semantic_kind for region in regions] == ["scalar", "table", "skipped"]
    assert [region.source_bounds.a1_range for region in regions] == ["A1:A1", "A2:B3", "A5:A5"]
    assert regions[0].text == "Quarterly sales"
    assert regions[1].candidate is candidates[0]
    assert "low_meaning_fragment" in regions[2].warnings


def test_sheet_region_serialization_keeps_coordinates_without_cell_payload() -> None:
    rows = [["Title"], ["Name", "Amount"], ["A", 1]]
    candidates = detect_table_candidates(
        rows,
        workbook_checksum="sha256",
        sheet_name="Sheet",
        sheet_index=2,
    )
    region = build_sheet_regions(
        rows,
        candidates,
        workbook_checksum="sha256",
        sheet_name="Sheet",
        sheet_index=2,
        merged_ranges=(),
    )[0]

    payload = region.to_dict()
    assert payload["sheet_index"] == 2
    assert payload["source_bounds"]["a1_range"] == "A1:A1"
    assert "rows" not in payload
