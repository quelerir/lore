import pytest
from toast.sql_guardrails import qualify_table, validate_select

T = "toast_tbl_ec48a6d52d16ab405f95"
OTHER = "toast_tbl_17a7241d0a976f287103"


def test_valid_select_on_allowed_table():
    assert validate_select(f"SELECT column_1 FROM splitter_toast.{T} LIMIT 5", T) is None


def test_bare_table_name_qualified():
    assert qualify_table(f"SELECT * FROM {T}", T) == f"SELECT * FROM splitter_toast.{T}"
    # уже квалифицированное не трогаем
    q = f"SELECT * FROM splitter_toast.{T}"
    assert qualify_table(q, T) == q


def test_self_join_allowed():
    sql = (f"SELECT a.column_1 FROM splitter_toast.{T} a "
           f"JOIN splitter_toast.{T} b USING (_splitter_source_row)")
    assert validate_select(sql, T) is None


@pytest.mark.parametrize("bad", [
    "DROP TABLE splitter_toast.x",
    "DELETE FROM splitter_toast.x",
    "INSERT INTO splitter_toast.x VALUES (1)",
    "UPDATE splitter_toast.x SET a=1",
    "SELECT 1; DROP TABLE y",
])
def test_mutations_rejected(bad):
    assert validate_select(bad, T) is not None


def test_other_table_rejected():
    assert validate_select(f"SELECT * FROM splitter_toast.{OTHER}", T) is not None


def test_foreign_schema_rejected():
    assert validate_select("SELECT * FROM public.users", T) is not None
    assert validate_select("SELECT * FROM lore_core.chunks", T) is not None


def test_join_to_other_table_rejected():
    sql = (f"SELECT * FROM splitter_toast.{T} a "
           f"JOIN splitter_toast.{OTHER} b USING (_splitter_source_row)")
    assert validate_select(sql, T) is not None
