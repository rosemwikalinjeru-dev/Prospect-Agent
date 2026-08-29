from prospecting_agent.utils.scoring import (
    business_activity_score,
    compute_weighted_score,
    contactability_score,
    review_profile_score,
    website_opportunity_score,
)


def test_website_opportunity_score_high_when_no_website(make_cleaned_lead):
    lead = make_cleaned_lead(website=None)
    assert website_opportunity_score(lead) == 10.0


def test_website_opportunity_score_low_when_website_present(make_cleaned_lead):
    lead = make_cleaned_lead(website="https://example.com")
    assert website_opportunity_score(lead) == 3.0


def test_review_profile_score_high_when_no_reviews(make_cleaned_lead):
    lead = make_cleaned_lead(rating=None, user_ratings_total=None)
    assert review_profile_score(lead) == 10.0


def test_review_profile_score_lower_for_well_reviewed_business(make_cleaned_lead):
    few_reviews = review_profile_score(make_cleaned_lead(rating=4.0, user_ratings_total=5))
    many_reviews = review_profile_score(make_cleaned_lead(rating=4.0, user_ratings_total=200))
    assert few_reviews > many_reviews


def test_contactability_score_requires_a_phone(make_cleaned_lead):
    assert contactability_score(make_cleaned_lead(phone="555-0100", normalized_phone="+15550100")) == 10.0
    assert contactability_score(make_cleaned_lead(phone=None, normalized_phone=None)) == 0.0


def test_business_activity_score_penalizes_closed_status(make_cleaned_lead):
    operational = business_activity_score(make_cleaned_lead(business_status="OPERATIONAL", opening_hours=["Mon: 9-5"]))
    closed = business_activity_score(make_cleaned_lead(business_status="CLOSED_PERMANENTLY"))
    assert operational > closed


def test_compute_weighted_score_blends_and_clamps_to_1_10():
    sub_scores = {
        "service_need_score": 10.0,
        "website_opportunity_score": 10.0,
        "review_profile_score": 10.0,
        "contactability_score": 10.0,
        "business_activity_score": 10.0,
    }
    assert compute_weighted_score(sub_scores) == 10

    zeros = {k: 0.0 for k in sub_scores}
    assert compute_weighted_score(zeros) == 1  # clamped to the 1-10 floor, never 0


def test_compute_weighted_score_respects_custom_weights():
    sub_scores = {
        "service_need_score": 10.0,
        "website_opportunity_score": 0.0,
        "review_profile_score": 0.0,
        "contactability_score": 0.0,
        "business_activity_score": 0.0,
    }
    # All weight on service_need_score -> the total should track it directly.
    assert compute_weighted_score(sub_scores, weights={"service_need_score": 1.0, "website_opportunity_score": 0.0,
                                                         "review_profile_score": 0.0, "contactability_score": 0.0,
                                                         "business_activity_score": 0.0}) == 10
