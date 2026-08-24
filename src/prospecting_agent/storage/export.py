"""CSV export for leads already saved to Airtable (see the `export` CLI command)."""

import csv
from pathlib import Path

from loguru import logger


def write_csv(rows: list[dict], output_path: Path) -> int:
    """Write `rows` (e.g. from AirtableLeadsManager.read_leads) to a CSV file using the
    rows' own keys as the header. Returns the number of rows written; 0 (with a log
    line, no error) if `rows` is empty.
    """
    if not rows:
        logger.info("No rows to export")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Exported {len(rows)} leads to {output_path}")
    return len(rows)
