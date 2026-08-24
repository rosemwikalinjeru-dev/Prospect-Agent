from prospecting_agent.processing.filters import filter_leads, is_relevant_category


def test_relevant_category_matches_on_types(make_cleaned_lead):
    lead = make_cleaned_lead(types=["hvac_contractor"], search_keyword="anything")
    assert is_relevant_category(lead)


def test_relevant_category_matches_on_search_keyword(make_cleaned_lead):
    lead = make_cleaned_lead(types=["point_of_interest"], search_keyword="emergency plumber")
    assert is_relevant_category(lead)


def test_relevant_category_rejects_unrelated_business(make_cleaned_lead):
    lead = make_cleaned_lead(types=["restaurant"], search_keyword="pizza")
    assert not is_relevant_category(lead)


def test_filter_leads_drops_missing_phone(make_cleaned_lead):
    lead = make_cleaned_lead(normalized_phone=None)
    assert filter_leads([lead]) == []


def test_filter_leads_drops_permanently_closed(make_cleaned_lead):
    lead = make_cleaned_lead(business_status="CLOSED_PERMANENTLY")
    assert filter_leads([lead]) == []


def test_filter_leads_keeps_qualifying_lead(make_cleaned_lead):
    lead = make_cleaned_lead()
    assert filter_leads([lead]) == [lead]
