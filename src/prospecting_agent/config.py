"""Typed application settings, loaded and validated from environment variables (.env).

Loading this once at startup means a missing API key fails immediately with a clear
error, instead of failing midway through a run after burning API quota.
"""

from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # OpenAI
    openai_api_key: str
    openai_model: str = "gpt-4o"

    # Maps data provider — see scrapers/factory.py. Only the credential for whichever
    # provider is selected actually needs to be set; the rest can stay blank in .env.
    scraper_provider: Literal["apify", "serpapi", "places_api"] = "apify"

    apify_api_token: Optional[str] = None
    apify_google_maps_actor_id: str = "compass/crawler-google-places"

    serpapi_api_key: Optional[str] = None

    # Google Maps (Places API) — only required if scraper_provider="places_api"
    google_maps_api_key: Optional[str] = None

    # Airtable — api_key/base_id are optional at the settings level so `--dry-run`
    # (which never touches storage) works with no Airtable setup at all; anything that
    # actually needs it (a real run, or --rotate-cities) validates it's set at the
    # point of use instead.
    airtable_api_key: Optional[str] = None
    airtable_base_id: Optional[str] = None
    airtable_leads_table_name: str = "Leads"
    airtable_cities_table_name: str = "Cities"

    # Pipeline behavior
    min_lead_score: int = Field(default=7, ge=1, le=10)
    max_results_per_search: int = 60
    request_delay_seconds: float = 0.5
    cities_per_run: int = 5
    log_level: str = "INFO"


def load_settings() -> Settings:
    """Load and validate settings from the environment/.env file."""
    return Settings()
