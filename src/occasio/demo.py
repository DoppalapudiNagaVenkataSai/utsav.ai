"""Seed one sample plan per event type: ``python -m occasio.demo`` (or ``make demo``)."""

from __future__ import annotations

from datetime import date, timedelta

from occasio.config import get_settings
from occasio.core.models import EventProfile
from occasio.core.planner import build_plan
from occasio.storage.repo import PlanRepository


def sample_profiles(today: date) -> list[EventProfile]:
    return [
        EventProfile(
            event_type="wedding", event_date=today + timedelta(weeks=30), guest_count=200,
            budget_minor=8_00_000_00, currency="INR", location="Kochi, Kerala",
            setting="outdoor", vibe="Backwaters at sunset, relaxed",
            preferences=["live music", "Kerala sadya"], dietary=["vegetarian"],
        ),
        EventProfile(
            event_type="birthday", event_date=today + timedelta(weeks=5), guest_count=35,
            budget_minor=1_500_00, currency="USD", location="Austin, Texas",
            setting="mixed", vibe="Retro arcade", must_haves=["photo booth"],
            dietary=["gluten_free"],
        ),
        EventProfile(
            event_type="community_event", event_date=today + timedelta(weeks=10),
            guest_count=300, budget_minor=60_000_00, currency="INR",
            location="Bengaluru", setting="outdoor", vibe="Neighbourhood harvest fair",
            dietary=["vegan", "jain"],
        ),
    ]  # fmt: skip


def main() -> None:
    settings = get_settings()
    repo = PlanRepository(settings.db_path)
    for profile in sample_profiles(date.today()):
        stored = repo.create(build_plan(profile, data_dir=settings.data_dir))
        print(f"{profile.event_type.value:16} http://127.0.0.1:8000/#plan={stored.id}")
    repo.close()


if __name__ == "__main__":
    main()
