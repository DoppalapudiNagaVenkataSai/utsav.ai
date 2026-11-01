"""Personalised theme / activity / menu / decor ideas for a plan."""

from __future__ import annotations

import logging

from pydantic import ValidationError

from occasio.ai import fallback, prompts
from occasio.ai.client import AIClient
from occasio.ai.schemas import IDEAS_SCHEMA, IdeasPayload, IdeasResult
from occasio.core.models import Plan

log = logging.getLogger("occasio.ai")


def _facts(plan: Plan) -> dict[str, object]:
    p = plan.profile
    return {
        "event_type": p.event_type.value,
        "month": f"{p.event_date:%B}",
        "guest_count": p.guest_count,
        "scale": plan.scale.value,
        "setting": p.setting.value,
        "catering_style": plan.budget.catering_style.value,
        "dietary": [d.value for d in p.dietary],
        "lead_time": plan.timeline.lead_time_class.value,
        "budget_categories": [line.category for line in plan.budget.lines],
    }


def _user_text(plan: Plan) -> str:
    p = plan.profile
    parts = [f"Location: {p.location}"]
    if p.vibe:
        parts.append(f"Vibe: {p.vibe}")
    if p.preferences:
        parts.append("Preferences: " + "; ".join(p.preferences))
    if p.must_haves:
        parts.append("Must-haves: " + "; ".join(p.must_haves))
    return "\n".join(parts)


def generate(plan: Plan, client: AIClient) -> IdeasResult:
    raw = client.complete_json(
        "ideas",
        system=prompts.IDEAS_SYSTEM,
        user=prompts.plan_facts(_facts(plan)) + "\n" + prompts.user_data(_user_text(plan)),
        schema=IDEAS_SCHEMA,
    )
    if raw is not None:
        try:
            return IdeasResult(**IdeasPayload.model_validate(raw).model_dump(), source="ai")
        except ValidationError:
            log.warning("ai.ideas response failed validation; using fallback")
    return fallback.ideas(plan)
