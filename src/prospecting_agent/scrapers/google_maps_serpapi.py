"""Google Maps data via SerpApi's `google_maps` search engine — an alternative to the
Apify provider. Simpler (one HTTP call per page, no actor/dataset polling), but SerpApi's
`local_results` doesn't expose structured opening hours or closed-status as reliably as
Apify's actor does; see the field-mapping notes below.
"""

import time

from loguru import logger
from serpapi import GoogleSearch

from prospecting_agent.models import RawBusiness
from prospecting_agent.utils.helpers import build_search_query
from prospecting_agent.utils.retry import with_retry

# The `google-search-results` client doesn't raise a distinct exception type for API-level
# failures (those come back as an `error` key in the response dict, handled below) — only
# network-level failures raise, as plain built-in exceptions.
_RETRYABLE_ERRORS = (TimeoutError, ConnectionError, OSError)


def _business_status(item: dict) -> str:
    # SerpApi doesn't provide a dedicated closed-status field on local_results; the best
    # available signal is the free-text `hours`/`open_state` field occasionally saying so.
    text = f"{item.get('hours', '')} {item.get('open_state', '')}".lower()
    if "permanently closed" in text:
        return "CLOSED_PERMANENTLY"
    if "temporarily closed" in text:
        return "CLOSED_TEMPORARILY"
    return "OPERATIONAL"


def _item_to_business(item: dict, city: str, keyword: str) -> RawBusiness | None:
    place_id = item.get("place_id") or item.get("data_id")
    if not place_id:
        logger.warning(f"Skipping SerpApi item with no place_id: {item.get('title')!r}")
        return None

    types = item.get("types") or ([item["type"]] if item.get("type") else [])

    return RawBusiness(
        place_id=place_id,
        name=item.get("title", ""),
        formatted_address=item.get("address"),
        phone=item.get("phone"),
        website=item.get("website"),
        rating=item.get("rating"),
        user_ratings_total=item.get("reviews"),
        business_status=_business_status(item),
        types=types,
        opening_hours=None,  # not reliably available on local_results; see module docstring
        search_city=city,
        search_keyword=keyword,
        source="serpapi",
    )


class SerpApiMapsScraper:
    """Calls SerpApi's `google_maps` engine, paginating via `next_page_token`."""

    def __init__(self, api_key: str, max_results: int = 60, request_delay_seconds: float = 0.5):
        self._api_key = api_key
        self._max_results = max_results
        self._delay = request_delay_seconds

    @with_retry(_RETRYABLE_ERRORS)
    def _search_page(self, query: str, next_page_token: str | None) -> dict:
        params = {
            "engine": "google_maps",
            "type": "search",
            "q": query,
            "api_key": self._api_key,
        }
        if next_page_token:
            params["next_page_token"] = next_page_token
        return GoogleSearch(params).get_dict()

    def search(self, city: str, state: str, keyword: str) -> list[RawBusiness]:
        query = build_search_query(city, state, keyword)
        logger.info(f"Searching SerpApi (google_maps engine): '{query}'")

        results: list[RawBusiness] = []
        next_page_token: str | None = None

        while len(results) < self._max_results:
            time.sleep(self._delay)  # stay under SerpApi's rate limits

            try:
                page = self._search_page(query, next_page_token)
            except Exception as exc:
                logger.error(f"SerpApi search failed for '{query}': {exc}")
                break

            error = page.get("error")
            if error:
                logger.error(f"SerpApi returned an error for '{query}': {error}")
                break

            local_results = page.get("local_results", [])
            for item in local_results:
                if len(results) >= self._max_results:
                    break
                business = _item_to_business(item, city, keyword)
                if business is not None:
                    results.append(business)

            next_page_token = page.get("serpapi_pagination", {}).get("next_page_token")
            if not next_page_token:
                break

        if not results:
            logger.info(f"SerpApi returned 0 results for '{query}'")
        else:
            logger.info(f"Found {len(results)} results for '{query}' via SerpApi")
        return results
