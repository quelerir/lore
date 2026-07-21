import pytest

from lore_core_domain.text import normalize_text


def test_crlf_and_cr_become_lf_with_single_trailing_newline():
    assert normalize_text("a\r\nb\rc") == "a\nb\nc\n"


def test_trailing_newlines_collapse_to_one():
    assert normalize_text("line\n\n\n") == "line\n"


def test_empty_string_yields_single_newline():
    assert normalize_text("") == "\n"


def test_nfc_unicode_normalization():
    # "e" + combining acute accent (NFD) normalizes to precomposed "é" (NFC).
    assert normalize_text("é") == "é\n"


def test_non_string_raises_type_error():
    with pytest.raises(TypeError):
        normalize_text(b"bytes")  # type: ignore[arg-type]
