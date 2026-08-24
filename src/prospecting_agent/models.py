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
    """A CleanedLead after OpenAI scoring."""

    score: int
    reason: str
    pain_points: list[str]
    recommended_offer: str
    personalized_first_line: str
    full_outreach_message: str
