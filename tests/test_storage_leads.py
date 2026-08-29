import pytest

from conftest import FakeTable
from prospecting_agent.storage.leads import AirtableLeadsManager


@pytest.fixture
def scored_lead(make_cleaned_lead):
    from prospecting_agent.models import ScoredLead

    def make(**kwargs):
        lead = make_cleaned_lead(
            place_id=kwargs.pop("place_id", "place_1"),
            name=kwargs.pop("name", "Acme HVAC"),
            phone=kwargs.pop("phone", "(214) 555-0100"),
            normalized_phone=kwargs.pop("normalized_phone", "+12145550100"),
            search_keyword=kwargs.pop("search_keyword", "HVAC repair"),
            rating=kwargs.pop("rating", 4.2),
            user_ratings_total=kwargs.pop("user_ratings_total", 15),
        )
        return ScoredLead(
            **lead.model_dump(),
            score=kwargs.pop("score", 8),
            service_need_score=kwargs.pop("service_need_score", 8.0),
            website_opportunity_score=kwargs.pop("website_opportunity_score", 3.0),
            review_profile_score=kwargs.pop("review_profile_score", 7.0),
            contactability_score=kwargs.pop("contactability_score", 10.0),
            business_activity_score=kwargs.pop("business_activity_score", 6.0),
            reason="test reason",
            pain_points=["no website listed"],
            recommended_offer="a free Missed Call Revenue Audit",
            personalized_first_line="Hi Acme HVAC,",
            full_outreach_message="Hi Acme HVAC, noticed a couple of things...",
        )

    return make


def test_append_new_leads_writes_new_lead(scored_lead):
    table = FakeTable()
    manager = AirtableLeadsManager(table)

    new_count, refreshed_count = manager.append_new_leads([scored_lead(place_id="new_place")])

    assert (new_count, refreshed_count) == (1, 0)
    assert len(table.records) == 1
    assert table.records[0]["fields"]["Name"] == "Acme HVAC"
    assert table.records[0]["fields"]["Place ID"] == "new_place"
    assert table.records[0]["fields"]["Duplicate Risk"] == "Low"


def test_append_new_leads_refreshes_existing_place_id_instead_of_skipping(scored_lead):
    table = FakeTable(
        records=[
            {
                "id": "rec1",
                "fields": {
                    "Phone": "+19999999999",
                    "Place ID": "dup_place",
                    "Rating": 3.0,
                    "Status": "Contacted",
                    "Notes": "called twice already",
                },
            }
        ]
    )
    manager = AirtableLeadsManager(table)

    new_count, refreshed_count = manager.append_new_leads([scored_lead(place_id="dup_place", rating=4.5)])

    assert (new_count, refreshed_count) == (0, 1)
    assert len(table.records) == 1  # updated in place, not duplicated
    assert table.records[0]["fields"]["Rating"] == 4.5  # scraped field refreshed
    assert table.records[0]["fields"]["Status"] == "Contacted"  # human-owned field untouched
    assert table.records[0]["fields"]["Notes"] == "called twice already"


def test_append_new_leads_refreshes_existing_phone_match_instead_of_skipping(scored_lead):
    table = FakeTable(records=[{"id": "rec1", "fields": {"Phone": "+12145550100", "Place ID": "some_other_place"}}])
    manager = AirtableLeadsManager(table)

    new_count, refreshed_count = manager.append_new_leads(
        [scored_lead(place_id="new_place", normalized_phone="+12145550100")]
    )

    assert (new_count, refreshed_count) == (0, 1)
    assert len(table.records) == 1


def test_append_new_leads_flags_duplicate_risk_for_similar_name_same_city(scored_lead):
    table = FakeTable(records=[{"id": "rec1", "fields": {"Name": "Acme HVAC LLC", "City": "Dallas", "Place ID": "existing"}}])
    manager = AirtableLeadsManager(table)

    manager.append_new_leads([scored_lead(place_id="new_place", name="Acme HVAC")])

    new_record = next(r for r in table.records if r["fields"]["Place ID"] == "new_place")
    assert new_record["fields"]["Duplicate Risk"] == "Medium"


def test_append_new_leads_empty_list_returns_zero():
    manager = AirtableLeadsManager(FakeTable())
    assert manager.append_new_leads([]) == (0, 0)


def test_update_status_found(scored_lead):
    table = FakeTable()
    manager = AirtableLeadsManager(table)
    manager.append_new_leads([scored_lead(place_id="target_place")])

    assert manager.update_status("target_place", "Contacted") is True
    assert table.records[0]["fields"]["Status"] == "Contacted"


def test_update_status_not_found():
    manager = AirtableLeadsManager(FakeTable())
    assert manager.update_status("nonexistent", "Contacted") is False


def test_update_fields_updates_multiple_fields_at_once(scored_lead):
    table = FakeTable()
    manager = AirtableLeadsManager(table)
    manager.append_new_leads([scored_lead(place_id="target_place")])

    updated = manager.update_fields("target_place", {"Notes": "left voicemail", "Follow Up Date": "2026-09-01"})

    assert updated is True
    assert table.records[0]["fields"]["Notes"] == "left voicemail"
    assert table.records[0]["fields"]["Follow Up Date"] == "2026-09-01"


def test_get_lead_returns_fields_by_place_id(scored_lead):
    table = FakeTable()
    manager = AirtableLeadsManager(table)
    manager.append_new_leads([scored_lead(place_id="target_place")])

    lead = manager.get_lead("target_place")

    assert lead["Name"] == "Acme HVAC"


