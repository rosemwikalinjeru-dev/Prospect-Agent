"""Deterministic lead-scoring factors, plus the weighted blend that turns them (and
OpenAI's `service_need_score`) into the single `score` shown everywhere.

These four factors are pure functions of data already on a `CleanedLead` — no OpenAI
call needed. Keeping them out of the LLM call means the frontend can recompute the
weighted total instantly as a user adjusts weights, without spending another API call.
"""

from prospecting_agent.models import CleanedLead

DEFAULT_WEIGHTS = {
    "service_need_score": 0.40,
    "website_opportunity_score": 0.25,
    "review_profile_score": 0.20,
    "contactability_score": 0.10,
    "business_activity_score": 0.05,
}


def website_opportunity_score(lead: CleanedLead) -> float:
    """No website at all is the strongest "missing calls" signal this data can show."""
    return 10.0 if not lead.website else 3.0


def review_profile_score(lead: CleanedLead) -> float:
    """Fewer reviews and/or a middling rating suggest more room for the audit to help.
    A business with no rating/reviews at all is the highest-opportunity case; a
    well-reviewed, well-rated business is the lowest.
    """
    if lead.rating is None or not lead.user_ratings_total:
        return 10.0

    review_count_score = 10.0 if lead.user_ratings_total < 10 else 6.0 if lead.user_ratings_total < 30 else 3.0
    rating_score = 8.0 if 3.5 <= lead.rating <= 4.3 else 4.0
    return (review_count_score + rating_score) / 2


def contactability_score(lead: CleanedLead) -> float:
    """Leads without a phone number are already dropped in processing/filters.py, so
    this is close to always 10 in practice — kept explicit rather than assumed, since
    it's still a real, meaningful factor in the weighted total.
    """
    return 10.0 if (lead.normalized_phone or lead.phone) else 0.0


def business_activity_score(lead: CleanedLead) -> float:
    """Operational + hours listed reads as an active, established business."""
    if lead.business_status not in (None, "OPERATIONAL"):
        return 2.0
    return 10.0 if lead.opening_hours else 6.0


def compute_weighted_score(sub_scores: dict[str, float], weights: dict[str, float] = DEFAULT_WEIGHTS) -> int:
    """Blend sub-factor scores (each 0-10) into the single 1-10 score, rounded to the
    nearest integer. `weights` need not sum to exactly 1.0 — normalized here so a
    user's custom weighting always produces a comparable 1-10 result.
    """
    total_weight = sum(weights.values())
    weighted = sum(sub_scores[factor] * weight for factor, weight in weights.items())
    return max(1, min(10, round(weighted / total_weight)))
