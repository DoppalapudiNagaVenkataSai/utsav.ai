"""Template output used when AI is disabled, fails, or returns something invalid.

Everything here is derived from the engine plan (and its ``reason`` fields), so the
app stays useful with no API key.
"""

from __future__ import annotations

import calendar
import re
from datetime import date

from occasio.ai.schemas import (
    ExplanationPoint,
    ExplanationResult,
    Idea,
    IdeaKind,
    IdeasResult,
    IntakePayload,
)
from occasio.core.budget import label
from occasio.core.models import (
    CateringStyle,
    DietaryFlag,
    EventType,
    Plan,
    Setting,
    format_money,
)

# ---- ideas ---------------------------------------------------------------

_THEMES: dict[EventType, list[tuple[str, str]]] = {
    EventType.WEDDING: [
        ("Garden of lights", "Fairy lights, marigold or local-flower garlands and lanterns."),
        ("Heritage revival", "Traditional textiles, brass accents and a regional-music set."),
        ("Minimal modern", "Neutral palette, greenery runners and candlelight."),
    ],
    EventType.BIRTHDAY: [
        (
            "Decade throwback",
            "Music, outfits and snacks from the year the guest of honour was born.",
        ),
        ("Game night", "Board-game tables, a quiz round and small prizes."),
        ("Picnic social", "Mats, cushions, finger food and lawn games."),
    ],
    EventType.COMMUNITY_EVENT: [
        ("Neighbourhood fair", "Stalls run by local groups, kids' corner and a small stage."),
        ("Culture showcase", "Food, music and craft from the community's traditions."),
        ("Green day", "Tree planting or cleanup paired with a shared meal."),
    ],
}

_MENU = {
    CateringStyle.PLATED: "A three-course plated menu with one regional signature dish.",
    CateringStyle.BUFFET: "A buffet with live counters for one or two crowd favourites.",
    CateringStyle.POTLUCK: "A themed potluck: assign starters, mains and desserts by surname.",
}


def ideas(plan: Plan) -> IdeasResult:
    profile = plan.profile
    themes = _THEMES[profile.event_type]
    vibe = f" Matches your '{profile.vibe}' vibe." if profile.vibe else ""
    setting = "outdoor" if profile.setting is not Setting.INDOOR else "indoor"
    out = [
        Idea(
            title=title,
            kind=IdeaKind.THEME,
            description=desc,
            why_it_fits=f"A proven theme for a {plan.scale.value} {setting} "
            f"{profile.event_type.value.replace('_', ' ')}.{vibe}"[:400],
        )
        for title, desc in themes[:2]
    ]
    dietary = ", ".join(d.value.replace("_", " ") for d in profile.dietary)
    out.append(
        Idea(
            title=f"{plan.budget.catering_style.value.capitalize()} menu",
            kind=IdeaKind.MENU,
            description=_MENU[plan.budget.catering_style]
            + (f" Label every dish for: {dietary}." if dietary else ""),
            why_it_fits=plan.budget.catering_reason[:400],
        )
    )
    if profile.setting is not Setting.INDOOR:
        out.append(
            Idea(
                title="Weather-proof decor",
                kind=IdeaKind.DECOR,
                description="Fabric canopies and lanterns that double as rain cover.",
                why_it_fits="Your event is partly or fully outdoors.",
            )
        )
    else:
        out.append(
            Idea(
                title=themes[2][0],
                kind=IdeaKind.THEME,
                description=themes[2][1],
                why_it_fits="A simple alternative that is easy to set up indoors.",
            )
        )
    return IdeasResult(ideas=out, source="fallback")


# ---- explanation ---------------------------------------------------------


def explanation(plan: Plan) -> ExplanationResult:
    b, tl, cur = plan.budget, plan.timeline, plan.budget.currency
    top = b.lines[0]
    summary = (
        f"This {plan.scale.value} {plan.profile.event_type.value.replace('_', ' ')} plan splits "
        f"{format_money(b.total_minor, cur)} across {len(b.lines)} categories, with "
        f"{label(top.category).lower()} the largest at {format_money(top.amount_minor, cur)}. "
        f"{tl.reason[0].upper()}{tl.reason[1:]}."
    )
    points = [
        ExplanationPoint(topic="Catering style", explanation=b.catering_reason[:400]),
        ExplanationPoint(topic=f"{label(top.category)} budget", explanation=top.reason[:400]),
    ]
    rule_lines = [
        line for line in b.lines if "Added by rule" in line.reason or "monsoon" in line.reason
    ]
    points += [
        ExplanationPoint(topic=label(line.category), explanation=line.reason[:400])
        for line in rule_lines[:2]
    ]
    critical = [m for m in tl.milestones if m.is_critical and not m.late_booking][:1]
    points += [
        ExplanationPoint(topic=f"Next: {m.title}"[:80], explanation=m.reason[:400])
        for m in critical
    ]
    points += [
        ExplanationPoint(topic=f"Risk: {r.code.replace('_', ' ')}", explanation=r.reason[:400])
        for r in plan.risks[:2]
    ]
    return ExplanationResult(summary=summary[:700], points=points[:8], source="fallback")


