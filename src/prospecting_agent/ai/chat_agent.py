"""Conversational layer over the prospecting agent — answers questions about leads
already saved in Airtable, and can propose (never silently execute) a new prospecting
run for the user to confirm in the UI.

Deliberately split into two kinds of tools:
- `search_leads` / `export_leads` execute immediately — read-only-ish, cheap, safe.
- `propose_run` never executes anything itself; it just returns the proposed
  parameters, which the caller (the Flask app / webapp.py) surfaces as an explicit
  Confirm/Cancel UI element. The actual scrape+score+write pipeline only runs if a
  human clicks Confirm — a chat message alone can never trigger it. This matters
  because a real run costs real money and takes several minutes.
"""

import json
from pathlib import Path

import openai
from loguru import logger

from prospecting_agent.storage.export import write_csv
from prospecting_agent.storage.leads import AirtableLeadsManager
from prospecting_agent.utils.retry import with_retry

SYSTEM_PROMPT = """You are a helpful assistant for an HVAC/Plumbing lead-prospecting tool. \
You can look up leads already saved in Airtable (search_leads), export them to CSV \
(export_leads), and propose running a brand new prospecting search for a city \
(propose_run).

Answer questions as asked — do not ask clarifying questions before calling search_leads. \
Every one of its filters (city, category, min_score, status) is optional, so act on \
whatever the user gave you: "leads in California" means call search_leads(city="California") \
immediately, even though California is a state and the City field holds city names — if \
that returns nothing, just say so and suggest a city, rather than asking a follow-up \
question first. Only ask the user something back if propose_run is genuinely missing \
required information (city and state) that nothing in the conversation supplies.

Ground every answer in actual tool results — never invent lead details, counts, or \
statistics you haven't actually looked up.

propose_run is special: calling it does NOT run anything. It only surfaces a proposal \
that the user must explicitly confirm in the app before it happens for real, because a \
real run costs API credits and takes several minutes. Never say a search has been run, \
is running, or has found leads unless a tool result actually told you so — after calling \
propose_run, tell the user you've set it up and they need to confirm it in the app."""

SEARCH_LEADS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_leads",
        "description": "Look up leads already saved in Airtable, with optional filters.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Filter by city (partial match, e.g. 'Dallas')."},
                "min_score": {"type": "integer", "description": "Minimum score, 1-10."},
                "status": {"type": "string", "description": "Filter by status, e.g. 'New', 'Contacted'."},
                "category": {"type": "string", "description": "Filter by trade category: 'HVAC' or 'Plumbing'."},
                "has_website": {"type": "boolean", "description": "True for leads with a website, false for leads with none."},
                "min_rating": {"type": "number", "description": "Minimum Google rating, e.g. 4.0."},
                "min_reviews": {"type": "integer", "description": "Minimum number of Google reviews."},
                "sort": {
                    "type": "string",
                    "description": "Sort order: 'score', 'rating', 'newest', or 'last_verified' (all descending).",
                },
                "limit": {"type": "integer", "description": "Max results to return (default 10)."},
            },
        },
    },
}

EXPORT_LEADS_TOOL = {
    "type": "function",
    "function": {
        "name": "export_leads",
        "description": "Export leads at/above a score to a CSV file on disk (leads_export.csv).",
        "parameters": {
            "type": "object",
            "properties": {
                "min_score": {"type": "integer", "description": "Minimum score to include (default 7)."},
            },
        },
    },
}

PROPOSE_RUN_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_run",
        "description": (
            "Propose running a new prospecting search for a city. Does NOT execute — "
            "surfaces a confirmation prompt in the app that the user must approve."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "state": {"type": "string", "description": "Two-letter US state code."},
                "keyword": {
                    "type": "string",
                    "description": "Optional search keyword, e.g. 'emergency plumber'. Omit to use all default keywords.",
                },
            },
            "required": ["city", "state"],
        },
    },
}

_TOOLS = [SEARCH_LEADS_TOOL, EXPORT_LEADS_TOOL, PROPOSE_RUN_TOOL]
_RETRYABLE_ERRORS = (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)
_MAX_TOOL_ROUNDS = 5  # safety valve against a runaway tool-call loop


class ChatAgent:
    def __init__(
        self,
        api_key: str,
        model: str,
        leads_manager: AirtableLeadsManager,
        max_results_per_search: int = 60,
        default_keyword_count: int = 1,
    ):
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model
        self._leads_manager = leads_manager
        # Used only to build propose_run's "estimated results" figure — not a promise,
        # just max_results_per_search x how many keywords a run with no --keyword would use.
        self._max_results_per_search = max_results_per_search
        self._default_keyword_count = default_keyword_count

    @with_retry(_RETRYABLE_ERRORS)
    def _complete(self, messages: list) -> object:
        return self._client.chat.completions.create(model=self._model, messages=messages, tools=_TOOLS)

    def _run_tool(self, name: str, args: dict) -> tuple[dict, dict | None]:
        """Execute one tool call. Returns (result_for_model, proposed_run_or_None)."""
        if name == "search_leads":
            leads, total = self._leads_manager.search_leads(**args)
            return {"leads": leads, "total_matched": total}, None

        if name == "export_leads":
            rows = self._leads_manager.read_leads(args.get("min_score", 7))
            count = write_csv(rows, Path("leads_export.csv"))
            return {"exported_count": count, "path": "leads_export.csv"}, None

        if name == "propose_run":
            # No side effect here — the UI is responsible for actually running the
            # pipeline, and only after the user clicks Confirm. Add an estimate so the
            # confirmation the UI shows says what will actually happen, not just "run?".
            keyword_count = 1 if args.get("keyword") else self._default_keyword_count
            proposal = {
                **args,
                "estimated_results": self._max_results_per_search * keyword_count,
                "data_source": "Google Maps (via Apify)",
            }
            return {"status": "proposed — waiting for the user to confirm in the app"}, proposal

        return {"error": f"unknown tool {name!r}"}, None

    def send(self, history: list[dict]) -> tuple[str, dict | None]:
        """`history` is the full chat so far (list of {"role", "content"} dicts, each
        role "user" or "assistant"), ending with the latest user message.

        Returns (assistant_reply_text, proposed_run). `proposed_run` is a
        {"city", "state", "keyword"} dict if the model proposed a run this turn,
        otherwise None.
        """
        messages: list = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
        proposed_run = None

        for _ in range(_MAX_TOOL_ROUNDS):
            response = self._complete(messages)
            message = response.choices[0].message

            if not message.tool_calls:
                return message.content or "", proposed_run

            messages.append(message)
            for tool_call in message.tool_calls:
                args = json.loads(tool_call.function.arguments or "{}")
                try:
                    result, this_proposal = self._run_tool(tool_call.function.name, args)
                except Exception as exc:
                    logger.error(f"Chat tool '{tool_call.function.name}' failed: {exc}")
                    result, this_proposal = {"error": str(exc)}, None

                if this_proposal is not None:
                    proposed_run = this_proposal

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, default=str),
                    }
                )

        logger.warning("Chat agent hit the max tool-call rounds without a final answer")
        return "Sorry, that took too many steps — could you rephrase or narrow your question?", proposed_run
