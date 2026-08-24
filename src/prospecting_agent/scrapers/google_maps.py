"""Google Maps data via Apify's "Google Maps Scraper" actor (compass/crawler-google-places).

This is the preferred provider: no per-request Google API billing, richer fields than the
Places API (e.g. explicit permanently/temporarily-closed flags), at the cost of being a
third-party scrape rather than an official API — review Apify's terms before high-volume use.
"""

import time
from typing import Any

from apify_client import ApifyClient
from loguru import logger

from prospecting_agent.models import RawBusiness
from prospecting_agent.utils.helpers import build_search_query
from prospecting_agent.utils.retry import with_retry

DEFAULT_ACTOR_ID = "compass/crawler-google-places"

# apify-client raises ApifyApiError (a subclass of Exception) for API-level failures and
# plain network exceptions for transport failures. Retrying on the broad Exception here —
# scoped tightly to just the actor-call/dataset-fetch methods below via @with_retry — is
# intentional: any failure at this specific call site is worth one retry before giving up.
_RETRYABLE_ERRORS = (Exception,)


def _business_status(item: dict) -> str:
    if item.get("permanentlyClosed"):
        return "CLOSED_PERMANENTLY"
    if item.get("temporarilyClosed"):
        return "CLOSED_TEMPORARILY"
    return "OPERATIONAL"


def _opening_hours(item: dict) -> list[str] | None:
    hours = item.get("openingHours")
    if not hours:
        return None
    # Apify returns a list of {"day": "Monday", "hours": "8 AM to 5 PM"} dicts.
    return [f"{h.get('day', '')}: {h.get('hours', '')}".strip(": ") for h in hours]


def _item_to_business(item: dict, city: str, keyword: str) -> RawBusiness | None:
    place_id = item.get("placeId")
    if not place_id:
        # Can't dedupe or write a usable lead without it — skip rather than fabricate one.
        logger.warning(f"Skipping Apify item with no placeId: {item.get('title')!r}")
        return None

    categories = item.get("categories") or ([item["categoryName"]] if item.get("categoryName") else [])

    return RawBusiness(
        place_id=place_id,
        name=item.get("title", ""),
        formatted_address=item.get("address"),
        phone=item.get("phone") or item.get("phoneUnformatted"),
        website=item.get("website"),
        rating=item.get("totalScore"),
        user_ratings_total=item.get("reviewsCount"),
        business_status=_business_status(item),
        types=categories,
        opening_hours=_opening_hours(item),
        search_city=city,
        search_keyword=keyword,
        source="apify",
    )


class ApifyMapsScraper:
    """Runs the Apify Google Maps Scraper actor for one (city, keyword) search per call."""

    def __init__(
        self,
        api_token: str,
        actor_id: str = DEFAULT_ACTOR_ID,
        max_results: int = 60,
        request_delay_seconds: float = 0.5,
    ):
        self._client = ApifyClient(api_token)
        self._actor_id = actor_id
        self._max_results = max_results
        self._delay = request_delay_seconds

    @with_retry(_RETRYABLE_ERRORS)
    def _run_actor(self, city: str, state: str, keyword: str) -> Any:
        # `searchStringsArray` and `locationQuery` are separate inputs to this actor —
        # it geolocates from `locationQuery` independently of the search string. Putting
        # the city only in the search string (with no locationQuery) makes the actor fall
        # back to scanning the entire country grid for the keyword, which is both wrong
        # and extremely expensive — this bit us in testing (a "Dallas" search scraped
        # 2,800+ places nationwide before hitting maxCrawledPlacesPerSearch).
        run_input = {
            "searchStringsArray": [keyword],
            "locationQuery": f"{city}, {state}, USA",
            "maxCrawledPlacesPerSearch": self._max_results,
            "language": "en",
        }
        # .call() submits the run and blocks until it finishes (or times out) — no
        # manual polling loop needed. Returns a `Run` object (attribute access), not a dict.
        return self._client.actor(self._actor_id).call(run_input=run_input)

    @with_retry(_RETRYABLE_ERRORS)
    def _fetch_dataset_items(self, dataset_id: str) -> list[dict]:
        return self._client.dataset(dataset_id).list_items().items

    def search(self, city: str, state: str, keyword: str) -> list[RawBusiness]:
        """Search for `keyword` businesses in `city, state` and return enriched results.

        Two API calls per result (Text Search + Place Details) is intentional: Text Search
        alone doesn't return phone/website, which we need for filtering and outreach.
        """
        query = build_search_query(city, state, keyword)  # used for logging only
        logger.info(f"Running Apify actor '{self._actor_id}' for '{query}'")
        time.sleep(self._delay)  # space out actor runs against Apify's concurrency limits

        try:
            run = self._run_actor(city, state, keyword)
        except Exception as exc:
            # A failed run for one (city, keyword) pair shouldn't take down the whole
            # search grid — pipeline.py also catches this, but we log with more detail here.
            logger.error(f"Apify actor run failed for '{query}': {exc}")
            return []

        if run.status != "SUCCEEDED":
            logger.warning(f"Apify actor run for '{query}' ended with status={run.status!r} — returning no results")
            return []

        dataset_id = run.default_dataset_id
        if not dataset_id:
            logger.warning(f"Apify actor run for '{query}' had no dataset — returning no results")
            return []

        try:
            items = self._fetch_dataset_items(dataset_id)
        except Exception as exc:
            logger.error(f"Failed to fetch Apify dataset for '{query}': {exc}")
            return []

        if not items:
            logger.info(f"Apify actor returned 0 results for '{query}'")
            return []

        results = [
            business
            for item in items
            if (business := _item_to_business(item, city, keyword)) is not None
        ]
        logger.info(f"Found {len(results)} results for '{query}' via Apify")
        return results
