"""Business rules that decide which cleaned leads are worth scoring with OpenAI.

Filtering hard here matters: every lead that passes gets a paid OpenAI API call next.
"""

from loguru import logger

from prospecting_agent.models import CleanedLead

_EXCLUDED_STATUSES = {"CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"}
_RELEVANT_KEYWORDS = ("hvac", "plumb", "air_conditioning", "heating", "contractor")


def is_relevant_category(lead: CleanedLead) -> bool:
    """True if the lead's Places `types` or originating search keyword indicate it's
    actually an HVAC/plumbing business, not an unrelated result Text Search returned."""
    haystack = " ".join(lead.types).lower() + " " + lead.search_keyword.lower()
    return any(keyword in haystack for keyword in _RELEVANT_KEYWORDS)


def filter_leads(leads: list[CleanedLead]) -> list[CleanedLead]:
    """Keep only leads that are open, have a usable phone number, and are on-category."""
    filtered = [
        lead
        for lead in leads
        if lead.normalized_phone
        and lead.business_status not in _EXCLUDED_STATUSES
        and is_relevant_category(lead)
    ]
    logger.info(f"Filtered {len(leads)} cleaned leads down to {len(filtered)} qualifying leads")
    return filtered
