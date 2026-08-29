"""Airtable storage for qualified leads: duplicate detection by place_id/phone,
appending new leads, refreshing already-known ones, and editing status/notes/follow-up
fields later from the detail page.
"""

from datetime import date

from loguru import logger
from pyairtable import Table

from prospecting_agent.models import ScoredLead
from prospecting_agent.storage.airtable_helpers import get_table
from prospecting_agent.utils.duplicates import is_probable_duplicate, normalize_business_name
from prospecting_agent.utils.helpers import categorize_keyword

# The Section 7 prospecting pipeline — used by the Status single-select field and the
# lead-detail page's status dropdown. "New" is the default a fresh scrape/score writes.
STATUS_PIPELINE = ["New", "Reviewed", "Contacted", "Follow-up", "Qualified", "Won", "Not a fit"]

# Fields a human may have edited on an existing record — never overwritten by a re-scrape,
# only ever changed via update_fields() from the detail page.
_HUMAN_OWNED_FIELDS = {
    "Status",
    "Notes",
    "Follow Up Date",
    "Owner",
    "Call Outcome",
    "Last Contacted",
    "Contact Attempts",
}

# Everything else in _lead_to_fields is scraped/computed and safe to overwrite on refresh.
_REFRESHABLE_FIELDS = [
    "Name",
    "Phone",
    "Website",
    "Google Maps URL",
    "Address",
    "City",
    "Category",
    "Rating",
    "Reviews",
    "Business Status",
    "Opening Hours",
    "Score",
    "Service Need Score",
    "Website Opportunity Score",
    "Review Profile Score",
    "Contactability Score",
    "Business Activity Score",
    "Reason",
    "Pain Points",
    "Recommended Offer",
    "Personalized First Line",
    "Personalized Message",
    "Source",
    "Last Verified",
]


