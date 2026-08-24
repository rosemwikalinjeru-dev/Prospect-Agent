"""The contract every Google Maps data provider must satisfy, so `pipeline.py` and every
downstream stage (cleaner/filters/scorer/sheets) can work with any of them interchangeably.
"""

from typing import Protocol

from prospecting_agent.models import RawBusiness


class MapsScraper(Protocol):
    def search(self, city: str, state: str, keyword: str) -> list[RawBusiness]:
        """Search for `keyword` businesses in `city, state` and return results as
        RawBusiness. Must never raise on a zero-result search — return [] instead.
        """
        ...
