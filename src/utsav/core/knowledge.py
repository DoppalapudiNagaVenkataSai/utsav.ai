"""Loads the illustrative planning data in ``data/*.json`` into typed tables.

The data directory defaults to ``<repo>/data`` and can be overridden by passing a
path to :func:`load_knowledge` (the API layer does this from settings). Loaded
tables are validated once and cached for the process lifetime.
"""

from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from utsav.core.models import Currency, EventType, Scale, Setting

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data"


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MilestoneTemplate(_Frozen):
    key: str
    title: str
    weeks_before_event: int = Field(ge=0)
    category: str
    is_critical: bool


class TaskTemplate(_Frozen):
    key: str
    title: str
    category: str
    is_critical: bool


class ScaleChecklist(_Frozen):
    base: list[TaskTemplate]
    small: list[TaskTemplate]
    medium: list[TaskTemplate]
    large: list[TaskTemplate]

    def for_scale(self, scale: Scale) -> list[TaskTemplate]:
        extra: list[TaskTemplate] = getattr(self, scale.value)
        return [*self.base, *extra]


class PerHeadThresholds(_Frozen):
    potluck_below: int = Field(gt=0)
    plated_from: int = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self) -> PerHeadThresholds:
        if self.plated_from <= self.potluck_below:
            raise ValueError("plated_from must be greater than potluck_below")
        return self


class Region(_Frozen):
    name: str
    keywords: list[str]
    monsoon_months: list[int]
    cost_multiplier: float = Field(gt=0)


class Knowledge(_Frozen):
    budget_splits: dict[EventType, dict[str, int]]
    timelines: dict[EventType, list[MilestoneTemplate]]
    checklists: dict[EventType, ScaleChecklist]
    per_head_thresholds: dict[Currency, PerHeadThresholds]
    regions: list[Region]

    @model_validator(mode="after")
    def _complete(self) -> Knowledge:
        for event_type in EventType:
            split = self.budget_splits.get(event_type)
            if split is None or sum(split.values()) != 100:
                raise ValueError(f"budget split for {event_type} must exist and sum to 100")
            if "contingency" not in split or "catering" not in split:
                raise ValueError(f"budget split for {event_type} needs catering and contingency")
            if event_type not in self.timelines or event_type not in self.checklists:
                raise ValueError(f"missing timeline or checklist for {event_type}")
        for currency in Currency:
            if currency not in self.per_head_thresholds:
                raise ValueError(f"missing per-head thresholds for {currency}")
        return self

    def region_for(self, location: str) -> Region | None:
        needle = location.lower()
        for region in self.regions:
            if any(keyword in needle for keyword in region.keywords):
                return region
        return None


def _read(data_dir: Path, name: str) -> dict[str, object]:
    with (data_dir / name).open(encoding="utf-8") as fh:
        raw: dict[str, object] = json.load(fh)
    raw.pop("_note", None)
    return raw


@lru_cache(maxsize=4)
def load_knowledge(data_dir: Path = DEFAULT_DATA_DIR) -> Knowledge:
    regional = _read(data_dir, "regional_factors.json")
    return Knowledge.model_validate(
        {
            "budget_splits": _read(data_dir, "budget_splits.json"),
            "timelines": _read(data_dir, "timeline_templates.json"),
            "checklists": _read(data_dir, "checklists.json"),
            "per_head_thresholds": regional["per_head_thresholds"],
            "regions": regional["regions"],
        }
    )


def monsoon_exposure(
    location: str, setting: Setting, event_date: date, knowledge: Knowledge
) -> Region | None:
    """Return the matched region if an (at least partly) outdoor event falls in its monsoon."""
    if setting is Setting.INDOOR:
        return None
    region = knowledge.region_for(location)
    if region is not None and event_date.month in region.monsoon_months:
        return region
    return None
