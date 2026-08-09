from __future__ import annotations

from krabville.db import initialize, loads
from krabville.world import (
    _advance_health_conditions,
    _begin_health_treatment,
    _dramatic_life_event,
    advance_tick,
    start_season,
)


def test_live_decisions_store_real_context_and_persistent_wants(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="ab" * 32)
    for _ in range(30):
        advance_tick(connection)

    factor_kinds = {
        str(row[0]) for row in connection.execute("SELECT DISTINCT factor_kind FROM decision_factors")
    }
    assert {"need", "schedule", "trait", "inventory"} <= factor_kinds
    assert connection.execute(
        "SELECT COUNT(*) FROM resident_wants WHERE source_need IS NOT NULL AND action_key IS NOT NULL"
    ).fetchone()[0] > 0
    connection.close()


def test_accident_creates_condition_and_treatment_drives_recovery(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="02" * 32)
    season = connection.execute("SELECT * FROM seasons WHERE number=1").fetchone()
    _dramatic_life_event(connection, season, 0, 228)

    condition = connection.execute("SELECT * FROM health_conditions").fetchone()
    assert condition["condition_type"] == "injury"
    assert condition["status"] == "active"
    before = int(condition["severity"])
    treated = _begin_health_treatment(
        connection, int(season["id"]), int(condition["resident_id"]), 229,
    )
    assert treated and treated[0]["treatmentCostCents"] > 0
    _advance_health_conditions(connection, season, 1, 288)
    after = connection.execute(
        "SELECT severity,status FROM health_conditions WHERE id=?", (condition["id"],)
    ).fetchone()
    assert int(after["severity"]) < before
    assert after["status"] in {"recovering", "resolved"}
    assert connection.execute(
        "SELECT COUNT(*) FROM event_stream WHERE event_type='health'"
    ).fetchone()[0] >= 2
    connection.close()


def test_romance_is_adult_safe_and_moves_durable_relationship_dimensions(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="03" * 32)
    season = connection.execute("SELECT * FROM seasons WHERE number=1").fetchone()
    _dramatic_life_event(connection, season, 0, 228)

    event = connection.execute("SELECT * FROM life_events").fetchone()
    assert event["event_type"] == "romance"
    stages = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT lifecycle.current_stage FROM life_event_participants participant
            JOIN resident_lifecycle lifecycle ON lifecycle.resident_id=participant.resident_id
            WHERE participant.life_event_id=?
            """,
            (event["id"],),
        )
    }
    assert stages <= {"adult", "senior"}
    ledger_id = connection.execute(
        "SELECT id FROM story_ledger WHERE life_event_id=?", (event["id"],)
    ).fetchone()[0]
    assert connection.execute(
        "SELECT COUNT(DISTINCT resident_id) FROM story_ledger_participants WHERE ledger_id=?",
        (ledger_id,),
    ).fetchone()[0] == 2
    relationship = connection.execute(
        "SELECT * FROM relationships WHERE season_id=? AND attraction>0 ORDER BY attraction DESC LIMIT 1",
        (season["id"],),
    ).fetchone()
    assert relationship["affection"] > 0
    assert relationship["respect"] > 0
    assert relationship["commitment"] > 0
    payload = connection.execute(
        "SELECT payload_json FROM event_stream WHERE event_type='relationship_change' ORDER BY seq DESC LIMIT 1"
    ).fetchone()[0]
    assert loads(payload, {})["cause"] == "romance"
    connection.close()