def test_get_lead_returns_none_when_missing():
    manager = AirtableLeadsManager(FakeTable())
    assert manager.get_lead("nonexistent") is None


def test_read_leads_filters_by_min_score(scored_lead):
    table = FakeTable()
    manager = AirtableLeadsManager(table)
    manager.append_new_leads(
        [
            scored_lead(place_id="high", score=9),
            scored_lead(place_id="low", score=4, normalized_phone="+12145550999"),
        ]
    )

    rows = manager.read_leads(min_score=7)

    assert len(rows) == 1
    assert rows[0]["Score"] == 9


def test_read_leads_skips_records_with_unparseable_score():
    table = FakeTable(records=[{"id": "rec1", "fields": {"Name": "Weird Co", "Score": "not-a-number"}}])
    manager = AirtableLeadsManager(table)
    assert manager.read_leads(min_score=1) == []


def test_search_leads_filters_by_city_case_insensitive_substring():
    table = FakeTable(
        records=[
            {"id": "r1", "fields": {"Name": "Dallas Co", "City": "Dallas", "Score": 8, "Status": "New"}},
            {"id": "r2", "fields": {"Name": "Miami Co", "City": "Miami", "Score": 8, "Status": "New"}},
        ]
    )
    manager = AirtableLeadsManager(table)

    results, total = manager.search_leads(city="dallas")

    assert [r["Name"] for r in results] == ["Dallas Co"]
    assert total == 1


def test_search_leads_filters_by_min_score_and_status():
    table = FakeTable(
        records=[
            {"id": "r1", "fields": {"Name": "High New", "City": "Dallas", "Score": 9, "Status": "New"}},
            {"id": "r2", "fields": {"Name": "High Contacted", "City": "Dallas", "Score": 9, "Status": "Contacted"}},
            {"id": "r3", "fields": {"Name": "Low New", "City": "Dallas", "Score": 3, "Status": "New"}},
        ]
    )
    manager = AirtableLeadsManager(table)

    results, total = manager.search_leads(min_score=7, status="new")

    assert [r["Name"] for r in results] == ["High New"]
    assert total == 1


def test_search_leads_respects_limit_but_reports_full_total():
    table = FakeTable(records=[{"id": f"r{i}", "fields": {"Name": f"Co {i}", "Score": 8}} for i in range(5)])
    manager = AirtableLeadsManager(table)

    results, total = manager.search_leads(limit=2)

    assert len(results) == 2
    assert total == 5


def test_search_leads_filters_by_category_case_insensitive():
    table = FakeTable(
        records=[
            {"id": "r1", "fields": {"Name": "Hot Air Co", "Category": "HVAC"}},
            {"id": "r2", "fields": {"Name": "Wet Pipes Co", "Category": "Plumbing"}},
        ]
    )
    manager = AirtableLeadsManager(table)

    results, total = manager.search_leads(category="hvac")

    assert [r["Name"] for r in results] == ["Hot Air Co"]


def test_search_leads_filters_by_has_website():
    table = FakeTable(
        records=[
            {"id": "r1", "fields": {"Name": "Has Site", "Website": "https://example.com"}},
            {"id": "r2", "fields": {"Name": "No Site", "Website": ""}},
        ]
    )
    manager = AirtableLeadsManager(table)

    results, _ = manager.search_leads(has_website=False)

    assert [r["Name"] for r in results] == ["No Site"]


def test_search_leads_filters_by_min_rating_and_min_reviews():
    table = FakeTable(
        records=[
            {"id": "r1", "fields": {"Name": "Great Co", "Rating": 4.8, "Reviews": 100}},
            {"id": "r2", "fields": {"Name": "Meh Co", "Rating": 3.0, "Reviews": 2}},
        ]
    )
    manager = AirtableLeadsManager(table)

    results, _ = manager.search_leads(min_rating=4.0, min_reviews=10)

    assert [r["Name"] for r in results] == ["Great Co"]


def test_search_leads_sorts_by_score_descending():
    table = FakeTable(
        records=[
            {"id": "r1", "fields": {"Name": "Low", "Score": 5}},
            {"id": "r2", "fields": {"Name": "High", "Score": 9}},
        ]
    )
    manager = AirtableLeadsManager(table)

    results, _ = manager.search_leads(sort="score")

    assert [r["Name"] for r in results] == ["High", "Low"]


def test_append_new_leads_stamps_category_from_search_keyword(scored_lead):
    table = FakeTable()
    manager = AirtableLeadsManager(table)

    manager.append_new_leads(
        [
            scored_lead(place_id="hvac_lead", search_keyword="HVAC repair", normalized_phone="+12145550100"),
            scored_lead(place_id="plumbing_lead", search_keyword="emergency plumber", normalized_phone="+12145550200"),
        ]
    )

    categories = {r["fields"]["Place ID"]: r["fields"]["Category"] for r in table.records}
    assert categories == {"hvac_lead": "HVAC", "plumbing_lead": "Plumbing"}


def test_list_cities_returns_distinct_sorted_cities():
    table = FakeTable(
        records=[
            {"id": "r1", "fields": {"Name": "A", "City": "Miami"}},
            {"id": "r2", "fields": {"Name": "B", "City": "Dallas"}},
            {"id": "r3", "fields": {"Name": "C", "City": "Dallas"}},
        ]
    )
    manager = AirtableLeadsManager(table)

    assert manager.list_cities() == ["Dallas", "Miami"]


def test_list_cities_skips_records_with_no_city():
    table = FakeTable(records=[{"id": "r1", "fields": {"Name": "No City Co"}}])
    manager = AirtableLeadsManager(table)

    assert manager.list_cities() == []
