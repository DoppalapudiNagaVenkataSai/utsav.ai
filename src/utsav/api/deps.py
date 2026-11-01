"""Dependency accessors for objects created once in the app factory."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Path, Request, status

from utsav.ai.client import AIClient
from utsav.config import Settings
from utsav.storage.repo import PlanRepository, StoredPlan


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_repo(request: Request) -> PlanRepository:
    repo: PlanRepository = request.app.state.repo
    return repo


def get_ai(request: Request) -> AIClient:
    ai: AIClient = request.app.state.ai
    return ai


def ai_rate_limit(request: Request) -> None:
    request.app.state.ai_limiter(request)


PlanId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$", description="Plan id")]
Repo = Annotated[PlanRepository, Depends(get_repo)]
AI = Annotated[AIClient, Depends(get_ai)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def load_plan(plan_id: PlanId, repo: Repo) -> StoredPlan:
    stored = repo.get(plan_id)
    if stored is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    return stored


ExistingPlan = Annotated[StoredPlan, Depends(load_plan)]
