"""Picks and constructs the configured Google Maps data provider.

Adding a new provider means adding one branch here and one new module in `scrapers/` —
nothing else in the pipeline needs to change, since every provider returns `RawBusiness`.
"""

from prospecting_agent.config import Settings
from prospecting_agent.scrapers.base import MapsScraper


def get_scraper(settings: Settings) -> MapsScraper:
    provider = settings.scraper_provider

    if provider == "apify":
        if not settings.apify_api_token:
            raise ValueError("SCRAPER_PROVIDER=apify requires APIFY_API_TOKEN to be set")
        from prospecting_agent.scrapers.google_maps import ApifyMapsScraper

        return ApifyMapsScraper(
            api_token=settings.apify_api_token,
            actor_id=settings.apify_google_maps_actor_id,
            max_results=settings.max_results_per_search,
            request_delay_seconds=settings.request_delay_seconds,
        )

    if provider == "serpapi":
        if not settings.serpapi_api_key:
            raise ValueError("SCRAPER_PROVIDER=serpapi requires SERPAPI_API_KEY to be set")
        from prospecting_agent.scrapers.google_maps_serpapi import SerpApiMapsScraper

        return SerpApiMapsScraper(
            api_key=settings.serpapi_api_key,
            max_results=settings.max_results_per_search,
            request_delay_seconds=settings.request_delay_seconds,
        )

    if provider == "places_api":
        if not settings.google_maps_api_key:
            raise ValueError("SCRAPER_PROVIDER=places_api requires GOOGLE_MAPS_API_KEY to be set")
        from prospecting_agent.scrapers.places_api import PlacesClient

        return PlacesClient(
            api_key=settings.google_maps_api_key,
            request_delay_seconds=settings.request_delay_seconds,
            max_results=settings.max_results_per_search,
        )

    raise ValueError(f"Unknown SCRAPER_PROVIDER: {provider!r}")
