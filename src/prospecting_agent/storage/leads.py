"""Airtable storage for qualified leads: duplicate detection by place_id/phone,
appending new leads, and updating a lead's status later.
"""

from datetime import date

from loguru import logger
from pyairtable import Table

from prospecting_agent.models import ScoredLead
from prospecting_agent.storage.airtable_helpers import get_table


def _lead_to_fields(lead: ScoredLead) -> dict:
    return {
        "Name": lead.name,
        "Phone": lead.normalized_phone or lead.phone or "",
        "Website": lead.website or "",
        "City": lead.search_city,
        "Rating": lead.rating,
        "Reviews": lead.user_ratings_total,
        "Score": lead.score,
        "Pain Points": "; ".join(lead.pain_points),
        "Personalized Message": lead.full_outreach_message,
        "Status": "New",
        "Date Added": date.today().isoformat(),
        "Source": lead.source,
        "Place ID": lead.place_id,
    }


class AirtableLeadsManager:
    """Wraps one Airtable table. Construct via `.connect(...)` for real use; the plain
    constructor takes an already-built pyairtable `Table` directly, which keeps this
    class trivially testable with a fake table double.
    """

    def __init__(self, table: Table):
        self._table = table

    @classmethod
    def connect(cls, api_key: str, base_id: str, table_name: str) -> "AirtableLeadsManager":
        return cls(get_table(api_key, base_id, table_name))

    def _existing_keys(self) -> tuple[set[str], set[str]]:
        """Return (place_ids, phones) already present, for duplicate checks."""
        place_ids: set[str] = set()
        phones: set[str] = set()
        for record in self._table.all():
            fields = record["fields"]
            if fields.get("Place ID"):
                place_ids.add(fields["Place ID"])
            if fields.get("Phone"):
                phones.add(fields["Phone"])
        return place_ids, phones

    def append_new_leads(self, leads: list[ScoredLead]) -> int:
        """Append leads not already present (by place_id or phone). Returns the number
        of records actually written — 0 if `leads` is empty or every lead is a duplicate.
        """
        if not leads:
            logger.info("No leads to write to Airtable")
            return 0

        existing_place_ids, existing_phones = self._existing_keys()

        new_records = []
        for lead in leads:
            phone = lead.normalized_phone or lead.phone
            if lead.place_id in existing_place_ids or (phone and phone in existing_phones):
                logger.debug(f"Skipping duplicate lead '{lead.name}' ({lead.place_id})")
                continue
            new_records.append(_lead_to_fields(lead))
            existing_place_ids.add(lead.place_id)
            if phone:
                existing_phones.add(phone)

        if not new_records:
            logger.info("All leads were already in Airtable — nothing new to write")
            return 0

        self._table.batch_create(new_records, typecast=True)
        logger.info(f"Wrote {len(new_records)} new leads to Airtable")
        return len(new_records)

    def read_leads(self, min_score: int) -> list[dict]:
        """Return every record's fields with Score >= min_score — used by `export`."""
        rows = []
        for record in self._table.all():
            fields = record["fields"]
            try:
                score = int(fields.get("Score", ""))
            except (TypeError, ValueError):
                continue
            if score >= min_score:
                rows.append(fields)
        return rows

    def update_status(self, place_id: str, new_status: str) -> bool:
        """Find the record for `place_id` and update its Status field.

        Returns False (and logs a warning) if no record matches, rather than raising —
        a stale/unknown place_id shouldn't crash whatever's calling this.
        """
        record = self._table.first(formula=f"{{Place ID}} = '{place_id}'")
        if record is None:
            logger.warning(f"Could not find place_id={place_id!r} to update status")
            return False

        self._table.update(record["id"], {"Status": new_status}, typecast=True)
        logger.info(f"Updated status for place_id={place_id!r} to '{new_status}'")
        return True
