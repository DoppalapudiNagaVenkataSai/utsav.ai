"""Budget allocation: base split per event type, then explicit rules.

Rules applied, in order (each leaves a trace in the affected line's ``reason``):

1. Per-head budget (scaled by the region's cost multiplier) picks the catering style.
   Community events below the potluck threshold go potluck and release part of the
   catering share to contingency.
2. More than 150 guests makes sound/AV mandatory (4% carved from other lines).
3. Outdoor or mixed setting in a monsoon month adds 10 points of contingency.
4. Dietary flags annotate the catering line.

Amounts are integers in minor units and always sum exactly to the total.
"""

from __future__ import annotations

from utsav.core.knowledge import Knowledge, monsoon_exposure
from utsav.core.models import (
    MEDIUM_MAX_GUESTS,
    BudgetLine,
    BudgetPlan,
    CateringStyle,
    EventProfile,
    EventType,
    format_money,
)

AV_CATEGORY = "sound_av"
AV_SHARE = 4.0
MONSOON_CONTINGENCY = 10.0
MINOR_PER_MAJOR = 100
POTLUCK_CATERING_KEEP = 0.4  # potluck keeps 40% of catering for drinks, serveware, staples

_PROTECTED = frozenset({"contingency"})


_LABELS = {"sound_av": "Sound & AV", "budget_minor": "Budget"}


def label(category: str) -> str:
    if category in _LABELS:
        return _LABELS[category]
    return category.replace("_", " ").replace(" and ", " & ").capitalize()


def _carve(
    shares: dict[str, float],
    reasons: dict[str, list[str]],
    trims: dict[str, list[str]],
    target: str,
    points: float,
    why: str,
) -> None:
    """Move ``points`` percentage points into ``target``, taken pro rata from other lines."""
    donors = [c for c in shares if c != target and c not in _PROTECTED]
    pool = sum(shares[c] for c in donors)
    for c in donors:
        shares[c] -= points * shares[c] / pool
        trims.setdefault(c, []).append(label(target).lower())
    shares[target] = shares.get(target, 0.0) + points
    reasons.setdefault(target, []).append(why)


def _catering_style(
    profile: EventProfile, knowledge: Knowledge, per_head: int
) -> tuple[CateringStyle, str]:
    thresholds = knowledge.per_head_thresholds[profile.currency]
    region = knowledge.region_for(profile.location)
    multiplier = region.cost_multiplier if region else 1.0
    potluck_below = round(thresholds.potluck_below * multiplier)
    plated_from = round(thresholds.plated_from * multiplier)
    cur = profile.currency
    where = (
        f" (thresholds scaled x{multiplier:g} for {region.name})"
        if region and multiplier != 1
        else ""
    )
    per_head_txt = f"{format_money(per_head, cur)} per guest"

    if per_head < potluck_below:
        if profile.event_type is EventType.COMMUNITY_EVENT:
            return CateringStyle.POTLUCK, (
                f"{per_head_txt} is below {format_money(potluck_below, cur)}{where}; "
                "a potluck or shared-dish format keeps a community event affordable"
            )
        return CateringStyle.BUFFET, (
            f"{per_head_txt} is below {format_money(potluck_below, cur)}{where}; "
            "a simple buffet with a short menu is the most economical catered option"
        )
    if per_head >= plated_from and profile.event_type is not EventType.COMMUNITY_EVENT:
        return CateringStyle.PLATED, (
            f"{per_head_txt} is at or above {format_money(plated_from, cur)}{where}; "
            "the budget supports plated service"
        )
    if profile.event_type is EventType.COMMUNITY_EVENT:
        return CateringStyle.BUFFET, f"{per_head_txt}: buffet or food stalls suit a community event"
    return CateringStyle.BUFFET, (
        f"{per_head_txt} is below the {format_money(plated_from, cur)} plated threshold{where}; "
        "buffet service fits"
    )


def _to_minor(shares: dict[str, float], total: int) -> dict[str, int]:
    """Split ``total`` into whole major units (largest-remainder rounding).

    Amounts sum exactly to ``total``; any sub-unit remainder goes to contingency.
    """
    units, change = divmod(total, MINOR_PER_MAJOR)
    exact = {c: units * s / 100 for c, s in shares.items()}
    whole = {c: int(v) for c, v in exact.items()}
    leftover = units - sum(whole.values())
    by_remainder = sorted(exact, key=lambda c: (exact[c] - whole[c], shares[c]), reverse=True)
    for c in by_remainder[:leftover]:
        whole[c] += 1
    amounts = {c: v * MINOR_PER_MAJOR for c, v in whole.items()}
    amounts["contingency"] += change
    return amounts


def allocate(profile: EventProfile, knowledge: Knowledge) -> BudgetPlan:
    base = knowledge.budget_splits[profile.event_type]
    shares: dict[str, float] = {c: float(p) for c, p in base.items()}
    reasons: dict[str, list[str]] = {}
    trims: dict[str, list[str]] = {}
    notes: dict[str, list[str]] = {}
    per_head = profile.budget_minor // profile.guest_count

    style, style_reason = _catering_style(profile, knowledge, per_head)
    reasons.setdefault("catering", []).append(f"{style.value} service: {style_reason}")
    if style is CateringStyle.POTLUCK:
        released = shares["catering"] * (1 - POTLUCK_CATERING_KEEP)
        shares["catering"] -= released
        shares["contingency"] += released
        reasons["contingency"] = [
            f"received {released:.1f} points released by the potluck catering format"
        ]

    if profile.guest_count > MEDIUM_MAX_GUESTS:
        _carve(
            shares,
            reasons,
            trims,
            AV_CATEGORY,
            AV_SHARE,
            f"{profile.guest_count} guests (> {MEDIUM_MAX_GUESTS}) need amplified sound and AV",
        )

    region = monsoon_exposure(profile.location, profile.setting, profile.event_date, knowledge)
    if region is not None:
        _carve(
            shares,
            reasons,
            trims,
            "contingency",
            MONSOON_CONTINGENCY,
            f"{profile.setting.value} event in {profile.event_date:%B}, monsoon season for "
            f"{region.name}: +{MONSOON_CONTINGENCY:g} points for tents, covers and backup",
        )

    if profile.dietary:
        flags = ", ".join(d.value.replace("_", " ") for d in profile.dietary)
        notes["catering"] = [
            f"Brief the caterer on: {flags}",
            "Ask for separate prep and labelled dishes for allergy-related needs",
        ]

    amounts = _to_minor(shares, profile.budget_minor)
    event_name = profile.event_type.value.replace("_", " ")
    lines = []
    for category, share in sorted(shares.items(), key=lambda kv: -kv[1]):
        base_pct = base.get(category)
        head = (
            f"Base share for a {event_name}: {base_pct}% (illustrative default)"
            if base_pct is not None
            else "Added by rule"
        )
        why = [head, *reasons.get(category, [])]
        if category in trims:
            why.append("trimmed pro rata to fund " + " and ".join(trims[category]))
        lines.append(
            BudgetLine(
                category=category,
                amount_minor=amounts[category],
                percent=round(share, 2),
                reason="; ".join(why),
                notes=notes.get(category, []),
            )
        )
    return BudgetPlan(
        total_minor=profile.budget_minor,
        currency=profile.currency,
        per_head_minor=per_head,
        catering_style=style,
        catering_reason=style_reason,
        lines=lines,
    )
