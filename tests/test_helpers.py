import pytest

from prospecting_agent.utils.helpers import build_search_query, categorize_keyword, chunked, truncate


def test_build_search_query_formats_correctly():
    assert build_search_query("Dallas", "TX", "HVAC repair") == "HVAC repair in Dallas, TX, USA"


def test_chunked_splits_evenly():
    assert list(chunked([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]


def test_chunked_handles_uneven_remainder():
    assert list(chunked([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_chunked_empty_input_yields_nothing():
    assert list(chunked([], 3)) == []


def test_chunked_rejects_non_positive_size():
    with pytest.raises(ValueError):
        list(chunked([1, 2], 0))


def test_truncate_leaves_short_text_untouched():
    assert truncate("short text", max_length=100) == "short text"


def test_truncate_cuts_long_text_with_ellipsis():
    result = truncate("a" * 150, max_length=100)
    assert len(result) == 100
    assert result.endswith("…")


def test_truncate_exact_length_untouched():
    text = "a" * 50
    assert truncate(text, max_length=50) == text


@pytest.mark.parametrize(
    "keyword,expected",
    [
        ("HVAC repair", "HVAC"),
        ("HVAC installation", "HVAC"),
        ("air conditioning repair", "HVAC"),
        ("emergency plumber", "Plumbing"),
        ("plumbing repair", "Plumbing"),
        ("drain cleaning service", "Plumbing"),
        ("lawn mowing", "Other"),
    ],
)
def test_categorize_keyword(keyword, expected):
    assert categorize_keyword(keyword) == expected


def test_categorize_keyword_is_case_insensitive():
    assert categorize_keyword("EMERGENCY PLUMBER") == "Plumbing"
