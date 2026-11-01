"""Typed domain models for the planning engine.

Money is always an integer number of minor units (paise, cents, pence) paired with
a currency code. Dates are plain ``datetime.date`` values; the engine has no notion
of time zones and treats every date as the planner's local calendar date.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
TagText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]

MAX_GUESTS = 5000
MAX_BUDGET_MINOR = 10**12  # 10 billion major units; anything above is a typo


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EventType(StrEnum):
    WEDDING = "wedding"
    BIRTHDAY = "birthday"
    COMMUNITY_EVENT = "community_event"


class Setting(StrEnum):
    INDOOR = "indoor"
    OUTDOOR = "outdoor"
    MIXED = "mixed"


class Currency(StrEnum):
    INR = "INR"
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class DietaryFlag(StrEnum):
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    HALAL = "halal"
    KOSHER = "kosher"
    JAIN = "jain"
    GLUTEN_FREE = "gluten_free"
    NUT_ALLERGY = "nut_allergy"
    DAIRY_FREE = "dairy_free"


class Scale(StrEnum):
    SMALL = "small"  # < 50 guests
    MEDIUM = "medium"  # 50-150 guests
    LARGE = "large"  # > 150 guests


class LeadTimeClass(StrEnum):
    COMFORTABLE = "comfortable"  # >= 16 weeks
    TIGHT = "tight"  # 6-16 weeks
    CRISIS = "crisis"  # < 6 weeks


class CateringStyle(StrEnum):
    POTLUCK = "potluck"
    BUFFET = "buffet"
    PLATED = "plated"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class TaskStatus(StrEnum):
    TODO = "todo"
    DONE = "done"


class EventProfile(StrictModel):
    """Everything the planner knows about the event. Validated at the boundary."""

    event_type: EventType
    event_date: date
    guest_count: int = Field(ge=1, le=MAX_GUESTS)
    budget_minor: int = Field(gt=0, le=MAX_BUDGET_MINOR)
    currency: Currency = Currency.INR
    location: ShortText = Field(min_length=1)
    setting: Setting = Setting.INDOOR
    vibe: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    preferences: list[TagText] = Field(default_factory=list, max_length=10)
    must_haves: list[TagText] = Field(default_factory=list, max_length=10)
    dietary: list[DietaryFlag] = Field(default_factory=list, max_length=len(DietaryFlag))
    has_ticket_revenue: bool = False


class BudgetLine(StrictModel):
    category: str
    amount_minor: int = Field(ge=0)
    percent: float
    reason: str
    notes: list[str] = Field(default_factory=list)


class BudgetPlan(StrictModel):
    total_minor: int
    currency: Currency
    per_head_minor: int
    catering_style: CateringStyle
    catering_reason: str
    lines: list[BudgetLine]


class Milestone(StrictModel):
    key: str
    title: str
    category: str
    due_date: date
    weeks_before_event: float
    is_critical: bool
    compressed: bool = False
    late_booking: bool = False
    optional: bool = False
    reason: str


class Timeline(StrictModel):
    lead_time_class: LeadTimeClass
    weeks_available: float
    reason: str
    milestones: list[Milestone]


class Task(StrictModel):
    id: str
    title: str
    category: str
    is_critical: bool = False
    status: TaskStatus = TaskStatus.TODO
    reason: str


class Checklist(StrictModel):
    items: list[Task]


class Risk(StrictModel):
    code: str
    severity: Severity
    message: str
    reason: str


class Plan(StrictModel):
    profile: EventProfile
    generated_on: date
    scale: Scale
    budget: BudgetPlan
    timeline: Timeline
    checklist: Checklist
    risks: list[Risk]


class ChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class Change(StrictModel):
    section: str
    key: str
    kind: ChangeKind
    before: Any = None
    after: Any = None
    message: str


class PlanDiff(StrictModel):
    changes: list[Change]

    @property
    def is_empty(self) -> bool:
        return not self.changes


_SYMBOLS = {Currency.INR: "₹", Currency.USD: "$", Currency.EUR: "€", Currency.GBP: "£"}


def format_money(amount_minor: int, currency: Currency) -> str:
    """Render minor units as a human string, e.g. ``4000000, INR -> '₹40,000'``.

    Indian rupees use lakh grouping (₹8,00,000); others use thousands grouping.
    Whole amounts drop the decimals to keep messages short.
    """
    sign = "-" if amount_minor < 0 else ""
    major, minor = divmod(abs(amount_minor), 100)
    if currency == Currency.INR:
        digits = str(major)
        head, tail = digits[:-3], digits[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        body = ",".join([*groups, tail]) if groups else tail
    else:
        body = f"{major:,}"
    cents = f".{minor:02d}" if minor else ""
    return f"{sign}{_SYMBOLS[Currency(currency)]}{body}{cents}"


SMALL_MAX_GUESTS = 49
MEDIUM_MAX_GUESTS = 150


def scale_for(guest_count: int) -> Scale:
    """small < 50, medium 50-150 (inclusive), large > 150."""
    if guest_count <= SMALL_MAX_GUESTS:
        return Scale.SMALL
    if guest_count <= MEDIUM_MAX_GUESTS:
        return Scale.MEDIUM
    return Scale.LARGE
