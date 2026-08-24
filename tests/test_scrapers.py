from prospecting_agent.scrapers.google_maps import _item_to_business as apify_item_to_business
from prospecting_agent.scrapers.google_maps_serpapi import _item_to_business as serpapi_item_to_business

# --- Apify mapping ---

_APIFY_ITEM = {
    "placeId": "apify_place_1",
    "title": "Acme HVAC",
    "address": "123 Main St, Dallas, TX",
    "phone": "(214) 555-0100",
    "website": "https://acmehvac.example.com",
    "totalScore": 4.5,
    "reviewsCount": 42,
    "categories": ["HVAC contractor"],
    "openingHours": [{"day": "Monday", "hours": "8 AM to 5 PM"}],
    "permanentlyClosed": False,
    "temporarilyClosed": False,
}


def test_apify_item_to_business_maps_fields():
    lead = apify_item_to_business(_APIFY_ITEM, city="Dallas", keyword="HVAC repair")

    assert lead is not None
    assert lead.place_id == "apify_place_1"
    assert lead.name == "Acme HVAC"
    assert lead.formatted_address == "123 Main St, Dallas, TX"
    assert lead.phone == "(214) 555-0100"
    assert lead.rating == 4.5
    assert lead.user_ratings_total == 42
    assert lead.types == ["HVAC contractor"]
    assert lead.business_status == "OPERATIONAL"
    assert lead.opening_hours == ["Monday: 8 AM to 5 PM"]
    assert lead.search_city == "Dallas"
    assert lead.search_keyword == "HVAC repair"


def test_apify_item_to_business_permanently_closed():
    item = {**_APIFY_ITEM, "permanentlyClosed": True}
    lead = apify_item_to_business(item, city="Dallas", keyword="HVAC repair")
    assert lead.business_status == "CLOSED_PERMANENTLY"


def test_apify_item_to_business_missing_place_id_returns_none():
    item = {**_APIFY_ITEM}
    del item["placeId"]
    assert apify_item_to_business(item, city="Dallas", keyword="HVAC repair") is None


# --- SerpApi mapping ---

_SERPAPI_ITEM = {
    "place_id": "serpapi_place_1",
    "title": "Acme Plumbing",
    "address": "456 Elm St, Tampa, FL",
    "phone": "(813) 555-0200",
    "website": "https://acmeplumbing.example.com",
    "rating": 4.1,
    "reviews": 30,
    "type": "Plumber",
}


def test_serpapi_item_to_business_maps_fields():
    lead = serpapi_item_to_business(_SERPAPI_ITEM, city="Tampa", keyword="emergency plumber")

    assert lead is not None
    assert lead.place_id == "serpapi_place_1"
    assert lead.name == "Acme Plumbing"
    assert lead.formatted_address == "456 Elm St, Tampa, FL"
    assert lead.rating == 4.1
    assert lead.user_ratings_total == 30
    assert lead.types == ["Plumber"]
    assert lead.business_status == "OPERATIONAL"
    assert lead.opening_hours is None


def test_serpapi_item_to_business_detects_permanently_closed_from_text():
    item = {**_SERPAPI_ITEM, "hours": "Permanently closed"}
    lead = serpapi_item_to_business(item, city="Tampa", keyword="emergency plumber")
    assert lead.business_status == "CLOSED_PERMANENTLY"


def test_serpapi_item_to_business_missing_place_id_falls_back_to_data_id():
    item = {**_SERPAPI_ITEM}
    del item["place_id"]
    item["data_id"] = "fallback_id"
    lead = serpapi_item_to_business(item, city="Tampa", keyword="emergency plumber")
    assert lead.place_id == "fallback_id"


def test_serpapi_item_to_business_missing_id_returns_none():
    item = {**_SERPAPI_ITEM}
    del item["place_id"]
    assert serpapi_item_to_business(item, city="Tampa", keyword="emergency plumber") is None
