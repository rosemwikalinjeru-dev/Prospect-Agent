from conftest import FakeTable

from prospecting_agent.ai.chat_agent import ChatAgent
from prospecting_agent.storage.leads import AirtableLeadsManager


def _make_agent(records=None):
    leads_manager = AirtableLeadsManager(FakeTable(records=records or []))
    # api_key/model are never used by these tests — they only exercise _run_tool,
    # which doesn't touch the OpenAI client.
    return ChatAgent(api_key="unused", model="unused", leads_manager=leads_manager), leads_manager


def test_run_tool_search_leads_returns_matching_leads():
    agent, _ = _make_agent(records=[{"id": "r1", "fields": {"Name": "Acme HVAC", "City": "Dallas", "Score": 9}}])

    result, proposal = agent._run_tool("search_leads", {"city": "Dallas"})

    assert result["leads"][0]["Name"] == "Acme HVAC"
    assert proposal is None


def test_run_tool_export_leads_writes_csv(tmp_path, monkeypatch):
    agent, _ = _make_agent(records=[{"id": "r1", "fields": {"Name": "Acme HVAC", "Score": 9}}])
    monkeypatch.chdir(tmp_path)

    result, proposal = agent._run_tool("export_leads", {"min_score": 7})

    assert result["exported_count"] == 1
    assert (tmp_path / "leads_export.csv").exists()
    assert proposal is None


def test_run_tool_propose_run_does_not_execute_or_touch_leads():
    """propose_run must never itself write/read leads or trigger anything — the whole
    point is that only a human clicking Confirm in the UI can start a real run."""
    agent, _ = _make_agent()

    result, proposal = agent._run_tool("propose_run", {"city": "Miami", "state": "FL"})

    assert proposal["city"] == "Miami"
    assert proposal["state"] == "FL"
    assert proposal["estimated_results"] > 0
    assert "waiting" in result["status"]


def test_run_tool_unknown_tool_returns_error_not_exception():
    agent, _ = _make_agent()

    result, proposal = agent._run_tool("delete_everything", {})

    assert "error" in result
    assert proposal is None
