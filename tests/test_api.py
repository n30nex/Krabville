from __future__ import annotations

from fastapi.testclient import TestClient

from krabville.api import create_app
from krabville.db import dumps, initialize, now_iso
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
        assert modern["release"]["version"]
        assert modern["release"]["commit"] == "unknown"
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
    initialize(settings).close()
    with TestClient(create_app(settings), base_url="http://evil.invalid") as client:
        assert client.get("/healthz").status_code == 400


def test_health_and_metrics_expose_runtime_freshness(settings_factory) -> None:
    settings = settings_factory(tick_stale_seconds=1)
    connection = initialize(settings)
    season_id = start_season(connection, seed_hex="74" * 32)["seasonId"]
    connection.execute(
        "UPDATE seasons SET started_at='2000-01-01T00:00:00+00:00' WHERE id=?",
        (season_id,),
    )
    connection.close()
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        assert client.get("/livez").status_code == 200
        assert client.get("/readyz").status_code == 200
        health = client.get("/healthz")
        assert health.status_code == 503
        assert health.json()["runtime"]["tickFreshness"]["stale"] is True
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "krabville_tick_stale 1" in metrics.text
        assert 'krabville_model_jobs{status="queued"}' in metrics.text


def test_html_prevents_edge_script_injection(settings_factory) -> None:
    settings = settings_factory()
    initialize(settings).close()
    settings.frontend_dir.mkdir(parents=True)
    (settings.frontend_dir / "index.html").write_text("<!doctype html><title>Krabville</title>", encoding="utf-8")
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store, no-transform"


def test_empty_town_state_has_a_complete_public_schema(settings_factory) -> None:
    settings = settings_factory()
    initialize(settings).close()
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        payload = client.get("/api/v2/state").json()
        assert payload["season"] is None
        assert payload["usage"]["calls"] == 0
        assert payload["models"]["primary"] == "gpt-5.3-codex-spark"
        assert payload["residents"] == payload["events"] == payload["goals"] == []
        assert payload["lifeGoals"] == []
        assert set(payload["eventKinds"]) == {
            "goal_change", "purchase", "health", "care_handoff", "housing",
            "relationship_change", "verified_chronicle",
        }
        assert payload["docket"]["entries"] == []
        assert payload["modelCircuits"]["summaryLabel"] == "Circuit telemetry unavailable"


