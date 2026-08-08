from __future__ import annotations

from fastapi.testclient import TestClient

from krabville.api import create_app
from krabville.commerce_v2 import run_daily_commerce, run_phone_window
from krabville.db import dumps, initialize, loads
from krabville.world import advance_tick, start_season


def test_everyday_economy_is_balanced_local_and_visible(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="93" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()

    assert connection.execute("SELECT COUNT(*) FROM item_catalog").fetchone()[0] >= 180
    assert connection.execute("SELECT COUNT(*) FROM resident_phones").fetchone()[0] == connection.execute(
        "SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1 AND current_stage IN ('teen','adult','senior')"
    ).fetchone()[0]
    assert connection.execute(
        """
        SELECT COUNT(*) FROM resident_phones p JOIN resident_lifecycle l ON l.resident_id=p.resident_id
        WHERE l.current_stage IN ('baby','child')
        """
    ).fetchone()[0] == 0

    stock = connection.execute(
        """
        SELECT bi.business_id,bi.item_id FROM business_inventory bi
        JOIN businesses b ON b.id=bi.business_id WHERE b.name='Lagoon General Store' ORDER BY bi.item_id LIMIT 1
        """
    ).fetchone()
    connection.execute(
        "UPDATE business_inventory SET quantity=0 WHERE business_id=? AND item_id=?",
        (stock["business_id"], stock["item_id"]),
    )
    model_jobs = connection.execute("SELECT COUNT(*) FROM model_jobs").fetchone()[0]
    result = run_daily_commerce(connection, int(season["id"]), 0, 48)
    assert result["restocked"] >= 1
    assert connection.execute(
        "SELECT quantity FROM business_inventory WHERE business_id=? AND item_id=?",
        (stock["business_id"], stock["item_id"]),
    ).fetchone()[0] > 0
    assert connection.execute("SELECT COUNT(*) FROM model_jobs").fetchone()[0] == model_jobs
    assert not list(connection.execute(
        """
        SELECT t.id,SUM(e.amount_cents) total FROM financial_transactions t
        JOIN transaction_entries e ON e.transaction_id=t.id WHERE t.status='posted'
        GROUP BY t.id HAVING total<>0
        """
    ))

    calls = run_phone_window(connection, season, 108)
    assert calls["calls"] >= 1
    assert connection.execute("SELECT COUNT(*) FROM communications").fetchone()[0] >= 1
    assert connection.execute("SELECT COUNT(*) FROM model_jobs").fetchone()[0] == model_jobs

    for _ in range(3):
        advance_tick(connection)
    sleeping = connection.execute(
        "SELECT COUNT(*) FROM resident_state WHERE activity LIKE 'sleeping%' AND location<>''"
    ).fetchone()[0]
    assert sleeping == 12
    connection.close()

    with TestClient(create_app(settings), base_url="http://testserver") as client:
        state = client.get("/api/v3/state")
        assert state.status_code == 200
        payload = state.json()
        assert all(resident["indoors"] for resident in payload["residents"])
        assert all(resident["building"] for resident in payload["residents"])
        assert payload["economy"]["stockUnits"] > 0
        for resident in payload["residents"]:
            detail = client.get(f"/api/v3/residents/{resident['slug']}")
            assert detail.status_code == 200
            assert "phone" in detail.json()
            assert "homeInventory" in detail.json()
        home = next(item for item in payload["properties"] if item["type"] in {"house", "apartment"} and item["inside"])
        detail = client.get(f"/api/v3/properties/{home['slug']}")
        assert detail.status_code == 200
        assert detail.json()["residents"]
        assert client.get("/api/v3/economy").status_code == 200


def test_default_can_repossess_and_move_a_household_to_safety(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="94" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    debtor = connection.execute(
        """
        SELECT r.id resident_id,hm.household_id,r.name
        FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id AND l.current_stage='adult'
        JOIN household_members hm ON hm.resident_id=r.id AND hm.ended_season_id IS NULL
        ORDER BY r.id LIMIT 1
        """
    ).fetchone()
    chequing = connection.execute(
        "SELECT id FROM financial_accounts WHERE resident_id=? AND name='Personal chequing'",
        (debtor["resident_id"],),
    ).fetchone()[0]
    connection.execute("UPDATE financial_accounts SET opening_balance_cents=0 WHERE id=?", (chequing,))
    loan = connection.execute(
        "INSERT INTO financial_accounts(resident_id,name,account_type,opening_balance_cents,opened_tick) VALUES(?,'Test loan','loan',0,0) RETURNING id",
        (debtor["resident_id"],),
    ).fetchone()[0]
    debt_id = connection.execute(
        """
        INSERT INTO debts(
          borrower_account_id,debt_type,principal_cents,outstanding_cents,
          annual_rate_basis_points,minimum_payment_cents,opened_tick,status
        ) VALUES(?,'loan',3000000,3000000,800,60000,0,'late') RETURNING id
        """,
        (loan,),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO life_events(season_id,tick,event_type,subject_resident_id,title,summary,severity,created_at)
        VALUES(?,0,'debt_late',?,'Test arrears','Test arrears',50,'2026-01-01T00:00:00Z')
        """,
        (season["id"], debtor["resident_id"]),
    )

    day_three = run_daily_commerce(connection, int(season["id"]), 3, 3 * 288)
    assert day_three["defaults"] >= 1
    assert day_three["repossessions"] == 1
    day_four = run_daily_commerce(connection, int(season["id"]), 4, 4 * 288)
    assert day_four["evictions"] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM residents WHERE home='Harbour Shelter' AND id IN (SELECT resident_id FROM household_members WHERE household_id=?)",
        (debtor["household_id"],),
    ).fetchone()[0] >= 1
    assert connection.execute(
        """
        SELECT p.slug FROM property_occupancy po JOIN properties p ON p.id=po.property_id
        WHERE po.household_id=? AND po.ended_season_id IS NULL
        """,
        (debtor["household_id"],),
    ).fetchone()[0] == "harbour-shelter"
    assert not list(connection.execute("PRAGMA foreign_key_check"))
    assert connection.execute("SELECT status FROM debts WHERE id=?", (debt_id,)).fetchone()[0] in {"defaulted", "forgiven"}
    connection.close()


def test_dependent_care_keeps_a_caregiver_present_and_restores_needs(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="95" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    child = connection.execute(
        """
        SELECT r.id,r.home,c.caregiver_resident_id FROM residents r
        JOIN resident_lifecycle l ON l.resident_id=r.id AND l.current_stage='baby'
        JOIN childcare_arrangements c ON c.child_resident_id=r.id AND c.status='active'
        ORDER BY r.id LIMIT 1
        """
    ).fetchone()
    caregiver = int(child["caregiver_resident_id"])
    needs = loads(connection.execute(
        "SELECT needs_json FROM resident_state WHERE season_id=? AND resident_id=?",
        (season["id"], child["id"]),
    ).fetchone()[0], {})
    needs["hunger"] = 0
    connection.execute(
        "UPDATE resident_state SET needs_json=?,activity='having a bottle with a caregiver' WHERE season_id=? AND resident_id=?",
        (dumps(needs), season["id"], child["id"]),
    )
    connection.execute(
        "UPDATE resident_state SET location='Lagoon Clinic',activity='working a shift',path_json='[]' WHERE season_id=? AND resident_id=?",
        (season["id"], caregiver),
    )
    connection.execute(
        "UPDATE seasons SET current_tick=108,current_day=0,world_minutes=540 WHERE id=?",
        (season["id"],),
    )
    advance_tick(connection)

    child_state = connection.execute(
        "SELECT activity,location,needs_json FROM resident_state WHERE season_id=? AND resident_id=?",
        (season["id"], child["id"]),
    ).fetchone()
    caregiver_state = connection.execute(
        "SELECT activity,location,path_json FROM resident_state WHERE season_id=? AND resident_id=?",
        (season["id"], caregiver),
    ).fetchone()
    assert child_state["location"] == caregiver_state["location"] == child["home"]
    assert "bottle" in child_state["activity"]
    assert "feeding" in caregiver_state["activity"]
    assert loads(child_state["needs_json"], {})["hunger"] > 0
    assert caregiver_state["path_json"] == "[]"
    assert connection.execute(
        "SELECT status FROM employment WHERE resident_id=? ORDER BY id DESC LIMIT 1", (caregiver,)
    ).fetchone()[0] == "leave"
    assert connection.execute(
        "SELECT care_state FROM resident_season_state WHERE season_id=? AND resident_id=?",
        (season["id"], child["id"]),
    ).fetchone()[0] == "covered"
    connection.close()
