import pytest
from toast.guardrails import validate_select
from toast.policy import check_policy

OK = "SELECT column_1 FROM splitter_toast.toast_tbl_a1b2c3d4e5f6a7b8c9d0 LIMIT 5"


def test_valid_select_passes():
    assert validate_select(OK) is None


def test_join_and_registry_pass():
    sql = """SELECT b.column_2, m.middle_lvl_1
    FROM splitter_toast.toast_tbl_a1b2c3d4e5f6a7b8c9d0 b
    LEFT JOIN splitter_toast.toast_tbl_b1b2c3d4e5f6a7b8c9d0 m USING (_splitter_source_row)"""
    assert validate_select(sql) is None
    assert validate_select("SELECT payload_id FROM lore_core.payloads WHERE kind='table'") is None


@pytest.mark.parametrize("bad", [
    "DROP TABLE lore_core.payloads",
    "DELETE FROM lore_core.chunks",
    "INSERT INTO lore_core.chunks VALUES ('x','y','[]')",
    "UPDATE lore_core.payloads SET kind='x'",
    "COPY lore_core.chunks TO '/tmp/x'",
    "SELECT 1; DROP TABLE lore_core.payloads",
])
def test_mutations_rejected(bad):
    assert validate_select(bad) is not None


def test_foreign_schema_rejected():
    assert validate_select("SELECT * FROM public.users") is not None
    assert validate_select("SELECT * FROM pg_catalog.pg_tables") is not None


def test_bad_table_id_rejected():
    assert validate_select("SELECT * FROM splitter_toast.evil_table") is not None
    assert validate_select("SELECT * FROM splitter_toast.toast_tbl_zzzz") is not None


def test_bare_toast_tables_qualified():
    from toast.guardrails import qualify_toast_tables

    sql = ("SELECT t.column_1 FROM toast_tbl_d1b2c3d4e5f6a7b8c9d0 t "
           "JOIN toast_tbl_a1b2c3d4e5f6a7b8c9d0 b USING (_splitter_source_row)")
    fixed = qualify_toast_tables(sql)
    assert "FROM splitter_toast.toast_tbl_d1b2c3d4e5f6a7b8c9d0" in fixed
    assert "JOIN splitter_toast.toast_tbl_a1b2c3d4e5f6a7b8c9d0" in fixed
    # уже квалифицированные не трогаем
    ok = "SELECT 1 FROM splitter_toast.toast_tbl_a1b2c3d4e5f6a7b8c9d0"
    assert qualify_toast_tables(ok) == ok


def test_pii_table_gated():
    sql = "SELECT vacation_start FROM splitter_toast.toast_tbl_e1b2c3d4e5f6a7b8c9d0"
    assert check_policy(sql) is not None
    assert check_policy(OK) is None
