"""Free text -> partial EventProfile.

The model (or the regex fallback) only *suggests* values. Fields are validated one
by one against the same limits as ``EventProfile``; anything invalid is dropped.
Budget and date are never applied directly: they come back as ``suggested_*``
fields and are listed in ``needs_confirmation`` so the UI echoes them to the user.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from utsav.ai import fallback, prompts
from utsav.ai.client import AIClient
from utsav.ai.schemas import INTAKE_SCHEMA, IntakePayload, Source
from utsav.core.models import MAX_BUDGET_MINOR, MAX_GUESTS, Currency

log = logging.getLogger("utsav.ai")

MAX_INTAKE_CHARS = 2000
MAX_YEARS_AHEAD = 5


class IntakeSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, Any]
    suggested_budget_minor: int | None = None
    suggested_currency: Currency | None = None
    suggested_event_date: date | None = None
    needs_confirmation: list[str]
    source: Source


def _safe_fields(payload: IntakePayload) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if payload.event_type is not None:
        out["event_type"] = payload.event_type.value
    if payload.guest_count is not None and 1 <= payload.guest_count <= MAX_GUESTS:
        out["guest_count"] = payload.guest_count
    if payload.location and payload.location.strip():
        out["location"] = payload.location.strip()
    if payload.setting is not None:
        out["setting"] = payload.setting.value
    if payload.vibe and payload.vibe.strip():
        out["vibe"] = payload.vibe.strip()
    if payload.preferences:
        out["preferences"] = payload.preferences[:10]
    if payload.dietary:
        out["dietary"] = sorted({d.value for d in payload.dietary})
    if payload.has_ticket_revenue is not None:
        out["has_ticket_revenue"] = payload.has_ticket_revenue
    return out


def _budget(payload: IntakePayload) -> int | None:
    if payload.budget_amount is None:
        return None
    minor = round(payload.budget_amount * 100)
    return minor if 0 < minor <= MAX_BUDGET_MINOR else None


def _date(payload: IntakePayload, today: date) -> date | None:
    if not payload.event_date:
        return None
    try:
        parsed = date.fromisoformat(payload.event_date)
    except ValueError:
        return None
    latest = today + timedelta(days=365 * MAX_YEARS_AHEAD)
    return parsed if today < parsed <= latest else None


def parse(text: str, client: AIClient, today: date | None = None) -> IntakeSuggestion:
    today = today or date.today()
    text = prompts.sanitize(text, MAX_INTAKE_CHARS)
    source: Source = "fallback"
    payload: IntakePayload | None = None

    raw = client.complete_json(
        "intake", system=prompts.intake_system(today), user=prompts.user_data(text),
        schema=INTAKE_SCHEMA,
    )  # fmt: skip
    if raw is not None:
        try:
            payload = IntakePayload.model_validate(raw)
            source = "ai"
        except ValidationError:
            log.warning("ai.intake response failed validation; using fallback")
    if payload is None:
        payload = fallback.intake(text, today)

    budget = _budget(payload)
    when = _date(payload, today)
    currency = Currency(payload.currency) if payload.currency else None
    confirm = [name for name, value in (("budget", budget), ("event_date", when)) if value]
    return IntakeSuggestion(
        fields=_safe_fields(payload),
        suggested_budget_minor=budget,
        suggested_currency=currency,
        suggested_event_date=when,
        needs_confirmation=confirm,
        source=source,
    )
