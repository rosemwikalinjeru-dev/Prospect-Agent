"""Shared pytest fixtures."""

import itertools
import re

import pytest

from prospecting_agent.models import CleanedLead, RawBusiness


class FakeTable:
    """Minimal in-memory stand-in for the pyairtable.Table methods our storage classes
    (AirtableLeadsManager, CityRotationManager) use — shared across their test files.

    Records are `{"id": str, "fields": dict}`, matching pyairtable's RecordDict shape.
    """

    def __init__(self, records: list[dict] | None = None):
        self.records: list[dict] = records if records is not None else []
        self._ids = itertools.count(1)

    def all(self, **options) -> list[dict]:
        max_records = options.get("max_records")
        return list(self.records[:max_records]) if max_records is not None else list(self.records)

    def create(self, fields: dict, typecast: bool = False, use_field_ids=None) -> dict:
        record = {"id": f"rec{next(self._ids)}", "fields": dict(fields)}
        self.records.append(record)
        return record

    def batch_create(self, records, typecast: bool = False, use_field_ids=None) -> list[dict]:
        return [self.create(fields) for fields in records]

    def update(self, record_id: str, fields: dict, replace: bool = False, typecast: bool = False, use_field_ids=None) -> dict:
        for record in self.records:
            if record["id"] == record_id:
                record["fields"].update(fields)
                return record
        raise KeyError(f"no fake record with id {record_id!r}")

    def first(self, **options):
        formula = options.get("formula")
        if formula is None:
            return self.records[0] if self.records else None
        # Only supports the one pattern this codebase actually generates: {Field} = 'value'
        match = re.match(r"\{([^}]+)\}\s*=\s*'([^']*)'", formula)
        if not match:
            raise NotImplementedError(f"FakeTable.first() formula not supported: {formula!r}")
        field_name, value = match.groups()
        for record in self.records:
            if record["fields"].get(field_name) == value:
                return record
        return None


@pytest.fixture
def make_raw_business():
    """Factory for a RawBusiness with sensible defaults, overridable per test."""

    def _make(**overrides) -> RawBusiness:
        defaults = dict(
            place_id="place_1",
            name="Test HVAC Co",
            formatted_address="123 Main St, Dallas, TX",
            phone="(214) 555-0100",
            website="https://testhvac.example.com",
            rating=4.2,
            user_ratings_total=15,
            business_status="OPERATIONAL",
            types=["hvac_contractor", "point_of_interest"],
            opening_hours=None,
            search_city="Dallas",
            search_keyword="HVAC repair",
            source="apify",
        )
        defaults.update(overrides)
        return RawBusiness(**defaults)

    return _make


@pytest.fixture
def make_cleaned_lead():
    """Factory for a CleanedLead with sensible defaults, overridable per test."""

    def _make(**overrides) -> CleanedLead:
        defaults = dict(
            place_id="place_1",
            name="Test HVAC Co",
            formatted_address="123 Main St, Dallas, TX",
            phone="(214) 555-0100",
            normalized_phone="+12145550100",
            website="https://testhvac.example.com",
            rating=4.2,
            user_ratings_total=15,
            business_status="OPERATIONAL",
            types=["hvac_contractor", "point_of_interest"],
            opening_hours=None,
            search_city="Dallas",
            search_keyword="HVAC repair",
            source="apify",
        )
        defaults.update(overrides)
        return CleanedLead(**defaults)

    return _make
