from prospecting_agent.processing.cleaner import clean_businesses, normalize_phone


def test_normalize_phone_valid_us_number():
    assert normalize_phone("(214) 555-0100") == "+12145550100"


def test_normalize_phone_missing_returns_none():
    assert normalize_phone(None) is None
    assert normalize_phone("") is None


def test_normalize_phone_garbage_returns_none():
    assert normalize_phone("not a phone number") is None


def test_clean_businesses_dedupes_by_place_id(make_raw_business):
    businesses = [make_raw_business(place_id="p1"), make_raw_business(place_id="p1")]
    cleaned = clean_businesses(businesses)
    assert len(cleaned) == 1


def test_clean_businesses_dedupes_by_normalized_phone(make_raw_business):
    businesses = [
        make_raw_business(place_id="p1", phone="(214) 555-0100"),
        make_raw_business(place_id="p2", phone="214-555-0100"),  # same number, different formatting
    ]
    cleaned = clean_businesses(businesses)
    assert len(cleaned) == 1


def test_clean_businesses_keeps_distinct_leads(make_raw_business):
    businesses = [
        make_raw_business(place_id="p1", phone="(214) 555-0100"),
        make_raw_business(place_id="p2", phone="(214) 555-0200"),
    ]
    cleaned = clean_businesses(businesses)
    assert len(cleaned) == 2
