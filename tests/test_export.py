import csv

from prospecting_agent.storage.export import write_csv


def test_write_csv_writes_header_and_rows(tmp_path):
    rows = [
        {"Name": "Acme HVAC", "Score": 9},
        {"Name": "Beta Plumbing", "Score": 8},
    ]
    output = tmp_path / "leads.csv"

    count = write_csv(rows, output)

    assert count == 2
    with output.open(newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert [r["Name"] for r in reader] == ["Acme HVAC", "Beta Plumbing"]


def test_write_csv_empty_rows_returns_zero_without_creating_file(tmp_path):
    output = tmp_path / "leads.csv"

    count = write_csv([], output)

    assert count == 0
    assert not output.exists()


def test_write_csv_creates_parent_directories(tmp_path):
    output = tmp_path / "nested" / "dir" / "leads.csv"

    write_csv([{"Name": "Acme HVAC"}], output)

    assert output.exists()
