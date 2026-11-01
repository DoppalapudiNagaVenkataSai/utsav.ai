"""Structured-output contracts for every AI task.

Each task has a JSON schema (sent to the API to constrain generation) and a
Pydantic model (used to validate what actually came back). The Pydantic model is
the source of truth: it forbids extra keys and bounds every string, so an
unexpected or oversized response is rejected and the caller falls back.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from occasio.core.models import DietaryFlag, EventType, Setting

Text80 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Text400 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=400)]

Source = Literal["ai", "fallback"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- ideas ---------------------------------------------------------------


class IdeaKind(StrEnum):
    THEME = "theme"
    ACTIVITY = "activity"
    MENU = "menu"
    DECOR = "decor"


class Idea(_Strict):
    title: Text80
    kind: IdeaKind
    description: Text400
    why_it_fits: Text400


class IdeasPayload(_Strict):
    ideas: list[Idea] = Field(min_length=3, max_length=5)


class IdeasResult(IdeasPayload):
    source: Source


# ---- intake --------------------------------------------------------------


class IntakePayload(_Strict):
    event_type: EventType | None
    guest_count: int | None
    budget_amount: float | None  # major units, e.g. 800000 for "8 lakh"
    currency: Literal["INR", "USD", "EUR", "GBP"] | None
    event_date: str | None  # YYYY-MM-DD
    location: Annotated[str, StringConstraints(max_length=120)] | None
    setting: Setting | None
    vibe: Annotated[str, StringConstraints(max_length=200)] | None
    preferences: list[Text80] = Field(max_length=10)
    dietary: list[DietaryFlag] = Field(max_length=len(DietaryFlag))
    has_ticket_revenue: bool | None


# ---- explanation ---------------------------------------------------------


class ExplanationPoint(_Strict):
    topic: Text80
    explanation: Text400


class ExplanationPayload(_Strict):
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=700)]
    points: list[ExplanationPoint] = Field(min_length=1, max_length=8)


class ExplanationResult(ExplanationPayload):
    source: Source


# ---- JSON schemas sent to the API ----------------------------------------


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _obj(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_STR = {"type": "string"}

IDEAS_SCHEMA = _obj(
    {
        "ideas": {
            "type": "array",
            "items": _obj(
                {
                    "title": _STR,
                    "kind": {"type": "string", "enum": [k.value for k in IdeaKind]},
                    "description": _STR,
                    "why_it_fits": _STR,
                }
            ),
        }
    }
)

INTAKE_SCHEMA = _obj(
    {
        "event_type": _nullable({"type": "string", "enum": [e.value for e in EventType]}),
        "guest_count": _nullable({"type": "integer"}),
        "budget_amount": _nullable({"type": "number"}),
        "currency": _nullable({"type": "string", "enum": ["INR", "USD", "EUR", "GBP"]}),
        "event_date": _nullable({"type": "string", "format": "date"}),
        "location": _nullable(_STR),
        "setting": _nullable({"type": "string", "enum": [s.value for s in Setting]}),
        "vibe": _nullable(_STR),
        "preferences": {"type": "array", "items": _STR},
        "dietary": {
            "type": "array",
            "items": {"type": "string", "enum": [d.value for d in DietaryFlag]},
        },
        "has_ticket_revenue": _nullable({"type": "boolean"}),
    }
)

EXPLANATION_SCHEMA = _obj(
    {
        "summary": _STR,
        "points": {
            "type": "array",
            "items": _obj({"topic": _STR, "explanation": _STR}),
        },
    }
)
