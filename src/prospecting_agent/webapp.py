"""Flask chat UI for the prospecting agent.

Run with:

    prospecting-agent chat

or directly:

    python -m prospecting_agent.webapp

Lets you ask questions about leads already saved in Airtable, and propose a new
prospecting run for a city — which only actually executes after you click "Confirm &
Run" here in the app. A chat message alone never triggers a real (costly) run; see
`ai/chat_agent.py` for why that split exists.

Settings/Airtable/OpenAI are all validated and connected once at startup (`main()`),
not lazily per-request — same fail-fast philosophy as the CLI's `run` command.
"""

import webbrowser
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from pydantic import ValidationError

from prospecting_agent.ai.chat_agent import ChatAgent
from prospecting_agent.config import Settings, load_settings
from prospecting_agent.pipeline import load_cities, load_keywords, run_pipeline
from prospecting_agent.storage.leads import AirtableLeadsManager

app = Flask(__name__)

# Populated once by main() at startup; routes below assume these are set.
_settings: Settings | None = None
_agent: ChatAgent | None = None
_leads_manager: AirtableLeadsManager | None = None


@app.route("/")
def index():
    return render_template("chat.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json(force=True) or {}
    history = data.get("history", [])

    try:
        reply, proposed_run = _agent.send(history)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"reply": reply, "proposed_run": proposed_run})


@app.route("/api/cities", methods=["GET"])
def api_cities():
    """Populates the browse panel's dropdown: every city on the target list
    (config/cities.yaml) plus any city already in Airtable that isn't on that list
    (e.g. an earlier ad-hoc search). Each entry carries its state (so the UI can offer
    a "search this city now" action) and whether it already has leads.
    """
    try:
        existing = set(_leads_manager.list_cities())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    try:
        target = load_cities(Path("config/cities.yaml"))
    except Exception:
        target = []  # missing/bad yaml shouldn't break the dropdown

    cities = [{"city": c["city"], "state": c["state"], "has_leads": c["city"] in existing} for c in target]

    # Cities with leads but not on the target list (e.g. a one-off --city search) —
    # no known state for these, so the UI just won't offer "search again" for them.
    target_names = {c["city"] for c in target}
    for city in sorted(existing - target_names):
        cities.append({"city": city, "state": None, "has_leads": True})

    cities.sort(key=lambda c: c["city"])
    return jsonify({"cities": cities})


@app.route("/api/leads", methods=["GET"])
def api_leads():
    """Backs the browse/filter panel — a plain query, no chat/LLM involved."""
    city = request.args.get("city") or None
    category = request.args.get("category") or None
    status = request.args.get("status") or None
    limit = int(request.args.get("limit", 20))

    try:
        leads = _leads_manager.search_leads(city=city, category=category, status=status, limit=limit)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"leads": leads})


@app.route("/api/confirm_run", methods=["POST"])
def api_confirm_run():
    data = request.get_json(force=True) or {}
    city, state, keyword = data.get("city"), data.get("state"), data.get("keyword")

    if not city or not state:
        return jsonify({"error": "city and state are required"}), 400

    keywords = [keyword] if keyword else load_keywords(Path("config/keywords.yaml"))

    try:
        written = run_pipeline(_settings, [{"city": city, "state": state}], keywords, dry_run=False)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"written": written})


def create_app() -> Flask:
    """Load settings, connect Airtable, and build the chat agent — idempotent, so it's
    safe to call from both `main()` (local CLI use) and `wsgi.py` (production, where
    gunicorn imports this module without ever calling `main()`).
    """
    global _settings, _agent, _leads_manager

    if _leads_manager is not None:
        return app

    try:
        _settings = load_settings()
    except ValidationError as exc:
        print(f"Configuration error — check your environment variables (see .env.example):\n{exc}")
        raise SystemExit(1)

    if not _settings.airtable_api_key or not _settings.airtable_base_id:
        print("AIRTABLE_API_KEY and AIRTABLE_BASE_ID must be set to use the chat.")
        raise SystemExit(1)

    try:
        _leads_manager = AirtableLeadsManager.connect(
            _settings.airtable_api_key,
            _settings.airtable_base_id,
            _settings.airtable_leads_table_name,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"Couldn't connect to Airtable: {exc}")
        raise SystemExit(1)

    _agent = ChatAgent(_settings.openai_api_key, _settings.openai_model, _leads_manager)
    return app


def main() -> None:
    """Local/CLI entry point (`prospecting-agent chat`) — opens a browser against
    Flask's own dev server. Production (Render) uses `wsgi.py` + gunicorn instead,
    which calls `create_app()` directly and never reaches this function.
    """
    create_app()

    url = "http://127.0.0.1:5000"
    print(f"Chat UI running at {url} — opening your browser...")
    webbrowser.open(url)
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
