from __future__ import annotations

from fastapi.testclient import TestClient

from krabville.api import create_app
from krabville.db import dumps, initialize
from krabville.world import advance_tick, start_season


def test_public_state_hides_seed_until_completion(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="71" * 32)
    connection.execute(
        "UPDATE seasons SET weather_json=? WHERE number=1",
        (dumps({"season": "summer", "condition": "heatwave", "temperatureC": 35}),),
    )
    connection.commit()
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
        v3 = client.get("/api/v3/state")
        assert v3.status_code == 200
        modern = v3.json()
        assert modern["schemaVersion"] == 3
        assert modern["season"]["weather"]["season"] == "spring"
        assert modern["world"]["mapAsset"] == "/assets/kvsim-town-v21-spring.webp"
        assert set(modern["world"]["mapAssets"]) == {"spring", "summer", "fall", "winter"}
        assert modern["world"]["interiorsAsset"] == "/assets/interiors-v4.png"
        assert modern["world"]["weatherAsset"] == "/assets/weather-seasons-v1.png"
        assert modern["world"]["inventoryAsset"] == "/assets/inventory-items-v2.png"
        assert modern["world"]["eventAsset"] == "/assets/event-props-v21.png"
        future_homes = [item for item in modern["properties"] if item["slug"] in {
            "home-cedar-cottage", "home-tidepool-house", "home-maple-row", "home-north-dock-flat"
        }]
        assert len(future_homes) == 4
        assert len({(item["x"], item["y"]) for item in future_homes}) == 4
        assert all(item["x"] is not None and item["y"] is not None for item in future_homes)
        assert modern["poll"] is None
        assert modern["analytics"]["relationships"]["pairs"] > 0
        assert modern["analytics"]["inventoryByCategory"]
        stocked_property = next(item for item in modern["properties"] if item["inventoryItems"] > 0)
        assert stocked_property["inventoryUnits"] > 0
        property_detail = client.get(f"/api/v3/properties/{stocked_property['slug']}")
        assert property_detail.status_code == 200
        property_payload = property_detail.json()
        assert all(0 <= item["assetIndex"] < 452 for item in property_payload["inventory"])
        assert property_payload["capacity"] >= len(property_payload["residents"])
        assert modern["analytics"]["population"]["living"] == 12
        assert modern["analytics"]["population"]["target"] == 13
        assert modern["analytics"]["housing"]["capacity"] >= 32
        assert modern["residents"][0]["needsHighIsGood"] is True
        assert modern["residents"][0]["lifeStage"] in {"baby", "child", "teen", "adult", "senior"}
        detail = client.get(f"/api/v3/residents/{modern['residents'][0]['slug']}")
        assert detail.status_code == 200
        assert "finances" in detail.json()


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


def test_html_prevents_edge_script_injection(settings_factory) -> None:
    settings = settings_factory()
    settings.frontend_dir.mkdir(parents=True)
    (settings.frontend_dir / "index.html").write_text("<!doctype html><title>Krabville</title>", encoding="utf-8")
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, no-transform"


def test_empty_town_state_has_a_complete_public_schema(settings_factory) -> None:
    settings = settings_factory()
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        payload = client.get("/api/v2/state").json()
        assert payload["season"] is None
        assert payload["usage"]["calls"] == 0
        assert payload["models"]["primary"] == "gpt-5.3-codex-spark"
        assert payload["residents"] == payload["events"] == payload["goals"] == []
