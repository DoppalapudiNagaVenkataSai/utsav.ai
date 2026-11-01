"""Re-planning: apply constraint changes, rebuild, carry progress over, and diff."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from utsav.core.budget import label
from utsav.core.knowledge import DEFAULT_DATA_DIR
from utsav.core.models import (
    Change,
    ChangeKind,
    EventProfile,
    Plan,
    PlanDiff,
    Task,
    TaskStatus,
    format_money,
)
from utsav.core.planner import build_plan

BUDGET_CUT_RENEGOTIATE = 0.10  # a cut of 10% or more triggers a renegotiation task


def apply_changes(profile: EventProfile, updates: dict[str, Any]) -> EventProfile:
    """Merge partial updates into a profile and re-validate the result."""
    merged = profile.model_dump()
    merged.update(updates)
    return EventProfile.model_validate(merged)


def replan(
    old: Plan,
    updates: dict[str, Any],
    today: date | None = None,
    data_dir: Path = DEFAULT_DATA_DIR,
) -> tuple[Plan, PlanDiff]:
    profile = apply_changes(old.profile, updates)
    new = build_plan(profile, today=today, data_dir=data_dir)

    done = {t.id for t in old.checklist.items if t.status is TaskStatus.DONE}
    for task in new.checklist.items:
        if task.id in done:
            task.status = TaskStatus.DONE
    new.checklist.items.extend(_replan_tasks(old, new, done))
    return new, diff(old, new)


def _replan_tasks(old: Plan, new: Plan, done: set[str]) -> list[Task]:
    """Follow-up tasks that only make sense when something already booked is affected."""
    tasks: list[Task] = []
    before, after = old.profile, new.profile
    cut = (before.budget_minor - after.budget_minor) / before.budget_minor
    if cut >= BUDGET_CUT_RENEGOTIATE and done:
        tasks.append(
            Task(
                id="renegotiate_vendors",
                title="Renegotiate or re-quote already-booked vendors",
                category="planning",
                is_critical=True,
                reason=f"Budget dropped {cut:.0%} after some vendors were booked",
            )
        )
    if after.guest_count > before.guest_count and "venue" in done:
        tasks.append(
            Task(
                id="confirm_venue_capacity",
                title=f"Confirm the venue can hold {after.guest_count} guests",
                category="venue",
                is_critical=True,
                reason=f"Guest list grew from {before.guest_count} to {after.guest_count} "
                "after the venue was booked",
            )
        )
    if after.event_date != before.event_date and done:
        tasks.append(
            Task(
                id="notify_date_change",
                title=f"Tell booked vendors about the new date ({after.event_date:%d %b %Y})",
                category="planning",
                is_critical=True,
                reason="The event date changed after some vendors were booked",
            )
        )
    existing = {t.id for t in new.checklist.items}
    return [t for t in tasks if t.id not in existing]


def diff(old: Plan, new: Plan) -> PlanDiff:
    changes: list[Change] = []
    cur_old, cur_new = old.budget.currency, new.budget.currency

    for field in EventProfile.model_fields:
        a, b = getattr(old.profile, field), getattr(new.profile, field)
        if a != b:
            changes.append(
                Change(
                    section="profile",
                    key=field,
                    kind=ChangeKind.CHANGED,
                    before=_jsonable(a),
                    after=_jsonable(b),
                    message=f"{label(field)}: {_show(a, field, cur_old)} → "
                    f"{_show(b, field, cur_new)}",
                )
            )

    old_lines = {line.category: line for line in old.budget.lines}
    new_lines = {line.category: line for line in new.budget.lines}
    for cat in [*old_lines, *(c for c in new_lines if c not in old_lines)]:
        o, n = old_lines.get(cat), new_lines.get(cat)
        if o and not n:
            changes.append(
                Change(
                    section="budget",
                    key=cat,
                    kind=ChangeKind.REMOVED,
                    before=o.amount_minor,
                    message=f"{label(cat)} removed (was {format_money(o.amount_minor, cur_old)})",
                )
            )
        elif n and not o:
            changes.append(
                Change(
                    section="budget",
                    key=cat,
                    kind=ChangeKind.ADDED,
                    after=n.amount_minor,
                    message=f"{label(cat)} added: {format_money(n.amount_minor, cur_new)}",
                )
            )
        elif o and n and o.amount_minor != n.amount_minor:
            verb = "increased" if n.amount_minor > o.amount_minor else "reduced"
            changes.append(
                Change(
                    section="budget",
                    key=cat,
                    kind=ChangeKind.CHANGED,
                    before=o.amount_minor,
                    after=n.amount_minor,
                    message=f"{label(cat)} {verb} {format_money(o.amount_minor, cur_old)} → "
                    f"{format_money(n.amount_minor, cur_new)}",
                )
            )

    if old.budget.catering_style != new.budget.catering_style:
        changes.append(
            Change(
                section="budget",
                key="catering_style",
                kind=ChangeKind.CHANGED,
                before=old.budget.catering_style.value,
                after=new.budget.catering_style.value,
                message=f"Catering style: {old.budget.catering_style.value} → "
                f"{new.budget.catering_style.value} ({new.budget.catering_reason})",
            )
        )

    if old.timeline.lead_time_class != new.timeline.lead_time_class:
        changes.append(
            Change(
                section="timeline",
                key="lead_time_class",
                kind=ChangeKind.CHANGED,
                before=old.timeline.lead_time_class.value,
                after=new.timeline.lead_time_class.value,
                message=f"Lead time: {old.timeline.lead_time_class.value} → "
                f"{new.timeline.lead_time_class.value}",
            )
        )
    old_ms = {m.key: m for m in old.timeline.milestones}
    for m in new.timeline.milestones:
        prev = old_ms.get(m.key)
        if prev and prev.due_date != m.due_date:
            changes.append(
                Change(
                    section="timeline",
                    key=m.key,
                    kind=ChangeKind.CHANGED,
                    before=prev.due_date.isoformat(),
                    after=m.due_date.isoformat(),
                    message=f"{m.title}: due {prev.due_date:%d %b} → {m.due_date:%d %b %Y}",
                )
            )

    changes += _set_diff(
        "checklist",
        {t.id: t.title for t in old.checklist.items},
        {t.id: t.title for t in new.checklist.items},
        "New task",
        "Task no longer needed",
    )
    changes += _set_diff(
        "risks",
        {r.code: r.message for r in old.risks},
        {r.code: r.message for r in new.risks},
        "New risk",
        "Risk cleared",
    )
    return PlanDiff(changes=changes)


def _set_diff(
    section: str, old: dict[str, str], new: dict[str, str], added: str, removed: str
) -> list[Change]:
    out = [
        Change(section=section, key=k, kind=ChangeKind.ADDED, after=v, message=f"{added}: {v}")
        for k, v in new.items()
        if k not in old
    ]
    out += [
        Change(section=section, key=k, kind=ChangeKind.REMOVED, before=v, message=f"{removed}: {v}")
        for k, v in old.items()
        if k not in new
    ]
    return out


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return getattr(value, "value", value)


def _show(value: Any, field: str, currency: Any) -> str:
    if field == "budget_minor":
        return format_money(int(value), currency)
    if isinstance(value, list):
        return ", ".join(str(_jsonable(v)) for v in value) or "none"
    return str(_jsonable(value)) or "—"
