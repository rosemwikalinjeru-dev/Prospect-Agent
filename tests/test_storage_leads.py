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
        )
        return ScoredLead(
            **lead.model_dump(),
            score=kwargs.pop("score", 8),
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

    written = manager.append_new_leads([scored_lead(place_id="new_place")])

    assert written == 1
    assert len(table.records) == 1
    assert table.records[0]["fields"]["Name"] == "Acme HVAC"
    assert table.records[0]["fields"]["Place ID"] == "new_place"


def test_append_new_leads_skips_duplicate_place_id(scored_lead):
    table = FakeTable(records=[{"id": "rec1", "fields": {"Phone": "+19999999999", "Place ID": "dup_place"}}])
    manager = AirtableLeadsManager(table)

    written = manager.append_new_leads([scored_lead(place_id="dup_place")])

    assert written == 0
    assert len(table.records) == 1  # nothing appended


def test_append_new_leads_skips_duplicate_phone(scored_lead):
    table = FakeTable(records=[{"id": "rec1", "fields": {"Phone": "+12145550100", "Place ID": "some_other_place"}}])
    manager = AirtableLeadsManager(table)

    written = manager.append_new_leads([scored_lead(place_id="new_place", normalized_phone="+12145550100")])

    assert written == 0


def test_append_new_leads_empty_list_returns_zero():
    manager = AirtableLeadsManager(FakeTable())
    assert manager.append_new_leads([]) == 0


def test_update_status_found(scored_lead):
    table = FakeTable()
    manager = AirtableLeadsManager(table)
    manager.append_new_leads([scored_lead(place_id="target_place")])

    assert manager.update_status("target_place", "Contacted") is True
    assert table.records[0]["fields"]["Status"] == "Contacted"


def test_update_status_not_found():
    manager = AirtableLeadsManager(FakeTable())
    assert manager.update_status("nonexistent", "Contacted") is False


def test_read_leads_filters_by_min_score(scored_lead):
    table = FakeTable()
    manager = AirtableLeadsManager(table)
    manager.append_new_leads(
        [
            scored_lead(place_id="high", score=9),
            scored_lead(place_id="low", score=4),
        ]
    )

    rows = manager.read_leads(min_score=7)

    assert len(rows) == 1
    assert rows[0]["Score"] == 9


def test_read_leads_skips_records_with_unparseable_score():
    table = FakeTable(records=[{"id": "rec1", "fields": {"Name": "Weird Co", "Score": "not-a-number"}}])
    manager = AirtableLeadsManager(table)
    assert manager.read_leads(min_score=1) == []
