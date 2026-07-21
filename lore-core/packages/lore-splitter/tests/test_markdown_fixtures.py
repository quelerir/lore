from __future__ import annotations

from lore_splitter.markdown import profile_table
from lore_splitter.markdown.render import render_workbook_markdown
from lore_splitter.markdown.toast import ToastThresholds, classify_table
from tests.test_markdown_render import (
    _candidate,
    _sheet,
    _table_data,
    _workbook,
)


def test_markdown_fixture_preserves_a1_note_hidden_sheet_and_skipped_metadata_source() -> None:
    workbook = _workbook(
        sheets=(
            _sheet("TitlePlusTable", 1, candidates=(_candidate("TitlePlusTable", 1, "A3:B5"),)),
            _sheet(
                "HiddenLookup", 2, hidden=True, candidates=(_candidate("HiddenLookup", 2, "A1:B3"),)
            ),
            _sheet("Decorative", 3, candidates=(_candidate("Decorative", 3, "A1:B2"),)),
        )
    )
    inline = _table_data("TitlePlusTable", 1, "A3:B5")
    hidden = _table_data("HiddenLookup", 2, "A1:B3", rows=(("Code", "Label"), ("A", "Active")))
    skipped = _table_data("Decorative", 3, "A1:B2", rows=(("Column_1", "Column_2"), ("", None)))
    tables = (inline, hidden, skipped)
    profiles = tuple(profile_table(table) for table in tables)
    decisions = tuple(
        classify_table(
            table,
            profile,
            thresholds=ToastThresholds(max_inline_markdown_bytes=1)
            if table.sheet_name == "HiddenLookup"
            else None,
        )
        for table, profile in zip(tables, profiles)
    )

    markdown = render_workbook_markdown(
        workbook,
        tables,
        profiles,
        decisions,
        sheet_scalar_text={"TitlePlusTable": ("A1: Quarterly sales note",)},
    )

    assert "A1: Quarterly sales note" in markdown
    assert "## Sheet 2: HiddenLookup (hidden sheet)" in markdown
    assert "> Warning: hidden sheet" in markdown
    assert decisions[1].toast_id is not None
    assert f"[TOAST: {decisions[1].toast_id}]" in markdown
    assert decisions[2].classification == "skipped"
    assert "Column_1" not in markdown
