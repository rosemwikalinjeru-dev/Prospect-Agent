"""The brain of the agent: sends each cleaned lead to OpenAI, gets back a qualification
score plus a ready-to-send outreach message offering the free "Missed Call Revenue Audit."

Kept as a single file deliberately — the system prompt, the schema that constrains the
model's output, the per-lead prompt builder, the API wrapper, and the batch-scoring loop
are one small, cohesive unit rather than a package.
"""

import json

import openai
from loguru import logger

from prospecting_agent.models import CleanedLead, ScoredLead
from prospecting_agent.utils.retry import with_retry
from prospecting_agent.utils.scoring import (
    DEFAULT_WEIGHTS,
    business_activity_score,
    compute_weighted_score,
    contactability_score,
    review_profile_score,
    website_opportunity_score,
)

# --- System prompt -----------------------------------------------------------------

SYSTEM_PROMPT = """You are a lead-qualification analyst for a company that offers home-service \
businesses (HVAC and plumbing companies) a free "Missed Call Revenue Audit" — a short, \
no-obligation review that shows an owner roughly how many inbound calls their business is \
likely missing each month, and what that's probably costing them in booked jobs.

You will be given structured data about one business, pulled from Google Maps. Your job is \
to judge one specific thing from that data — how strongly this business's overall situation \
suggests they'd benefit from the audit offer — and to draft an outreach message a real \
person could send as-is, with no editing. (Website presence, review profile, contactability, \
and business activity are scored separately, outside your judgment — focus purely on the \
holistic "does this business's situation suggest missed calls" read.)

HOW TO SCORE service_need_score (1-10):
Score high when the business's overall profile (category, how established it seems, hours,
status) suggests it's plausibly missing calls or under-resourced for its call volume. Score \
low when the business looks well-resourced and clearly dialed in operationally. Don't inflate \
the score just because a business is a plausible-sounding HVAC/plumbing company.

HOW TO WRITE — this is the part most cold outreach gets wrong:
Write like a person who actually looked at this specific business, not a marketing template \
with the name swapped in.
- No hype words ("amazing," "incredible," "huge opportunity"), no exclamation points, no \
  fake urgency ("don't miss out," "limited time offer").
- State observations, not compliments or criticisms. "Your listing doesn't show a website" \
  reads completely differently from "your online presence could use some work" — use the \
  former register throughout.
- The free audit is a low-pressure offer to look at something concrete, not a sales pitch. \
  Frame it as something the owner can take or leave with zero cost either way — never \
  pressure, never a hard close.
- Ground every field in the data you were actually given. If a signal is weak or absent, say \
  less about it — never invent a specific detail (a number, a claim about their competitors, \
  a fabricated quote) that wasn't in the input.

Respond with a JSON object matching the required schema — nothing else."""

# --- Structured output schema -------------------------------------------------------
# OpenAI's Structured Outputs (strict JSON schema mode) guarantees the response matches
# this shape exactly, so no brittle free-text parsing is needed downstream.

LEAD_EVALUATION_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "lead_evaluation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "service_need_score": {
                    "type": "integer",
                    "description": (
                        "1-10: how strongly this business's overall situation suggests they'd "
                        "benefit from the Missed Call Revenue Audit offer."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "1-2 sentence justification for the score, grounded in the given data.",
                },
                "pain_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "1-3 short, specific, data-grounded signals that this business may be "
                        "missing calls or revenue (e.g. 'no website listed', "
                        "'only 6 reviews despite years in business')."
                    ),
                },
                "recommended_offer": {
                    "type": "string",
                    "description": (
                        "One sentence framing the free Missed Call Revenue Audit specifically "
                        "around this business's biggest gap."
                    ),
                },
                "personalized_first_line": {
                    "type": "string",
                    "description": (
                        "A single opening line for a cold message, naming the business and one "
                        "concrete, real observation about it."
                    ),
                },
                "full_outreach_message": {
                    "type": "string",
                    "description": (
                        "A complete, ready-to-send outreach message (3-6 sentences): opens with "
                        "the idea in personalized_first_line, names 1-2 pain_points, offers the "
                        "free audit per recommended_offer, and ends with a low-pressure call to "
                        "action."
                    ),
                },
            },
            "required": [
                "service_need_score",
                "reason",
                "pain_points",
                "recommended_offer",
                "personalized_first_line",
                "full_outreach_message",
            ],
            "additionalProperties": False,
        },
    },
}

