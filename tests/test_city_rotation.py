from conftest import FakeTable

from prospecting_agent.storage.city_rotation import CityRotationManager


def test_seed_if_empty_populates_from_defaults():
    table = FakeTable()
    manager = CityRotationManager(table)

    manager.seed_if_empty([{"city": "Dallas", "state": "TX"}, {"city": "Phoenix", "state": "AZ"}])

    assert len(table.records) == 2
    assert table.records[0]["fields"] == {"City": "Dallas", "State": "TX", "Active": True}
    assert table.records[1]["fields"] == {"City": "Phoenix", "State": "AZ", "Active": True}


def test_seed_if_empty_noop_when_data_already_present():
    table = FakeTable(records=[{"id": "rec1", "fields": {"City": "Existing", "State": "OH", "Active": True}}])
    manager = CityRotationManager(table)

    manager.seed_if_empty([{"city": "Dallas", "state": "TX"}])

    assert len(table.records) == 1  # unchanged


def test_get_next_batch_prioritizes_never_run_and_oldest():
    table = FakeTable(
        records=[
            {"id": "r1", "fields": {"City": "Recent", "State": "TX", "Active": True, "Last Run At": "2026-08-01"}},
            {"id": "r2", "fields": {"City": "NeverRun", "State": "AZ", "Active": True}},
            {"id": "r3", "fields": {"City": "Oldest", "State": "FL", "Active": True, "Last Run At": "2026-01-01"}},
        ]
    )
    manager = CityRotationManager(table)

    batch = manager.get_next_batch(2)

    assert [c["city"] for c in batch] == ["NeverRun", "Oldest"]


def test_get_next_batch_skips_inactive_cities():
    # Airtable omits an unchecked checkbox field entirely rather than sending False.
    table = FakeTable(
        records=[
            {"id": "r1", "fields": {"City": "Inactive", "State": "TX"}},
            {"id": "r2", "fields": {"City": "Active", "State": "AZ", "Active": True}},
        ]
    )
    manager = CityRotationManager(table)

    batch = manager.get_next_batch(5)

    assert [c["city"] for c in batch] == ["Active"]


def test_get_next_batch_respects_batch_size():
    table = FakeTable(
        records=[
            {"id": "r1", "fields": {"City": "A", "State": "TX", "Active": True}},
            {"id": "r2", "fields": {"City": "B", "State": "TX", "Active": True}},
            {"id": "r3", "fields": {"City": "C", "State": "TX", "Active": True}},
        ]
    )
    manager = CityRotationManager(table)

    assert len(manager.get_next_batch(2)) == 2


def test_mark_run_updates_last_run_field():
    table = FakeTable(records=[{"id": "r1", "fields": {"City": "Dallas", "State": "TX", "Active": True}}])
    manager = CityRotationManager(table)
    batch = manager.get_next_batch(1)

    manager.mark_run(batch)

    assert table.records[0]["fields"]["Last Run At"]
