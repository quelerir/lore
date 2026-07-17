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


def test_union_of_same_table_allowed():
    sql = (f"SELECT column_1 FROM splitter_toast.{T} "
           f"UNION SELECT column_2 FROM splitter_toast.{T}")
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


def test_comma_join_to_other_table_rejected():
    # Regex-версия guardrails пропускала comma-join — чтение чужих таблиц.
    sql = f"SELECT u.* FROM splitter_toast.{T}, public.users u"
    assert validate_select(sql, T) is not None


def test_subquery_against_other_table_rejected():
    sql = f"SELECT (SELECT max(x) FROM public.secrets) FROM splitter_toast.{T}"
    assert validate_select(sql, T) is not None


def test_table_function_rejected():
    assert validate_select("SELECT * FROM generate_series(1, 10)", T) is not None


def test_forbidden_word_inside_string_literal_allowed():
    # Слово из чёрного списка в данных — не повод для отказа.
    sql = f"SELECT * FROM splitter_toast.{T} WHERE column_1 = 'create table'"
    assert validate_select(sql, T) is None


def test_semicolon_inside_string_literal_allowed():
    sql = f"SELECT * FROM splitter_toast.{T} WHERE column_1 = 'a;b'"
    assert validate_select(sql, T) is None


def test_trailing_semicolon_allowed():
    assert validate_select(f"SELECT * FROM splitter_toast.{T};", T) is None


def test_cte_over_own_table_allowed():
    sql = (f"WITH c AS (SELECT column_1 FROM splitter_toast.{T}) "
           "SELECT * FROM c")
    assert validate_select(sql, T) is None


def test_cte_over_foreign_table_rejected():
    sql = ("WITH x AS (SELECT * FROM public.users) "
           f"SELECT * FROM splitter_toast.{T} a JOIN x ON true")
    assert validate_select(sql, T) is not None


def test_cte_alias_only_without_real_table_rejected():
    # Все relation — алиасы CTE, ни одной настоящей таблицы.
    sql = "WITH c AS (SELECT 1) SELECT * FROM c"
    assert validate_select(sql, T) is not None


def test_select_into_rejected():
    assert validate_select(f"SELECT * INTO x FROM splitter_toast.{T}", T) is not None


def test_for_update_rejected():
    assert validate_select(f"SELECT * FROM splitter_toast.{T} FOR UPDATE", T) is not None


def test_non_sql_text_rejected():
    assert validate_select("Извините, не могу составить запрос", T) is not None


def test_quoted_qualified_table_accepted():
    # Модель может закавычить идентификатор — это валидный SELECT к своей таблице.
    assert validate_select(f'SELECT column_1 FROM splitter_toast."{T}"', T) is None
    assert validate_select(f'SELECT * FROM "splitter_toast"."{T}"', T) is None


def test_quoted_other_table_rejected():
    assert validate_select(f'SELECT * FROM splitter_toast."{OTHER}"', T) is not None
