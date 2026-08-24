"""Rotates through a list of target cities stored in an Airtable table, so scheduled
runs cover the whole list over time instead of hammering the same cities every run.

Table fields: City, State, Active (checkbox), Last Run At (date). Rotation picks the
least-recently-run active cities first — a city never run yet (no Last Run At value)
sorts before any date, since a missing field reads as an empty string.

Note on the Active checkbox: Airtable omits an unchecked checkbox field from the API
response entirely rather than returning `false` — there is no way to distinguish
"never set" from "explicitly unchecked." Every seeded city gets `Active: True`
explicitly, so in practice "not present" only happens when a user unchecks it in the
Airtable UI to pause that city — check the box to include a city in rotation, leave it
unchecked to exclude it.
"""

from datetime import date

from loguru import logger
from pyairtable import Table

from prospecting_agent.storage.airtable_helpers import get_table


class CityRotationManager:
    """Wraps one Airtable table. Construct via `.connect(...)` for real use; the plain
    constructor takes an already-built pyairtable `Table` directly, which keeps this
    class trivially testable with a fake table double.
    """

    def __init__(self, table: Table):
        self._table = table

    @classmethod
    def connect(cls, api_key: str, base_id: str, table_name: str) -> "CityRotationManager":
        return cls(get_table(api_key, base_id, table_name))

    def seed_if_empty(self, default_cities: list[dict]) -> None:
        """If the table has no records yet, populate it from `default_cities`
        (city/state pairs, e.g. from config/cities.yaml) so a brand-new rotation table
        is usable immediately without manual data entry.
        """
        if self._table.all(max_records=1):
            return  # already has data

        records = [{"City": c["city"], "State": c["state"], "Active": True} for c in default_cities]
        if not records:
            return

        self._table.batch_create(records, typecast=True)
        logger.info(f"Seeded Airtable Cities table with {len(records)} default cities")

    def get_next_batch(self, n: int) -> list[dict]:
        """Return the `n` active cities least recently run, as
        `[{"city", "state", "_record_id"}, ...]`. `_record_id` rides along so
        `mark_run` can update the right record without a second lookup.
        """
        candidates = []
        for record in self._table.all():
            fields = record["fields"]
            if fields.get("Active") is not True:
                continue
            last_run_at = fields.get("Last Run At") or ""
            candidates.append((last_run_at, record["id"], fields))

        candidates.sort(key=lambda c: c[0])

        return [
            {"city": fields.get("City", ""), "state": fields.get("State", ""), "_record_id": record_id}
            for _, record_id, fields in candidates[:n]
        ]

    def mark_run(self, cities: list[dict]) -> None:
        """Stamp today's date in Last Run At for each city just run."""
        today = date.today().isoformat()
        for city in cities:
            record_id = city.get("_record_id")
            if record_id is None:
                continue
            self._table.update(record_id, {"Last Run At": today}, typecast=True)
        logger.info(f"Marked {len(cities)} cities as run today ({today})")
