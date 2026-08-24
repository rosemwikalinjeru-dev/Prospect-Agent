"""Shared Airtable connection helper used by every storage class that talks to a
base/table (AirtableLeadsManager, CityRotationManager) — auth + table access + an
actionable error message on the common failure modes, in one place.
"""

import requests
from pyairtable import Api, Table


def get_table(api_key: str, base_id: str, table_name: str) -> Table:
    """Return a pyairtable Table client, failing fast with an actionable message on
    bad credentials/base/table rather than surfacing a raw HTTP error deep in a run.
    """
    table = Api(api_key).table(base_id, table_name)

    try:
        table.all(max_records=1)  # cheap request just to confirm access works
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        if status in (401, 403):
            raise RuntimeError(
                f"Airtable rejected the API key for base {base_id!r} — check "
                "AIRTABLE_API_KEY, and that the token has access to this base."
            ) from exc
        if status == 404:
            raise RuntimeError(
                f"Airtable table {table_name!r} not found in base {base_id!r} — check "
                f"AIRTABLE_BASE_ID, and that a table named exactly {table_name!r} exists."
            ) from exc
        raise RuntimeError(
            f"Airtable API error for base {base_id!r}, table {table_name!r}: {exc}"
        ) from exc

    return table
