from __future__ import annotations

from datetime import date

import pytest

from occasio.core.checklist import build_checklist
from occasio.core.models import Scale, scale_for
from occasio.core.timeline import build_timeline


def checklist_for(profile, knowledge, today):
    return build_checklist(profile, knowledge, build_timeline(profile, knowledge, today))


def ids(checklist) -> set[str]:
    return {t.id for t in checklist.items}


@pytest.mark.parametrize(
    ("guests", "scale"),
    [
        (1, Scale.SMALL),
        (49, Scale.SMALL),
        (50, Scale.MEDIUM),
        (150, Scale.MEDIUM),
        (151, Scale.LARGE),
    ],
)
def test_scale_boundaries(guests, scale):
    assert scale_for(guests) is scale


def test_scale_specific_tasks(make_profile, knowledge, today):
    small = checklist_for(make_profile(event_type="wedding", guest_count=30), knowledge, today)
    large = checklist_for(make_profile(event_type="wedding", guest_count=300), knowledge, today)
    assert "host_helpers" in ids(small) and "accommodation" not in ids(small)
    assert "accommodation" in ids(large) and "host_helpers" not in ids(large)


def test_av_task_only_above_150(make_profile, knowledge, today):
    assert "sound_av" not in ids(checklist_for(make_profile(guest_count=150), knowledge, today))
    cl = checklist_for(make_profile(guest_count=151), knowledge, today)
    task = next(t for t in cl.items if t.id == "sound_av")
    assert task.is_critical and "151 guests" in task.reason


def test_sponsorship_task_for_community_without_tickets(make_profile, knowledge, today):
    free = checklist_for(make_profile(event_type="community_event"), knowledge, today)
    paid = checklist_for(
        make_profile(event_type="community_event", has_ticket_revenue=True), knowledge, today
    )
    wedding = checklist_for(make_profile(event_type="wedding"), knowledge, today)
    assert "sponsorship" in ids(free)
    assert "sponsorship" not in ids(paid)
    assert "sponsorship" not in ids(wedding)


def test_dietary_task(make_profile, knowledge, today):
    cl = checklist_for(make_profile(dietary=["halal", "gluten_free"]), knowledge, today)
    task = next(t for t in cl.items if t.id == "dietary_brief")
    assert "halal" in task.title and "gluten free" in task.title
    assert "dietary_brief" not in ids(checklist_for(make_profile(), knowledge, today))


def test_weather_backup_critical_only_in_monsoon(make_profile, knowledge, today):
    monsoon = checklist_for(
        make_profile(setting="outdoor", event_date=date(2026, 7, 18)), knowledge, today
    )
    dry = checklist_for(
        make_profile(setting="outdoor", event_date=date(2026, 2, 14)), knowledge, today
    )
    indoor = checklist_for(make_profile(event_date=date(2026, 7, 18)), knowledge, today)
    assert next(t for t in monsoon.items if t.id == "weather_backup").is_critical
    assert not next(t for t in dry.items if t.id == "weather_backup").is_critical
    assert "weather_backup" not in ids(indoor)


def test_must_haves_become_critical_tasks(make_profile, knowledge, today):
    cl = checklist_for(
        make_profile(must_haves=["Live violinist", "Sunset photos"]), knowledge, today
    )
    titles = [t.title for t in cl.items if t.id.startswith("must_have_")]
    assert titles == ["Secure must-have: Live violinist", "Secure must-have: Sunset photos"]


def test_late_categories_become_critical(make_profile, knowledge, today):
    cl = checklist_for(make_profile(event_type="wedding", weeks_out=10), knowledge, today)
    photographer = next(t for t in cl.items if t.id == "photographer")
    decorator = next(t for t in cl.items if t.id == "decorator")
    assert photographer.is_critical and "earlier than the time you have left" in photographer.reason
    assert decorator.is_critical  # decor plan is usually 16 weeks out


def test_ids_unique_reasons_present_and_critical_first(make_profile, knowledge, today):
    profile = make_profile(
        event_type="community_event", guest_count=400, setting="mixed", dietary=["vegan"]
    )
    cl = checklist_for(profile, knowledge, today)
    assert len(ids(cl)) == len(cl.items)
    assert all(t.reason for t in cl.items)
    flags = [t.is_critical for t in cl.items]
    assert flags == sorted(flags, reverse=True)
