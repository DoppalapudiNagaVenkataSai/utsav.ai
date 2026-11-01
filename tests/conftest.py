from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest

from utsav.core.knowledge import Knowledge, load_knowledge
from utsav.core.models import EventProfile

TODAY = date(2026, 1, 5)  # a Monday; fixed so every date-based rule is reproducible

ProfileFactory = Callable[..., EventProfile]


@pytest.fixture
def today() -> date:
    return TODAY


@pytest.fixture
def knowledge() -> Knowledge:
    return load_knowledge()


@pytest.fixture
def make_profile() -> ProfileFactory:
    def factory(**overrides: Any) -> EventProfile:
        weeks = overrides.pop("weeks_out", None)
        data: dict[str, Any] = {
            "event_type": "birthday",
            "event_date": TODAY + timedelta(weeks=30),
            "guest_count": 40,
            "budget_minor": 200_000_00,
            "currency": "INR",
            "location": "Kochi, Kerala",
            "setting": "indoor",
        }
        if weeks is not None:
            data["event_date"] = TODAY + timedelta(weeks=weeks)
        data.update(overrides)
        return EventProfile.model_validate(data)

    return factory


# ---- AI mocking ------------------------------------------------------------

import json  # noqa: E402
import socket  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from utsav.ai.client import AIClient  # noqa: E402
from utsav.core.planner import build_plan  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if any test tries to open a real network connection."""

    def guard(*args, **kwargs):
        raise RuntimeError("network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


class FakeSDK:
    """Stands in for Google GenAI client; records calls, returns canned responses."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []
        self.models = self

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        if isinstance(item, SimpleNamespace):
            return item
        text = item if isinstance(item, str) else json.dumps(item)
        return SimpleNamespace(
            text=text,
            candidates=[
                SimpleNamespace(
                    finish_reason="STOP",
                    content=SimpleNamespace(parts=[SimpleNamespace(text=text)]),
                )
            ],
        )


@pytest.fixture
def fake_ai():
    def factory(*responses: Any) -> tuple[AIClient, FakeSDK]:
        sdk = FakeSDK(*responses)
        return AIClient(api_key="test-key", model="test-model", sdk=sdk), sdk

    return factory


@pytest.fixture
def disabled_ai() -> AIClient:
    return AIClient(api_key="", model="test-model")


@pytest.fixture
def sample_plan(make_profile, today):
    return build_plan(
        make_profile(
            event_type="wedding",
            guest_count=200,
            budget_minor=8_00_000_00,
            setting="outdoor",
            event_date=date(2026, 7, 18),
            dietary=["vegetarian"],
            vibe="Kerala backwaters, relaxed",
        ),
        today=today,
    )


# ---- API -------------------------------------------------------------------

from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from utsav.api.app import create_app  # noqa: E402
from utsav.config import Settings  # noqa: E402
from utsav.core.knowledge import DEFAULT_DATA_DIR  # noqa: E402
from utsav.storage.repo import PlanRepository  # noqa: E402


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        gemini_api_key="",
        model="test-model",
        ai_enabled=False,
        db_path=tmp_path / "test.db",
        data_dir=DEFAULT_DATA_DIR,
    )


@pytest.fixture
def make_client(tmp_path):
    def factory(ai: AIClient | None = None) -> TestClient:
        settings = _settings(tmp_path)
        app = create_app(settings, ai=ai, repo=PlanRepository(":memory:"))
        return TestClient(app)

    return factory


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@pytest.fixture
def profile_json() -> dict[str, Any]:
    future = date.today() + timedelta(weeks=30)
    return {
        "event_type": "wedding",
        "event_date": future.isoformat(),
        "guest_count": 120,
        "budget_minor": 10_00_000_00,
        "currency": "INR",
        "location": "Kochi",
        "setting": "indoor",
        "vibe": "relaxed",
        "dietary": ["vegetarian"],
    }


@pytest.fixture
def created(client, profile_json) -> dict[str, Any]:
    response = client.post("/api/plans", json=profile_json)
    assert response.status_code == 201, response.text
    return response.json()