def _lead_to_fields(lead: ScoredLead, duplicate_risk: str = "Low") -> dict:
    return {
        "Name": lead.name,
        "Phone": lead.normalized_phone or lead.phone or "",
        "Website": lead.website or "",
        "Google Maps URL": lead.google_maps_url or "",
        "Address": lead.formatted_address or "",
        "City": lead.search_city,
        "Category": categorize_keyword(lead.search_keyword),
        "Rating": lead.rating,
        "Reviews": lead.user_ratings_total,
        "Business Status": lead.business_status or "",
        "Opening Hours": "; ".join(lead.opening_hours) if lead.opening_hours else "",
        "Score": lead.score,
        "Service Need Score": lead.service_need_score,
        "Website Opportunity Score": lead.website_opportunity_score,
        "Review Profile Score": lead.review_profile_score,
        "Contactability Score": lead.contactability_score,
        "Business Activity Score": lead.business_activity_score,
        "Reason": lead.reason,
        "Pain Points": "; ".join(lead.pain_points),
        "Recommended Offer": lead.recommended_offer,
        "Personalized First Line": lead.personalized_first_line,
        "Personalized Message": lead.full_outreach_message,
        "Status": "New",
        "Duplicate Risk": duplicate_risk,
        "Date Added": date.today().isoformat(),
        "Last Verified": date.today().isoformat(),
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

    def _existing_index(self) -> tuple[dict[str, dict], dict[str, dict], dict[str, set[str]]]:
        """One pass over the table building everything append_new_leads needs: records
        keyed by Place ID and by Phone (for dedup/refresh lookups), plus the set of
        normalized business names already seen per city (for the soft duplicate-name
        check — see utils/duplicates.py).
        """
        by_place_id: dict[str, dict] = {}
        by_phone: dict[str, dict] = {}
        names_by_city: dict[str, set[str]] = {}
        for record in self._table.all():
            fields = record["fields"]
            if fields.get("Place ID"):
                by_place_id[fields["Place ID"]] = record
            if fields.get("Phone"):
                by_phone[fields["Phone"]] = record
            city, name = fields.get("City"), fields.get("Name")
            if city and name:
                names_by_city.setdefault(city, set()).add(normalize_business_name(name))
        return by_place_id, by_phone, names_by_city

    def append_new_leads(self, leads: list[ScoredLead]) -> tuple[int, int]:
        """Write leads not already present, and refresh the scraped/computed fields on
        ones that already exist (matched by Place ID or phone) instead of silently
        skipping them — this is what makes re-searching a city a real "refresh," not
        just a way to find brand-new businesses. Human-owned fields (Status, Notes,
        Follow Up Date, Owner, Call Outcome, Last Contacted, Contact Attempts) are never
        touched by a refresh — only ever changed via update_fields().

        Returns (new_count, refreshed_count) — both 0 if `leads` is empty.
        """
        if not leads:
            logger.info("No leads to write to Airtable")
            return 0, 0

        by_place_id, by_phone, names_by_city = self._existing_index()

        new_records = []
        refreshed = 0
        seen_place_ids: set[str] = set()
        seen_phones: set[str] = set()

        for lead in leads:
            phone = lead.normalized_phone or lead.phone
            existing = by_place_id.get(lead.place_id) or (by_phone.get(phone) if phone else None)

            if existing is not None:
                fields = {k: v for k, v in _lead_to_fields(lead).items() if k in _REFRESHABLE_FIELDS}
                self._table.update(existing["id"], fields, typecast=True)
                refreshed += 1
                logger.debug(f"Refreshed existing lead '{lead.name}' ({lead.place_id})")
                continue

            if lead.place_id in seen_place_ids or (phone and phone in seen_phones):
                logger.debug(f"Skipping duplicate lead '{lead.name}' ({lead.place_id}) within this batch")
                continue

            city_names = names_by_city.setdefault(lead.search_city, set())
            duplicate_risk = "Medium" if is_probable_duplicate(lead.name, city_names) else "Low"

            new_records.append(_lead_to_fields(lead, duplicate_risk))
            seen_place_ids.add(lead.place_id)
            if phone:
                seen_phones.add(phone)
            city_names.add(normalize_business_name(lead.name))

        if new_records:
            self._table.batch_create(new_records, typecast=True)

        logger.info(f"Wrote {len(new_records)} new lead(s), refreshed {refreshed} existing lead(s)")
        return len(new_records), refreshed

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

    def list_cities(self) -> list[str]:
        """Return the distinct, sorted City values across all leads — used to populate
        the browse panel's city dropdown so it only ever offers cities that actually
        have data, instead of a free-text box that can't guess what's been searched.
        """
        cities = {
            str(record["fields"]["City"]).strip()
            for record in self._table.all()
            if record["fields"].get("City")
        }
        return sorted(cities)

    _SORT_KEYS = {
        "score": lambda f: f.get("Score") or 0,
        "rating": lambda f: f.get("Rating") or 0,
        "newest": lambda f: f.get("Date Added") or "",
        "last_verified": lambda f: f.get("Last Verified") or "",
    }

    def search_leads(
        self,
        city: str | None = None,
        min_score: int | None = None,
        status: str | None = None,
        category: str | None = None,
        has_website: bool | None = None,
        min_rating: float | None = None,
        min_reviews: int | None = None,
        sort: str | None = None,
        limit: int = 10,
    ) -> tuple[list[dict], int]:
        """Free-form lead lookup — used by both the chat agent and the browse/filter UI.
        All filters are optional and combine with AND. `city` and `status` match
        case-insensitively; `city` is a substring match (so "dallas" matches "Dallas").
        `category` matches exactly, case-insensitively (e.g. "HVAC", "Plumbing").
        `sort` is one of "score"/"rating"/"newest"/"last_verified" (descending) or None
        for Airtable's own row order. Returns `(results, total_matched)` — `results` is
        capped at `limit`, `total_matched` is the full count before capping (for a
        "128 leads" style result count in the UI).
        """
        matched = []
        for record in self._table.all():
            fields = record["fields"]

            if city and city.lower() not in str(fields.get("City", "")).lower():
                continue

            if min_score is not None:
                try:
                    if int(fields.get("Score", 0)) < min_score:
                        continue
                except (TypeError, ValueError):
                    continue

            if status and str(fields.get("Status", "")).lower() != status.lower():
                continue

            if category and str(fields.get("Category", "")).lower() != category.lower():
                continue

            if has_website is not None and bool(fields.get("Website")) != has_website:
                continue

            if min_rating is not None and (fields.get("Rating") or 0) < min_rating:
                continue

            if min_reviews is not None and (fields.get("Reviews") or 0) < min_reviews:
                continue

            matched.append(fields)

        if sort in self._SORT_KEYS:
            matched.sort(key=self._SORT_KEYS[sort], reverse=True)

        return matched[:limit], len(matched)

    def get_lead(self, place_id: str) -> dict | None:
        """Return one lead's fields by Place ID, or None if it doesn't exist — backs the
        lead-detail page.
        """
        record = self._table.first(formula=f"{{Place ID}} = '{place_id}'")
        return record["fields"] if record is not None else None

    def update_fields(self, place_id: str, fields: dict) -> bool:
        """Find the record for `place_id` and update arbitrary fields on it — used by
        the detail page's Save button (Status, Notes, Follow Up Date, Owner, Call
        Outcome, Last Contacted, Contact Attempts).

        Returns False (and logs a warning) if no record matches, rather than raising —
        a stale/unknown place_id shouldn't crash whatever's calling this.
        """
        record = self._table.first(formula=f"{{Place ID}} = '{place_id}'")
        if record is None:
            logger.warning(f"Could not find place_id={place_id!r} to update")
            return False

        self._table.update(record["id"], fields, typecast=True)
        logger.info(f"Updated place_id={place_id!r}: {list(fields)}")
        return True

    def update_status(self, place_id: str, new_status: str) -> bool:
        """Convenience wrapper around update_fields() for just the Status field."""
        return self.update_fields(place_id, {"Status": new_status})
