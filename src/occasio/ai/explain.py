"""Plain-language explanation of the engine's decisions.

The model only rephrases the engine's ``reason`` fields. As a guard against it
altering numbers, every number in the response must already appear in the facts;
otherwise the response is discarded and the template explanation is used.
"""

from __future__ import annotations

import logging
import re

from pydantic import ValidationError

from occasio.ai import fallback, prompts
from occasio.ai.client import AIClient
from occasio.ai.schemas import EXPLANATION_SCHEMA, ExplanationPayload, ExplanationResult
from occasio.core.budget import label
from occasio.core.models import Plan, format_money

log = logging.getLogger("occasio.ai")

_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _facts(plan: Plan) -> dict[str, object]:
    cur = plan.budget.currency
    return {
        "event": plan.profile.event_type.value,
        "guests": plan.profile.guest_count,
        "scale": plan.scale.value,
        "total_budget": format_money(plan.budget.total_minor, cur),
        "per_guest": format_money(plan.budget.per_head_minor, cur),
        "catering": {"style": plan.budget.catering_style.value, "why": plan.budget.catering_reason},
        "budget_lines": [
            {
                "category": label(line.category),
                "amount": format_money(line.amount_minor, cur),
                "percent": line.percent,
                "why": line.reason,
            }
            for line in plan.budget.lines
        ],
        "timeline": {
            "lead_time": plan.timeline.lead_time_class.value,
            "why": plan.timeline.reason,
            "late_or_critical": [
                {"title": m.title, "due": m.due_date.isoformat(), "why": m.reason}
                for m in plan.timeline.milestones
                if m.late_booking or m.is_critical
            ][:8],
        },
        "rule_tasks": [
            {"title": t.title, "why": t.reason}
            for t in plan.checklist.items
            # Must-have titles are user text; keep them out of the trusted facts block.
            if not t.reason.startswith("Standard for") and not t.id.startswith("must_have_")
        ],
        "risks": [{"message": r.message, "why": r.reason} for r in plan.risks],
    }


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".").removesuffix(".0") for n in _NUMBER_RE.findall(text)}


def numbers_grounded(payload: ExplanationPayload, facts_text: str) -> bool:
    known = _numbers(facts_text)
    said = _numbers(
        payload.summary + " " + " ".join(p.explanation + p.topic for p in payload.points)
    )
    return said <= known


def explain(plan: Plan, client: AIClient) -> ExplanationResult:
    facts = prompts.plan_facts(_facts(plan))
    raw = client.complete_json(
        "explain", system=prompts.EXPLAIN_SYSTEM, user=facts, schema=EXPLANATION_SCHEMA
    )
    if raw is not None:
        try:
            payload = ExplanationPayload.model_validate(raw)
        except ValidationError:
            log.warning("ai.explain response failed validation; using fallback")
        else:
            if numbers_grounded(payload, facts):
                return ExplanationResult(**payload.model_dump(), source="ai")
            log.warning("ai.explain response contained numbers not in the plan; using fallback")
    return fallback.explanation(plan)
