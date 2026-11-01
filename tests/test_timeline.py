from __future__ import annotations

from datetime import timedelta

import pytest

from occasio.core.models import LeadTimeClass
from occasio.core.timeline import build_timeline, lead_time_class


@pytest.mark.parametrize(
    ("weeks", "expected"),
    [
        (40, LeadTimeClass.COMFORTABLE),
        (16, LeadTimeClass.COMFORTABLE),
        (16 - 1 / 7, LeadTimeClass.TIGHT),
        (6, LeadTimeClass.TIGHT),
        (6 - 1 / 7, LeadTimeClass.CRISIS),
        (1 / 7, LeadTimeClass.CRISIS),
    ],
)
def test_lead_time_class_boundaries(weeks, expected):
    assert lead_time_class(weeks) is expected


def test_exactly_six_weeks_is_tight(make_profile, knowledge, today):
    tl = build_timeline(make_profile(weeks_out=6), knowledge, today)
    assert tl.lead_time_class is LeadTimeClass.TIGHT
    assert tl.weeks_available == 6


def test_plenty_of_time_keeps_template_dates(make_profile, knowledge, today):
    profile = make_profile(weeks_out=30)
    tl = build_timeline(profile, knowledge, today)
    templates = {t.key: t for t in knowledge.timelines["birthday"]}
    for m in tl.milestones:
        expected = profile.event_date - timedelta(weeks=templates[m.key].weeks_before_event)
        assert m.due_date == expected
        assert not m.compressed and not m.late_booking


def test_short_window_compresses_and_flags_late_bookings(make_profile, knowledge, today):
    profile = make_profile(event_type="wedding", weeks_out=10)
    tl = build_timeline(profile, knowledge, today)
    templates = {t.key: t for t in knowledge.timelines["wedding"]}
    assert tl.lead_time_class is LeadTimeClass.TIGHT
    for m in tl.milestones:
        assert today <= m.due_date <= profile.event_date
        assert m.late_booking == (templates[m.key].weeks_before_event > 10)
        if m.late_booking:
            assert "book this immediately" in m.reason
    # Compression keeps the original order of milestones.
    order = [templates[m.key].weeks_before_event for m in tl.milestones]
    assert order == sorted(order, reverse=True)


def test_crisis_marks_non_critical_optional(make_profile, knowledge, today):
    tl = build_timeline(make_profile(event_type="wedding", weeks_out=4), knowledge, today)
    assert tl.lead_time_class is LeadTimeClass.CRISIS
    for m in tl.milestones:
        assert m.optional == (not m.is_critical)
    assert any(m.optional for m in tl.milestones)


def test_tight_does_not_mark_optional(make_profile, knowledge, today):
    tl = build_timeline(make_profile(event_type="wedding", weeks_out=10), knowledge, today)
    assert not any(m.optional for m in tl.milestones)


def test_event_day_milestone_is_on_event_date(make_profile, knowledge, today):
    profile = make_profile(weeks_out=3)
    tl = build_timeline(profile, knowledge, today)
    assert tl.milestones[-1].key == "event_day"
    assert tl.milestones[-1].due_date == profile.event_date


@pytest.mark.parametrize("days", [0, -1, -30])
def test_past_or_same_day_rejected(make_profile, knowledge, today, days):
    with pytest.raises(ValueError, match="after today"):
        build_timeline(make_profile(event_date=today + timedelta(days=days)), knowledge, today)


def test_every_milestone_has_reason(make_profile, knowledge, today):
    for event_type in ("wedding", "birthday", "community_event"):
        tl = build_timeline(make_profile(event_type=event_type, weeks_out=8), knowledge, today)
        assert tl.reason
        assert all(m.reason for m in tl.milestones)
