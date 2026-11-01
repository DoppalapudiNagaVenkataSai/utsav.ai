"""Plan CRUD, re-planning, checklist progress and export."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Body, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import ValidationError

from utsav.api.deps import ExistingPlan, Repo, SettingsDep
from utsav.api.schemas import PlanResponse, ProfileUpdate, ReplanResponse, TaskUpdate
from utsav.core.export import to_markdown
from utsav.core.models import EventProfile
from utsav.core.planner import build_plan
from utsav.core.replan import replan

router = APIRouter(prefix="/api/plans", tags=["plans"])


def _unprocessable(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=message)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_plan(profile: EventProfile, repo: Repo, settings: SettingsDep) -> PlanResponse:
    try:
        plan = build_plan(profile, data_dir=settings.data_dir)
    except ValueError as exc:  # e.g. event date not in the future
        raise _unprocessable(str(exc)) from None
    return PlanResponse.of(repo.create(plan))


@router.get("/{plan_id}")
def get_plan(stored: ExistingPlan) -> PlanResponse:
    return PlanResponse.of(stored)


@router.post("/{plan_id}/replan")
def replan_plan(
    stored: ExistingPlan,
    repo: Repo,
    settings: SettingsDep,
    changes: Annotated[ProfileUpdate, Body()],
) -> ReplanResponse:
    updates = changes.model_dump(exclude_unset=True)
    try:
        new_plan, diff = replan(stored.plan, updates, data_dir=settings.data_dir)
    except ValidationError as exc:
        raise _unprocessable(
            "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        ) from None
    except ValueError as exc:
        raise _unprocessable(str(exc)) from None
    updated = repo.update(stored.id, new_plan)
    assert updated is not None
    return ReplanResponse(**PlanResponse.of(updated).model_dump(), diff=diff)


@router.patch("/{plan_id}/tasks/{task_id}")
def update_task(
    stored: ExistingPlan,
    repo: Repo,
    body: TaskUpdate,
    task_id: Annotated[str, Path(pattern=r"^[a-z0-9_]{1,40}$")],
) -> PlanResponse:
    plan = stored.plan
    task = next((t for t in plan.checklist.items if t.id == task_id), None)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    task.status = body.status
    updated = repo.update(stored.id, plan)
    assert updated is not None
    return PlanResponse.of(updated)


@router.get("/{plan_id}/export", response_model=None)
def export_plan(
    stored: ExistingPlan, format: Annotated[Literal["md", "json"], Query()] = "md"
) -> Response:
    filename = f"utsav.ai-{stored.plan.profile.event_type.value}-{stored.id[:8]}"
    if format == "json":
        return JSONResponse(
            PlanResponse.of(stored).model_dump(mode="json"),
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )
    return PlainTextResponse(
        to_markdown(stored.plan),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.md"'},
    )
