from prospecting_agent.ai.openai_qualifier import score_leads


class _FakeQualifier:
    """Stands in for OpenAIQualifier so tests don't hit the real OpenAI API."""

    def __init__(self, results: dict[str, dict]):
        self._results = results

    def evaluate(self, lead):
        if lead.name not in self._results:
            raise RuntimeError(f"no fake result configured for {lead.name}")
        return self._results[lead.name]


def _fake_result(score: int) -> dict:
    return {
        "score": score,
        "reason": "test reason",
        "pain_points": ["no website listed", "low review count"],
        "recommended_offer": "a free Missed Call Revenue Audit",
        "personalized_first_line": "Noticed you don't have a website listed on Google.",
        "full_outreach_message": "Hi there — noticed a couple of things about your listing...",
    }


def test_score_leads_keeps_only_leads_at_or_above_threshold(make_cleaned_lead):
    leads = [make_cleaned_lead(name="High Scorer"), make_cleaned_lead(name="Low Scorer", place_id="p2")]
    qualifier = _FakeQualifier(
        {
            "High Scorer": _fake_result(9),
            "Low Scorer": _fake_result(3),
        }
    )

    scored = score_leads(leads, qualifier, min_score=7)

    assert [lead.name for lead in scored] == ["High Scorer"]
    assert scored[0].score == 9
    assert scored[0].pain_points == ["no website listed", "low review count"]
    assert scored[0].full_outreach_message.startswith("Hi there")


def test_score_leads_skips_lead_on_qualifier_error(make_cleaned_lead):
    leads = [make_cleaned_lead(name="Will Fail")]
    qualifier = _FakeQualifier({})  # no configured result -> evaluate() raises

    scored = score_leads(leads, qualifier, min_score=7)

    assert scored == []


def test_score_leads_skips_malformed_result_without_crashing_the_batch(make_cleaned_lead):
    """A response missing required fields (bad structured-output payload) must be logged
    and skipped like any other per-lead failure — not crash the whole batch (regression
    test: this used to raise KeyError/ValidationError outside the try/except)."""
    leads = [
        make_cleaned_lead(name="Malformed Result", place_id="p1"),
        make_cleaned_lead(name="Good Result", place_id="p2"),
    ]
    qualifier = _FakeQualifier(
        {
            "Malformed Result": {"score": 9},  # missing reason/pain_points/etc.
            "Good Result": _fake_result(9),
        }
    )

    scored = score_leads(leads, qualifier, min_score=7)

    assert [lead.name for lead in scored] == ["Good Result"]
