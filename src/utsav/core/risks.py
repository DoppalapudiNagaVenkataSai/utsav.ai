"""Feasibility checks and risk flags derived from the profile and the built plan."""

from __future__ import annotations

from utsav.core.knowledge import Knowledge, monsoon_exposure
from utsav.core.models import (
    MEDIUM_MAX_GUESTS,
    BudgetPlan,
    EventProfile,
    EventType,
    LeadTimeClass,
    Risk,
    Setting,
    Severity,
    Timeline,
    format_money,
)


def assess(
    profile: EventProfile, knowledge: Knowledge, budget: BudgetPlan, timeline: Timeline
) -> list[Risk]:
    risks: list[Risk] = []
    cur = profile.currency

    if timeline.lead_time_class is LeadTimeClass.CRISIS:
        risks.append(
            Risk(
                code="lead_time_crisis",
                severity=Severity.CRITICAL,
                message="Very little time left: popular vendors may already be booked.",
                reason=timeline.reason,
            )
        )
    elif timeline.lead_time_class is LeadTimeClass.TIGHT:
        risks.append(
            Risk(
                code="lead_time_tight",
                severity=Severity.WARNING,
                message="Lead time is tight: book the venue and food this month.",
                reason=timeline.reason,
            )
        )

    late = [m for m in timeline.milestones if m.late_booking and m.is_critical]
    if late:
        risks.append(
            Risk(
                code="late_bookings",
                severity=Severity.WARNING,
                message=f"{len(late)} critical item(s) are past their usual booking window: "
                + ", ".join(m.title.lower() for m in late[:4])
                + ("…" if len(late) > 4 else ""),
                reason="Their usual lead time is longer than the weeks left before the event",
            )
        )

    thresholds = knowledge.per_head_thresholds[cur]
    if budget.per_head_minor < thresholds.potluck_below:
        severity = (
            Severity.INFO if profile.event_type is EventType.COMMUNITY_EVENT else Severity.WARNING
        )
        risks.append(
            Risk(
                code="low_per_head_budget",
                severity=severity,
                message=f"Budget is {format_money(budget.per_head_minor, cur)} per guest, "
                "which is very lean. Consider fewer guests or a simpler format.",
                reason=f"Below the illustrative {format_money(thresholds.potluck_below, cur)} "
                "per-guest floor for catered events",
            )
        )

    region = monsoon_exposure(profile.location, profile.setting, profile.event_date, knowledge)
    if region is not None:
        risks.append(
            Risk(
                code="monsoon_outdoor",
                severity=Severity.WARNING,
                message=f"Rain is likely: {profile.event_date:%B} is monsoon season "
                f"for {region.name}.",
                reason="Outdoor or mixed setting during the regional monsoon; extra contingency "
                "was added and a weather backup task is on the checklist",
            )
        )
    elif profile.setting is not Setting.INDOOR and knowledge.region_for(profile.location) is None:
        risks.append(
            Risk(
                code="weather_unknown",
                severity=Severity.INFO,
                message="Check the local weather pattern for your date.",
                reason="Location not in the regional table, so seasonal rain risk is unknown",
            )
        )

    if profile.event_type is EventType.COMMUNITY_EVENT and not profile.has_ticket_revenue:
        risks.append(
            Risk(
                code="no_revenue",
                severity=Severity.INFO,
                message="No ticket revenue: costs depend on sponsors, grants or donations.",
                reason="Community event without ticket sales",
            )
        )

    if profile.guest_count > MEDIUM_MAX_GUESTS and profile.event_type is EventType.BIRTHDAY:
        risks.append(
            Risk(
                code="large_birthday",
                severity=Severity.INFO,
                message="A birthday this size behaves like a small festival: plan crowd flow.",
                reason=f"More than {MEDIUM_MAX_GUESTS} guests",
            )
        )

    order = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}
    risks.sort(key=lambda r: order[r.severity])
    return risks
