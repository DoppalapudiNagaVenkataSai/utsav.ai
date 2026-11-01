"""Milestone timeline built backwards from the event date.

Lead-time classes: comfortable (>= 16 weeks), tight (6 to < 16), crisis (< 6).
When a milestone's usual lead time is longer than the time left, the whole
schedule is compressed proportionally into the available window and the
milestone is flagged as a late booking. In crisis mode non-critical milestones
are marked optional so effort goes to what matters.
"""

from __future__ import annotations

from datetime import date, timedelta

from occasio.core.knowledge import Knowledge
from occasio.core.models import EventProfile, LeadTimeClass, Milestone, Timeline

COMFORTABLE_WEEKS = 16
CRISIS_WEEKS = 6


def weeks_between(today: date, event_date: date) -> float:
    return (event_date - today).days / 7


def lead_time_class(weeks_available: float) -> LeadTimeClass:
    if weeks_available >= COMFORTABLE_WEEKS:
        return LeadTimeClass.COMFORTABLE
    if weeks_available >= CRISIS_WEEKS:
        return LeadTimeClass.TIGHT
    return LeadTimeClass.CRISIS


def build_timeline(profile: EventProfile, knowledge: Knowledge, today: date) -> Timeline:
    if profile.event_date <= today:
        raise ValueError("event_date must be after today")
    weeks = weeks_between(today, profile.event_date)
    klass = lead_time_class(weeks)
    templates = knowledge.timelines[profile.event_type]
    longest = max(t.weeks_before_event for t in templates)
    # Leave the first few days for decisions when compressing, so day 0 is not overloaded.
    usable_days = max((profile.event_date - today).days - 3, 0)
    factor = min(1.0, usable_days / (longest * 7)) if longest else 1.0
    compressed = factor < 1.0

    milestones: list[Milestone] = []
    for t in templates:
        usual_due = profile.event_date - timedelta(weeks=t.weeks_before_event)
        late = usual_due < today
        due = profile.event_date - timedelta(days=round(t.weeks_before_event * 7 * factor))
        due = max(due, today)
        optional = klass is LeadTimeClass.CRISIS and not t.is_critical
        parts = [f"Usually done {t.weeks_before_event} weeks before a {_event(profile)}"]
        if late:
            parts.append(f"that date has passed ({weeks:.1f} weeks left), so book this immediately")
        elif compressed and due != usual_due:
            parts.append(f"moved to fit the {weeks:.1f}-week window")
        if t.is_critical:
            parts.append("critical: other bookings depend on it")
        if optional:
            parts.append("crisis lead time: optional, skip if it competes with critical items")
        milestones.append(
            Milestone(
                key=t.key,
                title=t.title,
                category=t.category,
                due_date=due,
                weeks_before_event=round((profile.event_date - due).days / 7, 1),
                is_critical=t.is_critical,
                compressed=due != usual_due,
                late_booking=late,
                optional=optional,
                reason="; ".join(parts),
            )
        )
    milestones.sort(key=lambda m: (m.due_date, not m.is_critical))
    return Timeline(
        lead_time_class=klass,
        weeks_available=round(weeks, 1),
        reason=_class_reason(klass, weeks),
        milestones=milestones,
    )


def _event(profile: EventProfile) -> str:
    return profile.event_type.value.replace("_", " ")


def _class_reason(klass: LeadTimeClass, weeks: float) -> str:
    if klass is LeadTimeClass.COMFORTABLE:
        return f"{weeks:.1f} weeks to go (>= {COMFORTABLE_WEEKS}): comfortable lead time"
    if klass is LeadTimeClass.TIGHT:
        return (
            f"{weeks:.1f} weeks to go ({CRISIS_WEEKS}-{COMFORTABLE_WEEKS}): tight, "
            "book key vendors this month"
        )
    return (
        f"{weeks:.1f} weeks to go (< {CRISIS_WEEKS}): crisis mode, "
        "lock venue and food first, simplify everything else"
    )
