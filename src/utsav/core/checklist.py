"""Vendor and task checklist by event type and scale, plus rule-driven tasks."""

from __future__ import annotations

from utsav.core.knowledge import Knowledge, monsoon_exposure
from utsav.core.models import (
    MEDIUM_MAX_GUESTS,
    Checklist,
    EventProfile,
    EventType,
    Scale,
    Setting,
    Task,
    Timeline,
    scale_for,
)

_SCALE_TEXT = {
    Scale.SMALL: "small (< 50 guests)",
    Scale.MEDIUM: "medium (50-150 guests)",
    Scale.LARGE: "large (> 150 guests)",
}


def build_checklist(profile: EventProfile, knowledge: Knowledge, timeline: Timeline) -> Checklist:
    scale = scale_for(profile.guest_count)
    event = profile.event_type.value.replace("_", " ")
    late_categories = {m.category for m in timeline.milestones if m.late_booking}

    items: list[Task] = []
    for t in knowledge.checklists[profile.event_type].for_scale(scale):
        reason = f"Standard for a {_SCALE_TEXT[scale]} {event}"
        critical = t.is_critical
        if t.category in late_categories:
            reason += "; usually booked earlier than the time you have left, so do it first"
            critical = True
        items.append(
            Task(id=t.key, title=t.title, category=t.category, is_critical=critical, reason=reason)
        )

    def add(task: Task) -> None:
        if all(i.id != task.id for i in items):
            items.append(task)

    if profile.guest_count > MEDIUM_MAX_GUESTS:
        add(
            Task(
                id="sound_av",
                title="Book sound system, mics and AV technician",
                category="sound_av",
                is_critical=True,
                reason=f"{profile.guest_count} guests (> {MEDIUM_MAX_GUESTS}): "
                "people at the back must be able to hear speeches and announcements",
            )
        )
    if profile.event_type is EventType.COMMUNITY_EVENT and not profile.has_ticket_revenue:
        add(
            Task(
                id="sponsorship",
                title="Approach local sponsors and apply for community grants",
                category="marketing_and_outreach",
                is_critical=True,
                reason="No ticket revenue: the budget must be covered by sponsors or grants",
            )
        )
    if profile.dietary:
        flags = ", ".join(d.value.replace("_", " ") for d in profile.dietary)
        add(
            Task(
                id="dietary_brief",
                title=f"Confirm dietary options with the caterer ({flags})",
                category="catering",
                is_critical=True,
                reason=f"Guests need {flags} options; caterers need this before quoting",
            )
        )
    if profile.setting is not Setting.INDOOR:
        region = monsoon_exposure(profile.location, profile.setting, profile.event_date, knowledge)
        add(
            Task(
                id="weather_backup",
                title="Arrange weather backup (tent, covered area or indoor fallback)",
                category="venue",
                is_critical=region is not None,
                reason=(
                    f"{profile.setting.value} event during monsoon season for {region.name}"
                    if region
                    else f"{profile.setting.value} events need a plan for bad weather"
                ),
            )
        )
    for i, must in enumerate(profile.must_haves):
        add(
            Task(
                id=f"must_have_{i + 1}",
                title=f"Secure must-have: {must}",
                category="planning",
                is_critical=True,
                reason="You marked this as a must-have",
            )
        )
    items.sort(key=lambda t: not t.is_critical)
    return Checklist(items=items)
