"""Wraps the Google Places API: Text Search (find candidates) + Place Details (enrich with
phone/website/hours). This is the only module that talks to Google Maps — every other
module works with our own `RawBusiness` model, not raw API payloads.
"""

import time

import googlemaps
from loguru import logger

from prospecting_agent.models import RawBusiness
from prospecting_agent.utils.helpers import build_search_query
from prospecting_agent.utils.retry import with_retry

# Only request the fields we actually use — Places API bills per field group requested.
_DETAIL_FIELDS = [
    "place_id",
    "name",
    "formatted_address",
    "formatted_phone_number",
    "website",
    "rating",
    "user_ratings_total",
    "business_status",
    "type",
    "opening_hours",
]

_RETRYABLE_ERRORS = (
    googlemaps.exceptions.ApiError,
    googlemaps.exceptions.Timeout,
    googlemaps.exceptions.TransportError,
)


class PlacesClient:
    """Thin, rate-limited wrapper around the `googlemaps` SDK."""

    def __init__(self, api_key: str, request_delay_seconds: float = 0.5, max_results: int = 60):
        self._client = googlemaps.Client(key=api_key)
        self._delay = request_delay_seconds
        self._max_results = max_results

    @with_retry(_RETRYABLE_ERRORS)
    def _text_search_page(self, query: str, page_token: str | None) -> dict:
        if page_token:
            # A next_page_token isn't valid until a couple of seconds after it's issued.
            time.sleep(2)
            return self._client.places(query=query, page_token=page_token)
        return self._client.places(query=query)

    @with_retry(_RETRYABLE_ERRORS)
    def _place_details(self, place_id: str) -> dict:
        return self._client.place(place_id=place_id, fields=_DETAIL_FIELDS)["result"]

    def search(self, city: str, state: str, keyword: str) -> list[RawBusiness]:
        """Search for `keyword` businesses in `city, state` and return enriched results.

        Two API calls per result (Text Search + Place Details) is intentional: Text Search
        alone doesn't return phone/website, which we need for filtering and outreach.
        """
        query = build_search_query(city, state, keyword)
        logger.info(f"Searching Places API: '{query}'")

        results: list[RawBusiness] = []
        page_token: str | None = None

        while True:
            page = self._text_search_page(query, page_token)

            for candidate in page.get("results", []):
                if len(results) >= self._max_results:
                    break

                time.sleep(self._delay)  # stay comfortably under Places API rate limits

                try:
                    details = self._place_details(candidate["place_id"])
                except Exception as exc:
                    # One bad place_id shouldn't kill the whole city/keyword search.
                    logger.warning(f"Skipping place_id={candidate.get('place_id')}: {exc}")
                    continue

                hours = details.get("opening_hours") or {}
                results.append(
                    RawBusiness(
                        place_id=details["place_id"],
                        name=details.get("name", ""),
                        formatted_address=details.get("formatted_address"),
                        phone=details.get("formatted_phone_number"),
                        website=details.get("website"),
                        rating=details.get("rating"),
                        user_ratings_total=details.get("user_ratings_total"),
                        business_status=details.get("business_status"),
                        types=details.get("types", []),
                        opening_hours=hours.get("weekday_text"),
                        search_city=city,
                        search_keyword=keyword,
                        source="places_api",
                    )
                )

            page_token = page.get("next_page_token")
            if not page_token or len(results) >= self._max_results:
                break

        logger.info(f"Found {len(results)} results for '{query}'")
        return results
