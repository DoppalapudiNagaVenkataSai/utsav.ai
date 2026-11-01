from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from utsav.core.models import ChangeKind, TaskStatus
from utsav.core.planner import build_plan
from utsav.core.replan import apply_changes, diff, replan


@pytest.fixture
def plan(make_profile, today):
    return build_plan(
        make_profile(
            event_type="wedding", guest_count=120, budget_minor=10_00_000_00, weeks_out=40
        ),
        today=today,
    )


def mark_done(plan, *task_ids):
    for task in plan.checklist.items:
        if task.id in task_ids:
            task.status = TaskStatus.DONE


def keys(d, section, kind=None):
    return {c.key for c in d.changes if c.section == section and (kind is None or c.kind is kind)}


def test_identical_plans_have_empty_diff(plan):
    assert diff(plan, plan).is_empty


def test_no_op_replan_has_empty_diff(plan, today):
    _, d = replan(plan, {}, today=today)
    assert d.is_empty


def test_budget_cut_reduces_lines_with_readable_messages(plan, today):
    new, d = replan(plan, {"budget_minor": 8_00_000_00}, today=today)
    assert sum(line.amount_minor for line in new.budget.lines) == 8_00_000_00
    decor = next(c for c in d.changes if c.section == "budget" and c.key == "decor")
    assert decor.kind is ChangeKind.CHANGED
    assert decor.message == "Decor reduced ₹1,00,000 → ₹80,000"
    assert any(c.section == "profile" and c.key == "budget_minor" for c in d.changes)


def test_budget_cut_after_bookings_adds_renegotiate_task(plan, today):
    mark_done(plan, "venue")
    new, d = replan(plan, {"budget_minor": 8_00_000_00}, today=today)
    assert "renegotiate_vendors" in {t.id for t in new.checklist.items}
    assert "renegotiate_vendors" in keys(d, "checklist", ChangeKind.ADDED)


def test_small_cut_or_no_bookings_does_not_add_renegotiate(plan, today):
    new, _ = replan(plan, {"budget_minor": 8_00_000_00}, today=today)
    assert "renegotiate_vendors" not in {t.id for t in new.checklist.items}
    mark_done(plan, "venue")
    new, _ = replan(plan, {"budget_minor": 9_50_000_00}, today=today)
    assert "renegotiate_vendors" not in {t.id for t in new.checklist.items}


def test_task_status_carried_over(plan, today):
    mark_done(plan, "venue", "caterer")
    new, _ = replan(plan, {"guest_count": 130}, today=today)
    done = {t.id for t in new.checklist.items if t.status is TaskStatus.DONE}
    assert done == {"venue", "caterer"}


def test_guest_growth_after_venue_booked_adds_capacity_check(plan, today):
    mark_done(plan, "venue")
    new, _ = replan(plan, {"guest_count": 140}, today=today)
    task = next(t for t in new.checklist.items if t.id == "confirm_venue_capacity")
    assert "120 to 140" in task.reason


def test_crossing_150_guests_adds_av_everywhere(plan, today):
    _, d = replan(plan, {"guest_count": 180}, today=today)
    assert "sound_av" in keys(d, "budget", ChangeKind.ADDED)
    assert "sound_av" in keys(d, "checklist", ChangeKind.ADDED)
    assert "accommodation" in keys(d, "checklist", ChangeKind.ADDED)


def test_date_change_moves_milestones_and_notifies_vendors(plan, today):
    mark_done(plan, "photographer")
    new_date = plan.profile.event_date - timedelta(weeks=36)
    new, d = replan(plan, {"event_date": new_date}, today=today)
    assert "lead_time_class" in keys(d, "timeline")
    assert "book_venue" in keys(d, "timeline")
    assert "notify_date_change" in {t.id for t in new.checklist.items}
    assert "lead_time_crisis" in keys(d, "risks", ChangeKind.ADDED)


def test_catering_style_change_is_reported(plan, today):
    _, d = replan(plan, {"budget_minor": 1_00_000_00}, today=today)
    style = next(c for c in d.changes if c.key == "catering_style")
    assert (style.before, style.after) == ("plated", "buffet")


def test_removed_lines_and_cleared_risks_reported(make_profile, today):
    big = build_plan(
        make_profile(guest_count=200, setting="outdoor", location="Reykjavik"), today=today
    )
    _, d = replan(big, {"guest_count": 100, "setting": "indoor"}, today=today)
    assert "sound_av" in keys(d, "budget", ChangeKind.REMOVED)
    assert "weather_unknown" in keys(d, "risks", ChangeKind.REMOVED)


def test_invalid_update_rejected(plan):
    with pytest.raises(ValidationError):
        apply_changes(plan.profile, {"guest_count": -5})
    with pytest.raises(ValidationError):
        apply_changes(plan.profile, {"not_a_field": 1})
