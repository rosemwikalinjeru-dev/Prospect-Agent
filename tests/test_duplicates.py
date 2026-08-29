from prospecting_agent.utils.duplicates import is_probable_duplicate, normalize_business_name


def test_normalize_business_name_strips_legal_suffix_and_lowercases():
    assert normalize_business_name("Acme HVAC LLC") == "acme hvac"
    assert normalize_business_name("Acme HVAC, Inc.") == "acme hvac"
    assert normalize_business_name("acme hvac") == "acme hvac"


def test_normalize_business_name_collapses_whitespace_and_punctuation():
    assert normalize_business_name("Acme   HVAC & Plumbing!") == "acme hvac plumbing"


def test_is_probable_duplicate_true_for_normalized_match():
    existing = {"acme hvac"}
    assert is_probable_duplicate("Acme HVAC LLC", existing) is True


def test_is_probable_duplicate_false_for_different_business():
    existing = {"acme hvac"}
    assert is_probable_duplicate("Best Plumbing Co", existing) is False
