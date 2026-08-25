"""Small, generic helpers shared across modules. Kept deliberately minimal — only
functions with a real call site or an obvious, immediate use belong here.
"""

from typing import Iterator, TypeVar

T = TypeVar("T")


def build_search_query(city: str, state: str, keyword: str) -> str:
    """Build the Google Maps search string used by every scraper provider."""
    return f"{keyword} in {city}, {state}, USA"


def chunked(items: list[T], size: int) -> Iterator[list[T]]:
    """Split `items` into consecutive chunks of at most `size` elements."""
    if size <= 0:
        raise ValueError("size must be positive")
    for i in range(0, len(items), size):
        yield items[i : i + size]


def truncate(text: str, max_length: int = 100) -> str:
    """Truncate `text` to `max_length` characters, appending an ellipsis if cut."""
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def categorize_keyword(keyword: str) -> str:
    """Classify a search keyword (from config/keywords.yaml) into a trade category
    for the Leads table's Category field and the browse/filter UI.

    Only HVAC and Plumbing are recognized today, matching what the agent actually
    searches for — "Other" is a safe fallback for a future keyword that doesn't match
    cleanly, not an error, so adding a new keyword never breaks the pipeline. Extending
    to a new trade (e.g. landscaping) means adding both a keyword here and in
    config/keywords.yaml, plus a new choice on the Airtable Category field.
    """
    lowered = keyword.lower()
    if "hvac" in lowered or "air condition" in lowered:
        return "HVAC"
    if "plumb" in lowered or "drain" in lowered:
        return "Plumbing"
    return "Other"
