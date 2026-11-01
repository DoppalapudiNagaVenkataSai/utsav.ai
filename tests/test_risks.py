from __future__ import annotations

from datetime import date

from occasio.core.models import Severity
from occasio.core.planner import build_plan


def codes(plan) -> list[str]:
    return [r.code for r in plan.risks]


def test_lead_time_risks(make_profile, today):
    assert "lead_time_crisis" in codes(build_plan(make_profile(weeks_out=3), today=today))
    assert "lead_time_tight" in codes(build_plan(make_profile(weeks_out=8), today=today))
    relaxed = build_plan(make_profile(weeks_out=30), today=today)
    assert not {"lead_time_crisis", "lead_time_tight"} & set(codes(relaxed))


def test_late_critical_bookings_listed(make_profile, today):
    plan = build_plan(make_profile(event_type="wedding", weeks_out=12), today=today)
    late = next(r for r in plan.risks if r.code == "late_bookings")
    assert "book the venue" in late.message


def test_low_per_head_severity_depends_on_event_type(make_profile, today):
    lean = {"guest_count": 200, "budget_minor": 20_000_00}
    birthday = build_plan(make_profile(**lean), today=today)
    community = build_plan(make_profile(event_type="community_event", **lean), today=today)
    assert (
        next(r for r in birthday.risks if r.code == "low_per_head_budget").severity
        is Severity.WARNING
    )
    assert (
        next(r for r in community.risks if r.code == "low_per_head_budget").severity
        is Severity.INFO
    )


def test_weather_risks(make_profile, today):
    monsoon = build_plan(make_profile(setting="outdoor", event_date=date(2026, 8, 1)), today=today)
    unknown = build_plan(make_profile(setting="outdoor", location="Oslo"), today=today)
    assert "monsoon_outdoor" in codes(monsoon)
    assert "weather_unknown" in codes(unknown)


def test_revenue_and_large_birthday_risks(make_profile, today):
    assert "no_revenue" in codes(
        build_plan(make_profile(event_type="community_event"), today=today)
    )
    assert "large_birthday" in codes(build_plan(make_profile(guest_count=300), today=today))


def test_risks_sorted_by_severity_and_explained(make_profile, today):
    plan = build_plan(
        make_profile(
            event_type="community_event",
            guest_count=300,
            budget_minor=10_000_00,
            setting="outdoor",
            event_date=date(2026, 1, 26),
        ),
        today=today,
    )
    order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    ranks = [order[r.severity] for r in plan.risks]
    assert ranks == sorted(ranks)
    assert all(r.reason for r in plan.risks)