_RETRYABLE_ERRORS = (openai.APIConnectionError, openai.RateLimitError, openai.InternalServerError)


def build_lead_prompt(lead: CleanedLead) -> str:
    """Build the per-lead fact sheet the model evaluates. Deliberately just facts — no
    framing or persuasion here, that's the system prompt's job."""
    return (
        f"Business: {lead.name}\n"
        f"Category/search keyword: {lead.search_keyword}\n"
        f"City: {lead.search_city}\n"
        f"Website: {lead.website or 'none listed'}\n"
        f"Google rating: {lead.rating or 'no rating'} ({lead.user_ratings_total or 0} reviews)\n"
        f"Listed hours: {'yes' if lead.opening_hours else 'no'}\n"
        f"Business status: {lead.business_status or 'unknown'}"
    )


class OpenAIQualifier:
    """Scores and drafts outreach for one lead per call. Kept one-lead-per-call (rather
    than batching many leads into one prompt) so a single bad response never corrupts
    other leads' results, and so results can be retried individually.
    """

    def __init__(self, api_key: str, model: str):
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model

    @with_retry(_RETRYABLE_ERRORS)
    def evaluate(self, lead: CleanedLead) -> dict:
        """Return the parsed lead-evaluation dict for one lead.

        Uses Structured Outputs (`response_format`) so the response is always
        schema-conformant JSON, not free text that would need brittle parsing.
        """
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=1536,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_lead_prompt(lead)},
            ],
            response_format=LEAD_EVALUATION_SCHEMA,
        )

        message = response.choices[0].message
        if message.refusal:
            raise ValueError(f"Model refused to evaluate '{lead.name}': {message.refusal}")

        return json.loads(message.content)


def score_leads(leads: list[CleanedLead], qualifier: OpenAIQualifier, min_score: int) -> list[ScoredLead]:
    """Score every lead: OpenAI judges `service_need_score`, the other four factors are
    computed deterministically from data already on the lead (see utils/scoring.py),
    then blended into the single `score` used for filtering/display. Keep only those
    at/above `min_score`.

    A single lead failing to score (API error, malformed response) is logged and
    skipped rather than aborting the whole batch.
    """
    scored: list[ScoredLead] = []

    for lead in leads:
        try:
            result = qualifier.evaluate(lead)
            sub_scores = {
                "service_need_score": float(result["service_need_score"]),
                "website_opportunity_score": website_opportunity_score(lead),
                "review_profile_score": review_profile_score(lead),
                "contactability_score": contactability_score(lead),
                "business_activity_score": business_activity_score(lead),
            }
            weighted_score = compute_weighted_score(sub_scores, DEFAULT_WEIGHTS)
            passed = weighted_score >= min_score
            lead_result = (
                ScoredLead(
                    **lead.model_dump(),
                    score=weighted_score,
                    **sub_scores,
                    reason=result["reason"],
                    pain_points=result["pain_points"],
                    recommended_offer=result["recommended_offer"],
                    personalized_first_line=result["personalized_first_line"],
                    full_outreach_message=result["full_outreach_message"],
                )
                if passed
                else None
            )
        except Exception as exc:
            # Covers both API failures (evaluate() raising) and a malformed/incomplete
            # result shape (KeyError, or ScoredLead's own validation) — either way, one
            # bad lead is logged and skipped rather than crashing the whole batch.
            logger.error(f"Scoring failed for '{lead.name}': {exc}")
            continue

        if lead_result is not None:
            scored.append(lead_result)
        else:
            logger.debug(f"'{lead.name}' scored {weighted_score} < {min_score}, dropping")

    logger.info(f"Scored {len(leads)} leads, {len(scored)} qualified at >= {min_score}")
    return scored