# ---- intake --------------------------------------------------------------

_TYPE_WORDS = {
    EventType.WEDDING: ("wedding", "marriage", "reception", "engagement", "shaadi"),
    EventType.BIRTHDAY: ("birthday", "bday", "turning", "anniversary party"),
    EventType.COMMUNITY_EVENT: (
        "community",
        "fundraiser",
        "festival",
        "meetup",
        "fair",
        "charity",
        "neighbourhood",
        "neighborhood",
    ),
}
_DIET_WORDS = {
    DietaryFlag.VEGAN: ("vegan",),
    DietaryFlag.VEGETARIAN: ("vegetarian", "veg only", "pure veg"),
    DietaryFlag.HALAL: ("halal",),
    DietaryFlag.KOSHER: ("kosher",),
    DietaryFlag.JAIN: ("jain",),
    DietaryFlag.GLUTEN_FREE: ("gluten",),
    DietaryFlag.NUT_ALLERGY: ("nut allerg", "nut-free", "nut free", "peanut"),
    DietaryFlag.DAIRY_FREE: ("dairy", "lactose"),
}
_GUESTS_RE = re.compile(
    r"(\d{1,4})\s*(?:\+\s*)?(?:people|guests|pax|persons|attendees|heads)", re.I
)
_MONEY_RE = re.compile(
    r"(?P<sym>[₹$€£]|rs\.?|inr|usd|eur|gbp)?\s*~?\s*(?P<num>\d+(?:[.,]\d+)*)\s*"
    r"(?P<unit>lakhs?|lacs?|crores?|cr|k|thousand|million|m)?\b\s*(?P<word>rupees|dollars|euros|pounds)?",
    re.I,
)
_UNITS = {
    "lakh": 1e5,
    "lac": 1e5,
    "crore": 1e7,
    "cr": 1e7,
    "k": 1e3,
    "thousand": 1e3,
    "million": 1e6,
    "m": 1e6,
}
_CURRENCY = {"₹": "INR", "rs": "INR", "inr": "INR", "rupees": "INR", "$": "USD", "usd": "USD",
             "dollars": "USD", "€": "EUR", "eur": "EUR", "euros": "EUR", "£": "GBP", "gbp": "GBP",
             "pounds": "GBP"}  # fmt: skip
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | {
    m.lower(): i for i, m in enumerate(calendar.month_abbr) if m
}
_MONTH_RE = re.compile(r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\b", re.I)


def intake(text: str, today: date) -> IntakePayload:
    """Best-effort keyword/regex extraction so 'Autofill' does something without AI."""
    low = text.lower()
    event_type = next((t for t, words in _TYPE_WORDS.items() if any(w in low for w in words)), None)
    guests_match = _GUESTS_RE.search(text)
    guest_count = int(guests_match.group(1)) if guests_match else None

    budget, currency = None, None
    for m in _MONEY_RE.finditer(text):
        if guests_match and m.start("num") == guests_match.start(1):
            continue
        unit = (m.group("unit") or "").lower().rstrip("s")
        sym = (m.group("sym") or m.group("word") or "").lower().rstrip(".")
        if not unit and not sym:
            continue
        value = float(m.group("num").replace(",", "")) * _UNITS.get(unit, 1)
        budget = value
        currency = _CURRENCY.get(sym) or ("INR" if unit in ("lakh", "lac", "crore", "cr") else None)
        break

    event_date = None
    month = _MONTH_RE.search(text)
    if month:
        mnum = _MONTHS[month.group(1).lower()]
        year = today.year if mnum > today.month else today.year + 1
        event_date = date(year, mnum, 1).isoformat()

    setting = None
    if "outdoor" in low or "open air" in low or "garden" in low or "beach" in low:
        setting = Setting.MIXED if "indoor" in low else Setting.OUTDOOR
    elif "indoor" in low or "hall" in low:
        setting = Setting.INDOOR

    location = None
    loc = re.search(
        r"\b(?:in|at)\s+([A-Z][\w\- ]{1,40}?)(?=[,.;]|\s+(?:on|in|for|with|around)\b|$)", text
    )
    if loc and loc.group(1).lower() not in _MONTHS:
        location = loc.group(1).strip()

    return IntakePayload(
        event_type=event_type,
        guest_count=guest_count,
        budget_amount=budget,
        currency=currency,
        event_date=event_date,
        location=location,
        setting=setting,
        vibe=None,
        preferences=[],
        dietary=[d for d, words in _DIET_WORDS.items() if any(w in low for w in words)],
        has_ticket_revenue=True if re.search(r"\btickets?\b", low) else None,
    )
