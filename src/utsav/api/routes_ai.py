"""AI-assisted endpoints. All are rate limited per IP and degrade to template output."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from utsav.ai import explain, ideas, intake
from utsav.ai.intake import IntakeSuggestion
from utsav.ai.schemas import ExplanationResult, IdeasResult
from utsav.api.deps import AI, ExistingPlan, ai_rate_limit
from utsav.api.schemas import IntakeRequest

router = APIRouter(tags=["ai"], dependencies=[Depends(ai_rate_limit)])


@router.post("/api/ai/intake")
def ai_intake(body: IntakeRequest, ai: AI) -> IntakeSuggestion:
    return intake.parse(body.text, ai)


@router.post("/api/plans/{plan_id}/ideas")
def plan_ideas(stored: ExistingPlan, ai: AI) -> IdeasResult:
    return ideas.generate(stored.plan, ai)


@router.post("/api/plans/{plan_id}/explain")
def plan_explain(stored: ExistingPlan, ai: AI) -> ExplanationResult:
    return explain.explain(stored.plan, ai)
