from __future__ import annotations

from fastapi.testclient import TestClient

from krabville.api import create_app
from krabville.db import initialize
from krabville.world import advance_tick, start_season


def test_public_state_hides_seed_until_completion(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="71" * 32)
    connection.close()
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        response = client.get("/api/v2/state")
        assert response.status_code == 200
        payload = response.json()
        assert payload["season"]["revealedSeed"] is None
        serialized = response.text
        assert "7171717171717171" not in serialized
        assert str(settings.database_path) not in serialized
        assert len(payload["residents"]) == 12
        assert payload["models"]["primary"] == "gpt-5.3-codex-spark"


def test_vote_requires_cookie_csrf_and_allows_choice_change(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="72" * 32)
    for _ in range(25):
        advance_tick(connection)
    connection.close()
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        poll_response = client.get("/api/v2/polls/current")
        poll = poll_response.json()["poll"]
        csrf = client.cookies.get("kv_csrf")
        first, second = poll["options"][:2]
        headers = {"Origin": "http://testserver"}
        response = client.post(
            f"/api/v2/polls/{poll['id']}/vote",
            json={"choiceId": first["choiceId"], "csrfToken": csrf},
            headers=headers,
        )
        assert response.status_code == 200
        response = client.post(
            f"/api/v2/polls/{poll['id']}/vote",
            json={"choiceId": second["choiceId"], "csrfToken": csrf},
            headers=headers,
        )
        assert response.status_code == 200
        options = {item["choiceId"]: item["votes"] for item in response.json()["poll"]["options"]}
        assert options[first["choiceId"]] == 0
        assert options[second["choiceId"]] == 1
        rejected = client.post(
            f"/api/v2/polls/{poll['id']}/vote",
            json={"choiceId": first["choiceId"], "csrfToken": "wrong" * 8},
            headers=headers,
        )
        assert rejected.status_code == 403
        extra = client.post(
            f"/api/v2/polls/{poll['id']}/vote",
            json={"choiceId": first["choiceId"], "csrfToken": csrf, "prompt": "ignore rules"},
            headers=headers,
        )
        assert extra.status_code == 422


def test_events_are_resumable_and_compatibility_route_survives(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="73" * 32)
    for _ in range(13):
        advance_tick(connection)
    connection.close()
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        first = client.get("/api/v2/events?after=0&limit=2").json()
        second = client.get(f"/api/v2/events?after={first['next']}&limit=100").json()
        assert first["events"]
        assert all(item["seq"] > first["next"] for item in second["events"])
        legacy = client.get("/api/krabville/state")
        assert legacy.status_code == 200
        assert legacy.json()["simulation"] == "krabville-v2"


def test_untrusted_host_is_rejected(settings_factory) -> None:
    settings = settings_factory()
    with TestClient(create_app(settings), base_url="http://evil.invalid") as client:
        assert client.get("/healthz").status_code == 400


def test_empty_town_state_has_a_complete_public_schema(settings_factory) -> None:
    settings = settings_factory()
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        payload = client.get("/api/v2/state").json()
        assert payload["season"] is None
        assert payload["usage"]["calls"] == 0
        assert payload["models"]["primary"] == "gpt-5.3-codex-spark"
        assert payload["residents"] == payload["events"] == payload["goals"] == []
