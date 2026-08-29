"""Flask chat UI for the prospecting agent.

Run with:

    prospecting-agent chat

or directly:

    python -m prospecting_agent.webapp

Lets you ask questions about leads already saved in Airtable, browse/filter them, open a
lead's detail page, and either propose a new prospecting run via chat (only actually
executes after you click "Confirm & Run") or trigger one directly from the browse
panel's city dropdown (deliberately confirmation-free — see templates/chat.html). Real
runs execute as a background job so the page can show live progress instead of blocking
on one long request; see jobs.py.

Settings/Airtable/OpenAI are all validated and connected once at startup (`main()`),
not lazily per-request — same fail-fast philosophy as the CLI's `run` command.
"""

import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from loguru import logger
from pydantic import ValidationError

from prospecting_agent.ai.chat_agent import ChatAgent
from prospecting_agent.config import Settings, load_settings
from prospecting_agent.jobs import STAGE_LABELS, create_job, get_job, update_job
from prospecting_agent.pipeline import load_cities, load_keywords, run_pipeline
from prospecting_agent.storage.leads import STATUS_PIPELINE, AirtableLeadsManager

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


def _parse_bool_arg(name: str) -> bool | None:
    value = request.args.get(name)
    if value not in ("true", "false"):
        return None
    return value == "true"


def _parse_number_arg(name: str, cast):
    value = request.args.get(name)
    if not value:
        return None
    try:
        return cast(value)
    except ValueError:
        return None


@app.route("/api/leads", methods=["GET"])
def api_leads():
    """Backs the browse/filter panel — a plain query, no chat/LLM involved."""
    try:
        leads, total = _leads_manager.search_leads(
            city=request.args.get("city") or None,
            category=request.args.get("category") or None,
            status=request.args.get("status") or None,
            min_score=_parse_number_arg("min_score", int),
            has_website=_parse_bool_arg("has_website"),
            min_rating=_parse_number_arg("min_rating", float),
            min_reviews=_parse_number_arg("min_reviews", int),
            sort=request.args.get("sort") or None,
            limit=_parse_number_arg("limit", int) or 20,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    return jsonify({"leads": leads, "total": total})


@app.route("/leads/<place_id>")
def lead_detail(place_id):
    """Full profile for one lead — business overview, prospecting signals, and an
    outreach workspace (status/notes/follow-up, call/email/website/map links).
    """
    try:
        lead = _leads_manager.get_lead(place_id)
    except Exception as exc:
        return render_template("lead_detail.html", lead=None, error=str(exc), place_id=place_id), 500

    if lead is None:
        return render_template("lead_detail.html", lead=None, error="Lead not found.", place_id=place_id), 404

    return render_template("lead_detail.html", lead=lead, error=None, place_id=place_id, status_pipeline=STATUS_PIPELINE)


@app.route("/api/leads/<place_id>", methods=["POST"])
def api_update_lead(place_id):
    """Save edits from the detail page's outreach workspace — Status/Notes/Follow Up
    Date/Owner/Call Outcome/Last Contacted/Contact Attempts only; anything else in the
    request body is ignored rather than trusted, since scraped/computed fields should
    only ever change via a real re-search (see AirtableLeadsManager.append_new_leads).
    """
    data = request.get_json(force=True) or {}
    editable = {"Status", "Notes", "Follow Up Date", "Owner", "Call Outcome", "Last Contacted", "Contact Attempts"}
    fields = {k: v for k, v in data.items() if k in editable}

    if not fields:
        return jsonify({"error": "no editable fields provided"}), 400

    try:
        updated = _leads_manager.update_fields(place_id, fields)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    if not updated:
        return jsonify({"error": "lead not found"}), 404

    return jsonify({"status": "ok"})


@app.route("/api/confirm_run", methods=["POST"])
def api_confirm_run():
    """Starts a real search as a background job and returns immediately — the caller
    (chat's Confirm & Run, or the browse panel's city dropdown) polls
    /api/run_status/<job_id> for progress rather than blocking on one long request.
    """
    data = request.get_json(force=True) or {}
    city, state, keyword = data.get("city"), data.get("state"), data.get("keyword")

    if not city or not state:
        return jsonify({"error": "city and state are required"}), 400

    keywords = [keyword] if keyword else load_keywords(Path("config/keywords.yaml"))
    job_id = create_job()

    def _run_job() -> None:
        try:
            written = run_pipeline(
                _settings,
                [{"city": city, "state": state}],
                keywords,
                dry_run=False,
                on_progress=lambda stage: update_job(job_id, stage=stage),
            )
            update_job(job_id, status="done", written=written)
        except Exception as exc:
            logger.error(f"Background search job {job_id} failed: {exc}")
            update_job(job_id, status="error", error=str(exc))

    threading.Thread(target=_run_job, daemon=True).start()
    return jsonify({"job_id": job_id}), 202


@app.route("/api/run_status/<job_id>", methods=["GET"])
def api_run_status(job_id):
    job = get_job(job_id)
    if job is None:
        return jsonify({"error": "unknown job_id"}), 404

    return jsonify({**job, "stage_label": STAGE_LABELS.get(job["stage"], job["stage"])})


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

    try:
        default_keyword_count = len(load_keywords(Path("config/keywords.yaml")))
    except Exception:
        default_keyword_count = 1

    _agent = ChatAgent(
        _settings.openai_api_key,
        _settings.openai_model,
        _leads_manager,
        max_results_per_search=_settings.max_results_per_search,
        default_keyword_count=default_keyword_count,
    )
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
