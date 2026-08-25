"""CLI entrypoint for the prospecting agent.

Multi-city (default — every city x every keyword from the yaml configs):

    python -m prospecting_agent.main run

Single city, ad hoc, no yaml editing needed:

    python -m prospecting_agent.main run --city Dallas --state TX

Single city + single keyword + dry run (skips Airtable, prints to console):

    python -m prospecting_agent.main run --city Dallas --state TX --keyword "emergency plumber" --dry-run

Rotate through cities listed in the "Cities" table of your Airtable base, N per run:

    python -m prospecting_agent.main run --rotate-cities --cities-per-run 10

Export everything scored >= 7 (so far, across all runs) to a CSV:

    python -m prospecting_agent.main export --min-score 7 --output leads_export.csv

Open a browser chat UI to ask questions about your leads (and propose new searches):

    python -m prospecting_agent.main chat

Or, after `pip install -e .`, drop the `python -m prospecting_agent.main` prefix and
just use `prospecting-agent run ...` / `prospecting-agent export ...` / `prospecting-agent chat`.

This module deliberately contains no pipeline logic itself — it parses CLI args,
loads settings, sets up logging, and delegates to `pipeline.run_pipeline` (or the
storage layer directly for `export`). That keeps the pipeline importable/testable
independently of Typer.
"""

from pathlib import Path
from typing import List, Optional

import typer
from loguru import logger
from pydantic import ValidationError

from prospecting_agent.config import load_settings
from prospecting_agent.pipeline import load_cities, load_keywords, run_pipeline
from prospecting_agent.storage.city_rotation import CityRotationManager
from prospecting_agent.storage.export import write_csv
from prospecting_agent.storage.leads import AirtableLeadsManager
from prospecting_agent.utils.logger import configure_logging

app = typer.Typer(add_completion=False, help="AI Prospecting Agent for HVAC/Plumbing leads.")


@app.command()
def run(
    cities: Path = typer.Option(
        Path("config/cities.yaml"), help="Path to cities YAML config. Ignored if --city or --rotate-cities is given."
    ),
    keywords: Path = typer.Option(
        Path("config/keywords.yaml"), help="Path to keywords YAML config. Ignored if --keyword is given."
    ),
    city: Optional[str] = typer.Option(
        None, help="Run a single city instead of --cities/--rotate-cities. Requires --state."
    ),
    state: Optional[str] = typer.Option(None, help="Two-letter state code, used with --city."),
    rotate_cities: bool = typer.Option(
        False,
        "--rotate-cities",
        help="Pull the next batch of cities from the Airtable 'Cities' table instead of --cities.",
    ),
    cities_per_run: Optional[int] = typer.Option(
        None, help="Batch size for --rotate-cities. Overrides CITIES_PER_RUN from .env."
    ),
    keyword: Optional[List[str]] = typer.Option(
        None, help="Run only this keyword (repeat --keyword for more than one). Overrides --keywords."
    ),
    min_score: Optional[int] = typer.Option(
        None, min=1, max=10, help="Override MIN_LEAD_SCORE from .env for this run only."
    ),
    dry_run: bool = typer.Option(
        False, help="Skip Airtable entirely and print results to the console instead."
    ),
) -> None:
    """Run the pipeline: scrape Google Maps, clean/filter, score with OpenAI, save to Airtable."""
    try:
        settings = load_settings()
    except ValidationError as exc:
        typer.echo("Configuration error — check your .env against .env.example:", err=True)
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    configure_logging(settings.log_level)

    if min_score is not None:
        settings.min_lead_score = min_score

    rotation_manager: Optional[CityRotationManager] = None

    try:
        if city:
            if not state:
                logger.error("--city requires --state (e.g. --city Dallas --state TX)")
                raise typer.Exit(code=1)
            city_grid = [{"city": city, "state": state}]
        elif rotate_cities:
            if not settings.airtable_api_key or not settings.airtable_base_id:
                raise ValueError(
                    "AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set in .env to use "
                    "--rotate-cities (the rotation state lives in Airtable, even on a --dry-run)."
                )
            rotation_manager = CityRotationManager.connect(
                settings.airtable_api_key,
                settings.airtable_base_id,
                settings.airtable_cities_table_name,
            )
            rotation_manager.seed_if_empty(load_cities(cities))
            batch_size = cities_per_run if cities_per_run is not None else settings.cities_per_run
            city_grid = rotation_manager.get_next_batch(batch_size)
            if not city_grid:
                logger.warning("No active cities found in the rotation table — nothing to run")
                raise typer.Exit(code=0)
            logger.info(f"Rotation batch: {', '.join(c['city'] for c in city_grid)}")
        else:
            city_grid = load_cities(cities)

        keyword_grid = list(keyword) if keyword else load_keywords(keywords)

        logger.info("Starting prospecting run" + (" (dry run)" if dry_run else ""))
        written = run_pipeline(settings, city_grid, keyword_grid, dry_run=dry_run)

        if rotation_manager and not dry_run:
            rotation_manager.mark_run(city_grid)
    except typer.Exit:
        raise
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        # Configuration/credential problems raised by the scraper factory or the
        # Airtable connection — a short, actionable message rather than a full traceback.
        logger.error(f"Run stopped: {exc}")
        raise typer.Exit(code=1)
    except Exception:
        logger.exception("Pipeline run failed unexpectedly")
        raise typer.Exit(code=1)

    if dry_run:
        logger.success(f"Dry run complete — {written} qualifying lead(s)")
    else:
        logger.success(f"Done — {written} leads written to Airtable")


@app.command()
def export(
    min_score: int = typer.Option(7, min=1, max=10, help="Minimum score to include."),
    output: Path = typer.Option(Path("leads_export.csv"), help="CSV output path."),
) -> None:
    """Export leads already saved in Airtable with score >= min_score to a CSV file."""
    try:
        settings = load_settings()
    except ValidationError as exc:
        typer.echo("Configuration error — check your .env against .env.example:", err=True)
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)

    configure_logging(settings.log_level)

    try:
        if not settings.airtable_api_key or not settings.airtable_base_id:
            raise ValueError("AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set in .env to export.")
        leads_manager = AirtableLeadsManager.connect(
            settings.airtable_api_key,
            settings.airtable_base_id,
            settings.airtable_leads_table_name,
        )
        rows = leads_manager.read_leads(min_score)
        count = write_csv(rows, output)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        logger.error(f"Export stopped: {exc}")
        raise typer.Exit(code=1)
    except Exception:
        logger.exception("Export failed unexpectedly")
        raise typer.Exit(code=1)

    logger.success(f"Exported {count} lead(s) with score >= {min_score} to {output}")


@app.command()
def chat() -> None:
    """Open a browser chat UI to ask about your leads and propose new searches."""
    from prospecting_agent.webapp import main as run_webapp

    run_webapp()


if __name__ == "__main__":
    app()