def test_v22_public_read_fields_work_before_and_after_optional_migration(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="74" * 32)
    season_id = int(connection.execute("SELECT id FROM seasons WHERE number=1").fetchone()[0])
    for _ in range(25):
        advance_tick(connection)
    resident = connection.execute("SELECT id,slug FROM residents ORDER BY id LIMIT 1").fetchone()
    household = connection.execute(
        "SELECT household_id FROM household_members WHERE resident_id=? AND ended_season_id IS NULL",
        (resident["id"],),
    ).fetchone()
    goal = connection.execute(
        "SELECT id FROM goals WHERE season_id=? AND resident_id=? ORDER BY id LIMIT 1",
        (season_id, resident["id"]),
    ).fetchone()
    decision_id = connection.execute(
        """
        INSERT INTO decision_history(
          season_id,resident_id,tick,phase,chosen_action,chosen_destination,public_thought,
          confidence,utility_score,mood_before,mood_after,created_at
        ) VALUES(?, ?, 25, 'committed', 'visit_friend', 'Town Square',
          'A friend and the weather make the square appealing.', .82, 74, 'steady', 'hopeful', ?)
        RETURNING id
        """,
        (season_id, resident["id"], now_iso()),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO decision_options VALUES(?,1,'visit_friend','Town Square',74,28,1)",
        (decision_id,),
    )
    connection.execute(
        "INSERT INTO decision_factors VALUES(?,1,'relationship','friendship',18,'A trusted friend is nearby.')",
        (decision_id,),
    )
    connection.execute(
        "UPDATE resident_season_state SET current_decision_id=?,decision_state='committed' WHERE season_id=? AND resident_id=?",
        (decision_id, season_id, resident["id"]),
    )
    ledger_id = connection.execute(
        """
        INSERT INTO story_ledger(
          season_id,tick,day,entry_type,headline,summary,significance,visibility,created_at,phase
        ) VALUES(?,25,6,'epilogue','A verified week-end record','The named resident completed a real action.',
          80,'public',?,'epilogue') RETURNING id
        """,
        (season_id, now_iso()),
    ).fetchone()[0]
    connection.execute(
        "INSERT INTO story_ledger_participants VALUES(?,?, 'subject')",
        (ledger_id, resident["id"]),
    )
    connection.execute(
        """
        INSERT INTO daily_chronicles(
          season_id,day,title,narrative,statistics_json,created_at,source,verified,ledger_ids_json
        ) VALUES(?,0,'Day 1','Only verified ledger facts.',?,?,'ledger_local',1,?)
        """,
        (season_id, dumps({"ledgerEntries": 1}), now_iso(), dumps([ledger_id])),
    )
    connection.execute(
        "UPDATE goals SET progress=15,evidence_json=? WHERE id=?",
        (dumps({"activityIds": [1], "commitmentIds": []}), goal["id"]),
    )
    activity_id = connection.execute(
        """
        INSERT INTO activities(season_id,tick,resident_id,kind,summary,location,source,created_at)
        VALUES(?,25,?,'pursue_purpose','Made verifiable progress on a long-term goal.',
          'Town Square','utility-v2',?) RETURNING id
        """,
        (season_id, resident["id"], now_iso()),
    ).fetchone()[0]
    life_goal = connection.execute(
        "SELECT id FROM life_goals WHERE resident_id=? ORDER BY id LIMIT 1",
        (resident["id"],),
    ).fetchone()
    connection.execute(
        "UPDATE life_goals SET progress=22,evidence_json=? WHERE id=?",
        (dumps([{"seasonId": season_id, "activityId": activity_id, "action": "pursue_purpose", "tick": 25}]), life_goal["id"]),
    )
    connection.execute(
        """
        INSERT INTO health_conditions(
          resident_id,condition_key,name,condition_type,severity,status,contagious,onset_season_id,
          onset_tick,treatment_cost_cents
        ) VALUES(?,'sprain','Sprained wrist','injury',24,'recovering',0,?,25,4500)
        """,
        (resident["id"], season_id),
    )
    housing_columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(housing_recovery)")
    }
    if not housing_columns:
        connection.execute(
            """
            CREATE TABLE housing_recovery(
              id INTEGER PRIMARY KEY,season_id INTEGER,household_id INTEGER,resident_id INTEGER,
              status TEXT,stage TEXT,stable_days INTEGER,next_step TEXT
            )
            """
        )
        housing_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(housing_recovery)")
        }
    housing_values = {
        "id": 1, "season_id": season_id, "household_id": household["household_id"],
        "resident_id": resident["id"], "status": "active", "stage": "repayment",
        "arrears_days": 1, "failed_attempts": 1, "stable_days": 2,
        "next_step": "Review a new rental", "opened_tick": 25, "updated_tick": 25,
    }
    insert_columns = [name for name in housing_values if name in housing_columns]
    connection.execute(
        f"INSERT INTO housing_recovery({','.join(insert_columns)}) VALUES({','.join('?' for _ in insert_columns)})",
        tuple(housing_values[name] for name in insert_columns),
    )
    connection.execute(
        """
        INSERT INTO model_circuits(
          season_id,day,job_kind,model,status,consecutive_failures,opened_at,updated_at
        ) VALUES(?,0,'chronicle','gpt-5.3-codex-spark','open',2,?,?)
        """,
        (season_id, now_iso(), now_iso()),
    )
    poll = connection.execute("SELECT id FROM polls WHERE season_id=?", (season_id,)).fetchone()
    option = connection.execute(
        "SELECT id FROM poll_options WHERE poll_id=? ORDER BY id LIMIT 1", (poll["id"],)
    ).fetchone()
    connection.execute(
        "UPDATE polls SET status='closed',winner_option_id=?,selection_source='town' WHERE id=?", (option["id"], poll["id"])
    )
    event_kinds = (
        "goal_change", "purchase", "health", "care_handoff", "housing",
        "relationship_change", "verified_chronicle",
    )
    connection.executemany(
        "INSERT INTO event_stream(season_id,tick,event_type,payload_json,created_at) VALUES(?,25,?,?,?)",
        [(season_id, kind, dumps({"summary": f"{kind} public update"}), now_iso()) for kind in event_kinds],
    )
    connection.commit()
    connection.close()

    with TestClient(create_app(settings), base_url="http://testserver") as client:
        payload = client.get("/api/v3/state").json()
        assert payload["schemaVersion"] == 3
        assert payload["docket"]["source"] == "authoritative-ledger"
        assert payload["ledgerVerification"]["verified"] == 1
        assert payload["ledgerVerification"]["participantLinks"] == 1
        assert payload["epilogues"][0]["phase"] == "epilogue"
        assert payload["goalEvidence"][0]["summary"] == "1 recorded activity"
        public_life_goal = next(item for item in payload["lifeGoals"] if item["resident"] == resident["slug"])
        assert public_life_goal["progress"] == 22
        assert public_life_goal["evidence"][0]["verified"] is True
        assert public_life_goal["evidence"][0]["summary"] == "Made verifiable progress on a long-term goal."
        assert payload["healthConditions"][0]["status"] == "recovering"
        assert payload["healthConditions"][0]["statusLabel"] == "Recovering"
        assert payload["healthConditions"][0]["severityLabel"] == "Mild"
        assert payload["housingRecovery"]["available"] is True
        assert payload["housingRecovery"]["plans"][0]["stageLabel"] == "Repayment"
        assert payload["modelCircuits"]["circuits"][0]["status"] == "open"
        assert payload["modelCircuits"]["circuits"][0]["statusLabel"] == "Fallback route active"
        assert set(payload["economy"]["indicators"]) >= {
            "residentMedianWealth", "disposableIncome", "cpi", "retailVolume",
            "businessRevenue", "businessProfit", "employmentRate", "debtDelinquencyRate",
            "shelterOccupancy", "wealthGini",
        }
        assert payload["poll"]["totalVotes"] == 0
        assert payload["poll"]["selectionSource"] == "town"
        assert payload["poll"]["winnerLabel"] == "Town selected"
        public_resident = next(item for item in payload["residents"] if item["slug"] == resident["slug"])
        assert public_resident["decisionFactors"][0]["key"] == "friendship"
        detail = client.get(f"/api/v3/residents/{resident['slug']}").json()
        assert detail["goalEvidence"][0]["verified"] is True
        assert detail["lifeGoals"][0]["evidenceCount"] == 1
        assert detail["lifeGoals"][0]["evidence"][0]["goalScope"] == "life"
        assert detail["health"]["conditionDetails"][0]["name"] == "Sprained wrist"
        assert detail["health"]["status"] == "Recovering"
        assert detail["housingRecovery"]["plans"][0]["stableDays"] == 2
        assert detail["housingRecovery"]["recoveryLabel"] == "Repayment"
        public_events = client.get("/api/v3/events?after=0&limit=500").json()
        assert set(event_kinds).issubset({item["type"] for item in public_events["events"]})
        assert set(event_kinds) == set(public_events["eventKinds"])
        archive = client.get(f"/api/v3/seasons/{season_id}").json()
        assert archive["ledgerVerification"]["verified"] == 1
        assert archive["epilogues"][0]["title"] == "A verified week-end record"
        legacy = client.get("/api/krabville/state").json()
        assert legacy["simulation"] == "krabville-v2"
        posts = {
            path
            for path, methods in client.get("/openapi.json").json()["paths"].items()
            if "post" in methods
        }
        assert posts == {"/api/v2/polls/{poll_id}/vote", "/api/v3/polls/{poll_id}/vote"}
