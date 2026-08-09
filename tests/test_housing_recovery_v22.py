from __future__ import annotations

from krabville.commerce_v2 import (
    evaluate_eviction_policy,
    housing_recovery_status,
    record_housing_settlement,
)
from krabville.db import initialize
from krabville.world import start_season


def test_eviction_requires_repeated_arrears_and_failed_recovery() -> None:
    assert not evaluate_eviction_policy(
        housing_arrears_days=1,
        failed_recovery_attempts=2,
        season_evictions=0,
    )["eligible"]
    assert not evaluate_eviction_policy(
        housing_arrears_days=2,
        failed_recovery_attempts=1,
        season_evictions=0,
    )["eligible"]
    assert evaluate_eviction_policy(
        housing_arrears_days=2,
        failed_recovery_attempts=2,
        season_evictions=0,
    )["eligible"]
    capped = evaluate_eviction_policy(
        housing_arrears_days=4,
        failed_recovery_attempts=4,
        season_evictions=1,
    )
    assert not capped["eligible"]
    assert "season eviction limit reached" in capped["reasons"]


def test_shelter_rehousing_unlocks_after_two_stable_settlements(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="9a" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    household = connection.execute(
        """
        SELECT h.id,MIN(hm.resident_id) subject_id FROM households h
        JOIN household_members hm ON hm.household_id=h.id AND hm.ended_season_id IS NULL
        WHERE h.status='active' GROUP BY h.id ORDER BY h.id LIMIT 1
        """
    ).fetchone()
    occupancy = connection.execute(
        "SELECT id FROM property_occupancy WHERE household_id=? AND ended_season_id IS NULL",
        (household["id"],),
    ).fetchone()
    shelter_id = connection.execute("SELECT id FROM properties WHERE slug='harbour-shelter'").fetchone()[0]
    connection.execute(
        "UPDATE property_occupancy SET ended_season_id=?,ended_tick=288,end_reason='test' WHERE id=?",
        (season["id"], occupancy["id"]),
    )
    connection.execute(
        """
        INSERT INTO property_occupancy(
          property_id,household_id,occupancy_type,monthly_cost_cents,started_season_id,started_tick
        ) VALUES(?,?,'emergency',0,?,288)
        """,
        (shelter_id, household["id"], season["id"]),
    )
    connection.execute(
        """
        INSERT INTO life_events(
          season_id,tick,event_type,subject_resident_id,household_id,title,summary,outcome,severity,created_at
        ) VALUES(?,288,'eviction',?,?,'Test eviction','Test eviction','evicted',80,'2026-01-01T00:00:00Z')
        """,
        (season["id"], household["subject_id"], household["id"]),
    )

    first = housing_recovery_status(connection, int(household["id"]), season_id=int(season["id"]))
    assert first["sheltered"]
    assert not first["rehousingEligible"]
    first_stable = record_housing_settlement(
        connection, int(season["id"]), 2, 2 * 288, int(household["id"]), stable=True
    )
    assert first_stable["sheltered"]
    assert first_stable["stableSettlements"] == 1
    assert not first_stable["rehousingEligible"]

    second_stable = record_housing_settlement(
        connection, int(season["id"]), 3, 3 * 288, int(household["id"]), stable=True
    )
    assert not second_stable["sheltered"]
    assert second_stable["stableSettlements"] == 2
    assert second_stable["recoveryStatus"] == "rehoused"
    new_home = connection.execute(
        """
        SELECT p.id,p.slug,p.resident_capacity FROM property_occupancy po
        JOIN properties p ON p.id=po.property_id
        WHERE po.household_id=? AND po.ended_season_id IS NULL
        """,
        (household["id"],),
    ).fetchone()
    assert new_home["slug"] != "harbour-shelter"
    occupied = connection.execute(
        """
        SELECT COUNT(hm.resident_id) FROM property_occupancy po
        JOIN household_members hm ON hm.household_id=po.household_id AND hm.ended_season_id IS NULL
        WHERE po.property_id=? AND po.ended_season_id IS NULL
        """,
        (new_home["id"],),
    ).fetchone()[0]
    assert occupied <= new_home["resident_capacity"]
    recovery = connection.execute(
        "SELECT status,stage,stable_days,resolved_tick FROM housing_recovery WHERE season_id=? AND household_id=?",
        (season["id"], household["id"]),
    ).fetchone()
    assert tuple(recovery[:3]) == ("rehoused", "housed", 2)
    assert recovery["resolved_tick"] == 3 * 288

    assert not list(connection.execute("PRAGMA foreign_key_check"))
    connection.close()
