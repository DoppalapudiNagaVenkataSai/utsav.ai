"""Orchestrates the engine: ``build_plan(profile) -> Plan``. Pure and deterministic."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from occasio.core.budget import allocate
from occasio.core.checklist import build_checklist
from occasio.core.knowledge import DEFAULT_DATA_DIR, load_knowledge
from occasio.core.models import EventProfile, Plan, scale_for
from occasio.core.risks import assess
from occasio.core.timeline import build_timeline


def build_plan(
    profile: EventProfile, today: date | None = None, data_dir: Path = DEFAULT_DATA_DIR
) -> Plan:
    """Build a full plan. ``today`` is injectable so results are reproducible in tests."""
    today = today or date.today()
    knowledge = load_knowledge(data_dir)
    timeline = build_timeline(profile, knowledge, today)
    budget = allocate(profile, knowledge)
    return Plan(
        profile=profile,
        generated_on=today,
        scale=scale_for(profile.guest_count),
        budget=budget,
        timeline=timeline,
        checklist=build_checklist(profile, knowledge, timeline),
        risks=assess(profile, knowledge, budget, timeline),
    )
