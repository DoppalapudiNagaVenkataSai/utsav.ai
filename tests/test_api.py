from __future__ import annotations

from datetime import date, timedelta

import pytest

from utsav.api.app import AI_RATE_LIMIT, MAX_BODY_BYTES

UNKNOWN = "0" * 32


def test_healthz_reports_ai_disabled(client):
    body = client.get("/healthz").json()
    assert body == {"status": "ok", "ai_enabled": False, "model": None}


def test_healthz_reports_ai_enabled(make_client, fake_ai):
    ai, _ = fake_ai({})
    assert make_client(ai).get("/healthz").json()["ai_enabled"] is True


def test_create_and_get_plan(client, created, profile_json):
    assert len(created["id"]) == 32
    plan = created["plan"]
    assert plan["profile"]["guest_count"] == 120
    assert sum(line["amount_minor"] for line in plan["budget"]["lines"]) == 10_00_000_00
    fetched = client.get(f"/api/plans/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["plan"] == plan


@pytest.mark.parametrize(
    "patch",
    [
        {"guest_count": 0},
        {"budget_minor": -1},
        {"budget_minor": 0},
        {"event_type": "rave"},
        {"location": "x" * 500},
        {"vibe": "x" * 201},
        {"preferences": ["a"] * 11},
        {"unexpected": "field"},
        {"currency": "BTC"},
        {"event_date": "not-a-date"},
    ],
)
def test_create_validation_errors(client, profile_json, patch):
    assert client.post("/api/plans", json={**profile_json, **patch}).status_code == 422


def test_create_rejects_past_date(client, profile_json):
    past = (date.today() - timedelta(days=1)).isoformat()
    response = client.post("/api/plans", json={**profile_json, "event_date": past})
    assert response.status_code == 422
    assert "after today" in response.json()["detail"]


def test_unknown_and_malformed_ids(client):
    assert client.get(f"/api/plans/{UNKNOWN}").status_code == 404
    assert client.get("/api/plans/not-an-id").status_code == 422
    assert client.post(f"/api/plans/{UNKNOWN}/replan", json={}).status_code == 404
    assert client.post(f"/api/plans/{UNKNOWN}/ideas").status_code == 404
    assert client.get(f"/api/plans/{UNKNOWN}/export").status_code == 404


def test_replan_returns_diff_and_persists(client, created):
    pid = created["id"]
    response = client.post(f"/api/plans/{pid}/replan", json={"budget_minor": 8_00_000_00})
    assert response.status_code == 200
    body = response.json()
    messages = [c["message"] for c in body["diff"]["changes"]]
    assert "Decor reduced ₹1,00,000 → ₹80,000" in messages
    assert client.get(f"/api/plans/{pid}").json()["plan"]["profile"]["budget_minor"] == 8_00_000_00


def test_replan_validation(client, created):
    pid = created["id"]
    assert client.post(f"/api/plans/{pid}/replan", json={"guest_count": -3}).status_code == 422
    assert client.post(f"/api/plans/{pid}/replan", json={"nope": 1}).status_code == 422
    assert client.post(f"/api/plans/{pid}/replan", json={"guest_count": None}).status_code == 422


def test_task_status_persisted_and_carried_through_replan(client, created):
    pid = created["id"]
    response = client.patch(f"/api/plans/{pid}/tasks/venue", json={"status": "done"})
    assert response.status_code == 200
    venue = next(t for t in response.json()["plan"]["checklist"]["items"] if t["id"] == "venue")
    assert venue["status"] == "done"
    replanned = client.post(f"/api/plans/{pid}/replan", json={"guest_count": 140}).json()
    items = {t["id"]: t for t in replanned["plan"]["checklist"]["items"]}
    assert items["venue"]["status"] == "done"
    assert "confirm_venue_capacity" in items


def test_task_errors(client, created):
    pid = created["id"]
    assert client.patch(f"/api/plans/{pid}/tasks/ghost", json={"status": "done"}).status_code == 404
    assert (
        client.patch(f"/api/plans/{pid}/tasks/venue", json={"status": "maybe"}).status_code == 422
    )
    assert client.patch(f"/api/plans/{pid}/tasks/BAD!", json={"status": "done"}).status_code == 422


def test_export_markdown_and_json(client, created):
    pid = created["id"]
    md = client.get(f"/api/plans/{pid}/export?format=md")
    assert md.status_code == 200
    assert md.headers["content-type"].startswith("text/markdown")
    assert "attachment" in md.headers["content-disposition"]
    assert md.text.startswith("# Wedding plan")
    assert "| Catering |" in md.text
    js = client.get(f"/api/plans/{pid}/export?format=json")
    assert js.json()["id"] == pid
    assert client.get(f"/api/plans/{pid}/export?format=pdf").status_code == 422


def test_ai_endpoints_fall_back_without_key(client, created):
    pid = created["id"]
    ideas = client.post(f"/api/plans/{pid}/ideas").json()
    assert ideas["source"] == "fallback" and 3 <= len(ideas["ideas"]) <= 5
    explanation = client.post(f"/api/plans/{pid}/explain").json()
    assert explanation["source"] == "fallback" and explanation["summary"]
    intake = client.post("/api/ai/intake", json={"text": "Birthday for 30 guests in Pune"}).json()
    assert intake["source"] == "fallback"
    assert intake["fields"]["guest_count"] == 30


def test_ai_endpoints_with_mocked_model(make_client, fake_ai, profile_json):
    ai, sdk = fake_ai(
        {"ideas": [{"title": "T", "kind": "menu", "description": "D", "why_it_fits": "W"}] * 3}
    )
    c = make_client(ai)
    pid = c.post("/api/plans", json=profile_json).json()["id"]
    assert c.post(f"/api/plans/{pid}/ideas").json()["source"] == "ai"
    assert len(sdk.calls) == 1


def test_intake_validation(client):
    assert client.post("/api/ai/intake", json={"text": ""}).status_code == 422
    assert client.post("/api/ai/intake", json={"text": "x" * 2001}).status_code == 422
    assert client.post("/api/ai/intake", json={"text": "hi", "extra": 1}).status_code == 422


def test_rate_limit_on_ai_endpoints(client):
    for _ in range(AI_RATE_LIMIT):
        assert client.post("/api/ai/intake", json={"text": "a party"}).status_code == 200
    blocked = client.post("/api/ai/intake", json={"text": "a party"})
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "60"
    assert client.get("/healthz").status_code == 200  # non-AI routes unaffected


def test_oversized_body_rejected(client, profile_json):
    big = {**profile_json, "vibe": "x" * (MAX_BODY_BYTES + 10)}
    assert client.post("/api/plans", json=big).status_code == 413


def test_oversized_streamed_body_rejected(client):
    def chunks():
        for _ in range(80):
            yield b"x" * 1024

    response = client.post(
        "/api/ai/intake", content=chunks(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413


def test_security_headers(client, created):
    for path in ("/healthz", f"/api/plans/{created['id']}", "/"):
        headers = client.get(path).headers
        assert "default-src 'self'" in headers["content-security-policy"]
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["x-frame-options"] == "DENY"


def test_no_cors_for_other_origins(client):
    response = client.options(
        "/api/plans",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_errors_do_not_leak_stack_traces(make_client, monkeypatch, profile_json):
    from utsav.api import routes_plan

    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(routes_plan, "build_plan", boom)
    c = make_client()
    c_raise = type(c)(c.app, raise_server_exceptions=False)
    response = c_raise.post("/api/plans", json=profile_json)
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert "secret" not in response.text and "Traceback" not in response.text


def test_static_ui_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "utsav.ai" in response.text


def test_openapi_docs_available(client):
    assert client.get("/docs").status_code == 200
    assert "/api/plans" in client.get("/openapi.json").json()["paths"]
