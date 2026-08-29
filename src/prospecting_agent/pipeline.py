"""Ties every stage together: search grid -> scrape -> clean -> filter -> score -> write.

`main.py`'s CLI calls `run_pipeline` directly. Keeping the orchestration here (rather
than inline in the CLI file) means it can also be imported and run from a notebook,
test, or scheduler without going through Typer at all.
"""

from pathlib import Path
from typing import Callable, Optional

import yaml
from loguru import logger

from prospecting_agent.ai.openai_qualifier import OpenAIQualifier, score_leads
from prospecting_agent.config import Settings
from prospecting_agent.models import RawBusiness, ScoredLead
from prospecting_agent.processing.cleaner import clean_businesses
from prospecting_agent.processing.filters import filter_leads
from prospecting_agent.scrapers.factory import get_scraper
from prospecting_agent.storage.leads import AirtableLeadsManager


def load_cities(cities_path: Path) -> list[dict]:
    """Load the target cities list from a YAML config file."""
    return yaml.safe_load(cities_path.read_text())["cities"]


def load_keywords(keywords_path: Path) -> list[str]:
    """Load the target keywords list from a YAML config file."""
    return yaml.safe_load(keywords_path.read_text())["keywords"]


def _print_dry_run_summary(leads: list[ScoredLead]) -> None:
    """Console summary used in place of writing to Airtable when dry_run=True."""
    if not leads:
        logger.info("Dry run: no qualifying leads")
        return

    logger.info(f"Dry run: {len(leads)} qualifying lead(s) — not written to Airtable")
    for lead in leads:
        top_pain_point = lead.pain_points[0] if lead.pain_points else "—"
        print(f"  [{lead.score}/10] {lead.name} ({lead.search_city}) — {top_pain_point}")
        print(f"      {lead.full_outreach_message}")


def run_pipeline(
    settings: Settings,
    cities: list[dict],
    keywords: list[str],
    dry_run: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
) -> int:
    """Run the full pipeline end to end over an already-loaded (cities, keywords) grid.

    `on_progress`, if given, is called with a stage name ("finding", "deduping",
    "verifying", "scoring", "saving") as each stage starts — used by the webapp's async
    job runner to show real progress; unused (and harmless to omit) from the CLI.

    Returns the number of *new* leads written to Airtable (or, in a dry run, the number
    that would have been written) — existing leads refreshed by this run are logged but
    not counted here, to keep this return value's meaning unchanged for the CLI.
    """

    def _progress(stage: str) -> None:
        if on_progress is not None:
            on_progress(stage)

    total_searches = len(cities) * len(keywords)
    logger.info(f"Search grid: {len(cities)} cities x {len(keywords)} keywords = {total_searches} searches")

    # Connect to Airtable first, before any scraping or paid OpenAI calls — a bad
    # credential, wrong base id, or missing table then fails in under a second instead
    # of after a run that may have taken minutes and cost money.
    leads_manager = None
    if not dry_run:
        if not settings.airtable_api_key or not settings.airtable_base_id:
            raise ValueError(
                "AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set in .env for a real run — "
                "use --dry-run instead if you don't have Airtable set up yet."
            )
        leads_manager = AirtableLeadsManager.connect(
            settings.airtable_api_key,
            settings.airtable_base_id,
            settings.airtable_leads_table_name,
        )

    scraper = get_scraper(settings)
    qualifier = OpenAIQualifier(api_key=settings.openai_api_key, model=settings.openai_model)

    # --- Scrape stage ---
    # Rate limiting between individual requests happens inside the scraper implementation
    # (settings.request_delay_seconds); here we just make sure one bad city/keyword pair
    # can't take down the whole run.
    _progress("finding")
    raw_businesses: list[RawBusiness] = []
    for city in cities:
        for keyword in keywords:
            try:
                raw_businesses.extend(scraper.search(city["city"], city["state"], keyword))
            except Exception as exc:
                logger.error(f"Search failed for '{keyword}' in {city['city']}, {city['state']}: {exc}")

    if not raw_businesses:
        logger.warning("No businesses found across the entire search grid — stopping")
        return 0

    # --- Clean + filter stages ---
    _progress("deduping")
    cleaned = clean_businesses(raw_businesses)
    _progress("verifying")
    qualifying = filter_leads(cleaned)

    if not qualifying:
        logger.warning("No leads passed filtering — stopping before OpenAI scoring")
        return 0

    # --- Score stage (each call costs money — only runs on filtered leads) ---
    _progress("scoring")
    scored = score_leads(qualifying, qualifier, settings.min_lead_score)

    # --- Write stage ---
    _progress("saving")
    if dry_run:
        _print_dry_run_summary(scored)
        return len(scored)

    new_count, refreshed_count = leads_manager.append_new_leads(scored)
    if refreshed_count:
        logger.info(f"Also refreshed {refreshed_count} already-known lead(s)")
    return new_count
