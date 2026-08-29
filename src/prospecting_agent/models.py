"""Pydantic models shared across pipeline stages. Each stage's output is the next
stage's input type, so the pipeline's data contract is explicit and type-checked."""

from typing import Optional

from pydantic import BaseModel


class RawBusiness(BaseModel):
    """A business exactly as returned by the Google Places API (Text Search + Place Details merged)."""

    place_id: str
    name: str
    formatted_address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    rating: Optional[float] = None
    user_ratings_total: Optional[int] = None
    business_status: Optional[str] = None
    types: list[str] = []
    opening_hours: Optional[list[str]] = None
    google_maps_url: Optional[str] = None

    # Which (city, keyword) search produced this result — useful for debugging and reporting.
    search_city: str
    search_keyword: str

    # Which scraper provider found this business ("apify" / "serpapi" / "places_api") —
    # required so it's never silently missing on a Sheets row.
    source: str


class CleanedLead(RawBusiness):
    """A RawBusiness after deduping and phone normalization."""

    normalized_phone: Optional[str] = None


class ScoredLead(CleanedLead):
    """A CleanedLead after scoring. `score` is a weighted blend of the five sub-scores
    below (see utils/scoring.py) — only `service_need_score` actually comes from OpenAI;
    the rest are computed deterministically from data already on the lead.
    """

    score: int
    service_need_score: float
    website_opportunity_score: float
    review_profile_score: float
    contactability_score: float
    business_activity_score: float

    reason: str
    pain_points: list[str]
    recommended_offer: str
    personalized_first_line: str
    full_outreach_message: str
