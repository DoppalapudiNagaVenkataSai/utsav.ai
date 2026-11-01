"""Request/response bodies specific to the HTTP API."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model

from utsav.core.models import EventProfile, Plan, PlanDiff, TaskStatus
from utsav.storage.repo import StoredPlan


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _optional_fields() -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for name, info in EventProfile.model_fields.items():
        copy = deepcopy(info)
        copy.default = None
        copy.default_factory = None
        annotation: Any = info.annotation
        fields[name] = (annotation | None, copy)
    return fields


# Every EventProfile field, all optional, same constraints. Only fields sent are applied.
ProfileUpdate: type[BaseModel] = create_model(
    "ProfileUpdate", __config__=ConfigDict(extra="forbid", str_strip_whitespace=True),
    **_optional_fields(),
)  # fmt: skip


class PlanResponse(_Strict):
    id: str
    created_at: datetime
    updated_at: datetime
    plan: Plan

    @classmethod
    def of(cls, stored: StoredPlan) -> PlanResponse:
        return cls(
            id=stored.id, created_at=stored.created_at, updated_at=stored.updated_at,
            plan=stored.plan,
        )  # fmt: skip


class ReplanResponse(PlanResponse):
    diff: PlanDiff


class TaskUpdate(_Strict):
    status: TaskStatus


class IntakeRequest(_Strict):
    text: Annotated[str, StringConstraints(min_length=1, max_length=2000)]


class Health(_Strict):
    status: str = "ok"
    ai_enabled: bool
    model: str | None = Field(default=None, description="Model id when AI is enabled")
