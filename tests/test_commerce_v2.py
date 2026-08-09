from __future__ import annotations

from fastapi.testclient import TestClient

from krabville.api import create_app
from krabville.commerce_v2 import (
    _illicit_relationship_outcome,
    _story_event,
    claim_due_commitment,
    deterministic_commitment_outcome,
    deterministic_phone_outcome,
    household_funding_account,
    illicit_actor_candidates,
    move_market_prices,
    repair_dependent_finances,
    run_daily_commerce,
    run_phone_window,
    visible_purchase_candidates,
)
from krabville.db import dumps, initialize, loads
from krabville.runtime_v2 import account_balance, settle_daily_economy
from krabville.world import advance_tick, start_season


def test_everyday_economy_is_balanced_local_and_visible(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="93" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()

    assert connection.execute("SELECT COUNT(*) FROM item_catalog").fetchone()[0] >= 380
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
    shared_before_settlement = {
        int(row["id"]): account_balance(connection, int(row["id"]))
        for row in connection.execute(
            "SELECT id FROM financial_accounts WHERE household_id IS NOT NULL AND name='Household chequing'"
        )
    }
    business_before = {
        row["name"]: account_balance(connection, int(row["account_id"]))
        for row in connection.execute(
            """
            SELECT b.name,a.id account_id FROM businesses b JOIN financial_accounts a
              ON a.business_id=b.id AND a.name='Operating' AND a.status='open'
            """
        )
    }
    settlement = settle_daily_economy(connection, int(season["id"]), 0, 48)
    shared_after_settlement = {
        account_id: account_balance(connection, account_id) for account_id in shared_before_settlement
    }
    business_after = {
        row["name"]: account_balance(connection, int(row["account_id"]))
        for row in connection.execute(
            """
            SELECT b.name,a.id account_id FROM businesses b JOIN financial_accounts a
              ON a.business_id=b.id AND a.name='Operating' AND a.status='open'
            """
        )
    }
    assert settlement["businessIncome"] > 0
    assert settlement["businessPayroll"] > 0
    assert settlement["servicePurchases"] > 0
    assert settlement["categorizedTransactions"] > settlement["transactions"]
    assert settlement["rent"] > 0
    assert settlement["utilities"] > 0
    assert settlement["taxes"] > 0
    assert any(
        shared_after_settlement[account_id] != balance
        for account_id, balance in shared_before_settlement.items()
    )
    categories = {
        str(row[0]) for row in connection.execute(
            "SELECT DISTINCT category FROM financial_transactions WHERE season_id=? AND status='posted'",
            (season["id"],),
        )
    }
    assert {"wages", "taxes", "rent", "utilities", "debt", "investments"} <= categories
    assert connection.execute(
        "SELECT COUNT(*) FROM financial_transactions WHERE season_id=? AND category='daily_settlement' AND status='posted'",
        (season["id"],),
    ).fetchone()[0] == 0
    assert any(business_after[name] != balance for name, balance in business_before.items())
    household_before = {
        int(row["id"]): account_balance(connection, int(row["id"]))
        for row in connection.execute(
            "SELECT id FROM financial_accounts WHERE household_id IS NOT NULL AND name='Household chequing'"
        )
    }
    result = run_daily_commerce(connection, int(season["id"]), 0, 48)
    household_after = {
        account_id: account_balance(connection, account_id) for account_id in household_before
    }
    assert result["restocked"] >= 1
    assert result["pricesMoved"] > 0
    assert any(household_after[account_id] < balance for account_id, balance in household_before.items())
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
        assert payload["economy"]["medianNetWorth"] > 0
        for resident in payload["residents"]:
            detail = client.get(f"/api/v3/residents/{resident['slug']}")
            assert detail.status_code == 200
            assert "phone" in detail.json()
            assert "clothing" in detail.json()
            assert detail.json()["clothing"]
            assert "homeInventory" in detail.json()
            assert all(0 <= item["assetIndex"] < 452 for item in detail.json()["onPersonInventory"])
        dependent = next(resident for resident in payload["residents"] if resident["lifeStage"] in {"baby", "child"})
        assert dependent["care"]["state"] in {"covered", "institutional"}
        assert dependent["care"]["caregiver"]
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
    assert connection.execute(
        "SELECT COUNT(DISTINCT tick / 288) FROM life_events WHERE season_id=? AND household_id=? AND event_type='housing_arrears'",
        (season["id"], debtor["household_id"]),
    ).fetchone()[0] == 2
    assert connection.execute(
        "SELECT COUNT(DISTINCT tick / 288) FROM life_events WHERE season_id=? AND household_id=? AND event_type='housing_recovery_attempt' AND outcome='failed'",
        (season["id"], debtor["household_id"]),
    ).fetchone()[0] == 2
    recovery = connection.execute(
        "SELECT status,stage,arrears_days,failed_attempts FROM housing_recovery WHERE season_id=? AND household_id=?",
        (season["id"], debtor["household_id"]),
    ).fetchone()
    assert recovery["status"] == "active"
    assert recovery["stage"] == "sheltered"
    assert recovery["arrears_days"] == recovery["failed_attempts"] == 2
    assert run_daily_commerce(connection, int(season["id"]), 5, 5 * 288)["evictions"] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM life_events WHERE season_id=? AND event_type='eviction'",
        (season["id"],),
    ).fetchone()[0] == 1
    assert not list(connection.execute("PRAGMA foreign_key_check"))
    assert connection.execute("SELECT status FROM debts WHERE id=?", (debt_id,)).fetchone()[0] in {"defaulted", "forgiven"}
    connection.close()


def test_purchase_candidates_are_visible_diverse_and_non_mutating(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="98" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    household = connection.execute("SELECT id FROM households WHERE status='active' ORDER BY id LIMIT 1").fetchone()
    shared = connection.execute(
        "SELECT id FROM financial_accounts WHERE household_id=? AND name='Household chequing'",
        (household["id"],),
    ).fetchone()
    transactions_before = connection.execute("SELECT COUNT(*) FROM financial_transactions").fetchone()[0]

    assert household_funding_account(
        connection, int(household["id"]), required_cents=1_000
    ) == int(shared["id"])
    candidates = visible_purchase_candidates(
        connection,
        int(season["id"]),
        0,
        household_id=int(household["id"]),
        budget_cents=100_000,
        limit=12,
    )

    assert len(candidates) >= 4
    assert len({candidate["category"] for candidate in candidates}) >= 4
    assert all(candidate["priceCents"] <= 100_000 for candidate in candidates)
    assert all(candidate["reason"] and candidate["business"] for candidate in candidates)
    assert connection.execute("SELECT COUNT(*) FROM financial_transactions").fetchone()[0] == transactions_before
    connection.close()


def test_market_price_movement_is_deterministic_and_bounded(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="99" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    row = connection.execute(
        "SELECT business_id,item_id FROM business_inventory ORDER BY business_id,item_id LIMIT 1"
    ).fetchone()
    connection.execute(
        "UPDATE business_inventory SET quantity=0 WHERE business_id=? AND item_id=?",
        (row["business_id"], row["item_id"]),
    )
    before = {
        (int(item["business_id"]), int(item["item_id"])): int(item["price_cents"])
        for item in connection.execute("SELECT business_id,item_id,price_cents FROM business_inventory")
    }

    changed = move_market_prices(connection, int(season["id"]), 0, max_daily_change_bps=250)
    after = {
        (int(item["business_id"]), int(item["item_id"])): int(item["price_cents"])
        for item in connection.execute("SELECT business_id,item_id,price_cents FROM business_inventory")
    }

    assert changed > 0
    assert after[(int(row["business_id"]), int(row["item_id"]))] > before[(int(row["business_id"]), int(row["item_id"]))]
    for key, old_price in before.items():
        assert abs(after[key] - old_price) <= max(1, round(old_price * 0.025))
    connection.close()


def test_categorized_settlement_replay_is_idempotent_and_balanced(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="9b" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()

    first = settle_daily_economy(connection, int(season["id"]), 0, 48)
    transaction_count = int(connection.execute("SELECT COUNT(*) FROM financial_transactions").fetchone()[0])
    balances = {
        int(row["id"]): account_balance(connection, int(row["id"]))
        for row in connection.execute("SELECT id FROM financial_accounts")
    }
    debts = list(connection.execute("SELECT id,outstanding_cents,status FROM debts ORDER BY id"))
    investments = list(connection.execute("SELECT id,market_value_cents,updated_tick FROM investments ORDER BY id"))

    second = settle_daily_economy(connection, int(season["id"]), 0, 48)

    assert first["categorizedTransactions"] > 0
    assert second["transactions"] == 0
    assert second["categorizedTransactions"] == 0
    assert connection.execute("SELECT COUNT(*) FROM financial_transactions").fetchone()[0] == transaction_count
    assert {
        int(row["id"]): account_balance(connection, int(row["id"]))
        for row in connection.execute("SELECT id FROM financial_accounts")
    } == balances
    assert list(connection.execute("SELECT id,outstanding_cents,status FROM debts ORDER BY id")) == debts
    assert list(connection.execute("SELECT id,market_value_cents,updated_tick FROM investments ORDER BY id")) == investments
    assert not list(connection.execute(
        """
        SELECT t.id FROM financial_transactions t JOIN transaction_entries e ON e.transaction_id=t.id
        WHERE t.status='posted' GROUP BY t.id HAVING SUM(e.amount_cents)<>0
        """
    ))
    connection.close()


def test_phone_and_commitment_outcomes_are_deterministic(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="9c" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    residents = connection.execute(
        """
        SELECT r.id FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        WHERE l.alive=1 AND l.current_stage IN ('teen','adult','senior') ORDER BY r.id LIMIT 2
        """
    ).fetchall()
    caller_id, recipient_id = int(residents[0][0]), int(residents[1][0])
    seed = str(season["seed_hex"])
    phone_outcomes = {
        deterministic_phone_outcome(seed, tick, caller_id, recipient_id, "meetup", trust=0, tension=100)
        for tick in range(200)
    }
    assert {"completed", "declined"} <= phone_outcomes

    ids: dict[str, int] = {}
    for desired in ("complete", "reschedule", "forget"):
        ids[desired] = next(
            commitment_id for commitment_id in range(1_000, 5_000)
            if deterministic_commitment_outcome(seed, commitment_id, recipient_id, 100) == desired
            and commitment_id not in ids.values()
        )
    results: dict[str, object] = {}
    for desired, commitment_id in ids.items():
        communication_id = commitment_id + 10_000
        connection.execute(
            """
            INSERT INTO communications(
              id,season_id,tick,caller_resident_id,recipient_resident_id,channel,purpose,
              summary,visibility,status,duration_minutes,created_at
            ) VALUES(?,?,90,?,?,'call','meetup',?,'public','completed',5,'2026-01-01T00:00:00Z')
            """,
            (communication_id, season["id"], caller_id, recipient_id, f"{desired} test"),
        )
        connection.execute(
            """
            INSERT INTO communication_commitments(
              id,communication_id,resident_id,commitment_type,location,due_tick,status
            ) VALUES(?,?,?,'meetup','Town Square',100,'pending')
            """,
            (commitment_id, communication_id, recipient_id),
        )
        results[desired] = claim_due_commitment(
            connection, int(season["id"]), recipient_id, 100
        )

    complete = connection.execute(
        "SELECT status,completed_tick FROM communication_commitments WHERE id=?", (ids["complete"],)
    ).fetchone()
    rescheduled = connection.execute(
        "SELECT status,due_tick FROM communication_commitments WHERE id=?", (ids["reschedule"],)
    ).fetchone()
    forgotten = connection.execute(
        "SELECT status,completed_tick FROM communication_commitments WHERE id=?", (ids["forget"],)
    ).fetchone()
    assert results["complete"] and results["complete"]["outcome"] == "complete"
    assert complete["status"] == "completed" and complete["completed_tick"] == 100
    assert results["reschedule"] is None
    assert rescheduled["status"] == "pending" and int(rescheduled["due_tick"]) > 100
    assert results["forget"] is None
    assert forgotten["status"] == "missed" and forgotten["completed_tick"] == 100
    connection.close()


def test_phone_window_can_decline_without_creating_commitments(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="9d" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    connection.execute(
        "UPDATE resident_needs SET satisfaction=0 WHERE season_id=? AND need_key IN ('social','belonging')",
        (season["id"],),
    )
    connection.execute(
        "UPDATE relationships SET trust=0,tension=100 WHERE season_id=?",
        (season["id"],),
    )

    for tick in range(1, 241):
        if run_phone_window(connection, season, tick)["declined"]:
            break
    declined = connection.execute(
        "SELECT id,status FROM communications WHERE season_id=? AND status='declined' ORDER BY id LIMIT 1",
        (season["id"],),
    ).fetchone()

    assert declined and declined["status"] == "declined"
    assert connection.execute(
        "SELECT COUNT(*) FROM communication_commitments WHERE communication_id=?",
        (declined["id"],),
    ).fetchone()[0] == 0
    connection.close()


def test_illicit_actor_selection_uses_context_and_cooldown(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="9e" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    eligible = connection.execute(
        """
        SELECT r.id FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        WHERE l.alive=1 AND l.current_stage IN ('teen','adult','senior') ORDER BY r.id
        """
    ).fetchall()
    actor_id = int(eligible[-1][0])
    calm_traits = dumps({
        "risk": 0, "spontaneity": 0, "conscientiousness": 100,
        "agreeableness": 100, "empathy": 100,
    })
    pressured_traits = dumps({
        "risk": 100, "spontaneity": 100, "conscientiousness": 0,
        "agreeableness": 0, "empathy": 0,
    })
    connection.execute(
        "UPDATE residents SET traits_json=? WHERE id IN (%s)" % ",".join("?" for _ in eligible),
        (calm_traits, *(int(row[0]) for row in eligible)),
    )
    connection.execute("UPDATE residents SET traits_json=? WHERE id=?", (pressured_traits, actor_id))
    connection.execute(
        "UPDATE resident_season_state SET stress=0 WHERE season_id=?", (season["id"],)
    )
    connection.execute(
        "UPDATE resident_season_state SET stress=100 WHERE season_id=? AND resident_id=?",
        (season["id"], actor_id),
    )
    connection.execute(
        "UPDATE resident_needs SET satisfaction=95 WHERE season_id=?", (season["id"],)
    )
    connection.execute(
        "UPDATE resident_needs SET satisfaction=0 WHERE season_id=? AND resident_id=?",
        (season["id"], actor_id),
    )
    connection.execute(
        "UPDATE financial_accounts SET opening_balance_cents=500000 WHERE resident_id IS NOT NULL AND name='Personal chequing'"
    )
    connection.execute(
        "UPDATE financial_accounts SET opening_balance_cents=0 WHERE resident_id=? AND name='Personal chequing'",
        (actor_id,),
    )
    connection.execute(
        """
        UPDATE relationships SET trust=0,tension=100,resentment=100
        WHERE season_id=? AND (resident_a=? OR resident_b=?)
        """,
        (season["id"], actor_id, actor_id),
    )

    ranked = illicit_actor_candidates(connection, int(season["id"]), 0, 0)
    assert ranked[0]["residentId"] == actor_id
    assert ranked[0]["factors"]["traits"] > 90
    assert ranked[0]["factors"]["stress"] == 100
    assert ranked[0]["factors"]["needs"] == 100
    assert ranked[0]["factors"]["finances"] == 100
    assert ranked[0]["factors"]["opportunity"] > 0
    assert ranked[0]["factors"]["relationships"] > 0

    connection.execute(
        """
        INSERT INTO life_events(
          season_id,tick,event_type,subject_resident_id,title,summary,severity,created_at
        ) VALUES(?,10,'theft',?,'Cooldown fixture','Cooldown fixture',50,'2026-01-01T00:00:00Z')
        """,
        (season["id"], actor_id),
    )
    cooled = illicit_actor_candidates(connection, int(season["id"]), 1, 288)
    actor = next(candidate for candidate in cooled if candidate["residentId"] == actor_id)
    assert actor["onCooldown"] is True
    assert cooled[0]["residentId"] != actor_id
    connection.close()


def test_consensual_black_market_trade_does_not_receive_theft_penalties(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="9f" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    pairs = connection.execute(
        "SELECT resident_a,resident_b FROM relationships WHERE season_id=? ORDER BY resident_a,resident_b LIMIT 2",
        (season["id"],),
    ).fetchall()
    trade_pair, theft_pair = pairs
    for pair in pairs:
        connection.execute(
            """
            UPDATE relationships SET affinity=5,trust=40,tension=22,resentment=11
            WHERE season_id=? AND resident_a=? AND resident_b=?
            """,
            (season["id"], pair["resident_a"], pair["resident_b"]),
        )

    _illicit_relationship_outcome(
        connection, int(season["id"]), 100,
        int(trade_pair["resident_a"]), int(trade_pair["resident_b"]), "black_market",
    )
    _illicit_relationship_outcome(
        connection, int(season["id"]), 101,
        int(theft_pair["resident_a"]), int(theft_pair["resident_b"]), "theft",
    )
    trade = connection.execute(
        """
        SELECT affinity,trust,tension,resentment FROM relationships
        WHERE season_id=? AND resident_a=? AND resident_b=?
        """,
        (season["id"], trade_pair["resident_a"], trade_pair["resident_b"]),
    ).fetchone()
    theft = connection.execute(
        """
        SELECT affinity,trust,tension,resentment FROM relationships
        WHERE season_id=? AND resident_a=? AND resident_b=?
        """,
        (season["id"], theft_pair["resident_a"], theft_pair["resident_b"]),
    ).fetchone()
    assert tuple(trade) == (6, 41, 22, 11)
    assert tuple(theft) == (5, 34, 30, 18)
    connection.close()


def test_commerce_story_events_always_record_subject_and_related_participants(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="a0" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    residents = connection.execute("SELECT id FROM residents ORDER BY id LIMIT 2").fetchall()
    subject_id, related_id = int(residents[0][0]), int(residents[1][0])
    transaction_id = int(connection.execute(
        """
        INSERT INTO financial_transactions(
          season_id,tick,category,description,status,external_key,created_at
        ) VALUES(?,101,'test','Participant fixture','void','participant-fixture','2026-01-01T00:00:00Z')
        RETURNING id
        """,
        (season["id"],),
    ).fetchone()[0])
    _story_event(
        connection, int(season["id"]), 0, 100, "test_event",
        "Commerce participant plain", "Plain participant fixture",
        subject_id, related_id,
    )
    _story_event(
        connection, int(season["id"]), 0, 101, "test_transaction_event",
        "Commerce participant transaction", "Transaction participant fixture",
        subject_id, related_id, transaction_id=transaction_id,
    )

    missing = connection.execute(
        """
        SELECT sl.id FROM story_ledger sl
        JOIN life_events le ON le.season_id=sl.season_id AND le.tick=sl.tick
          AND le.event_type=sl.entry_type AND le.title=sl.headline
        WHERE sl.headline LIKE 'Commerce participant %' AND (
          (le.subject_resident_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM story_ledger_participants p
            WHERE p.ledger_id=sl.id AND p.resident_id=le.subject_resident_id AND p.role='subject'
          )) OR
          (le.related_resident_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM story_ledger_participants p
            WHERE p.ledger_id=sl.id AND p.resident_id=le.related_resident_id AND p.role='related'
          ))
        )
        """
    ).fetchall()
    assert missing == []
    transaction_story = connection.execute(
        """
        SELECT life_event_id,transaction_id FROM story_ledger
        WHERE headline='Commerce participant transaction'
        """
    ).fetchone()
    assert transaction_story["life_event_id"] is None
    assert transaction_story["transaction_id"] == transaction_id
    assert connection.execute(
        """
        SELECT COUNT(*) FROM story_ledger_participants p JOIN story_ledger sl ON sl.id=p.ledger_id
        WHERE sl.headline LIKE 'Commerce participant %'
        """
    ).fetchone()[0] == 4
    connection.close()


def test_dependent_care_keeps_a_caregiver_present_and_restores_needs_overnight(settings_factory) -> None:
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
        "UPDATE seasons SET current_tick=24,current_day=0,world_minutes=120 WHERE id=?",
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
    care_state = connection.execute(
        "SELECT care_state,current_caregiver_id FROM resident_season_state WHERE season_id=? AND resident_id=?",
        (season["id"], child["id"]),
    ).fetchone()
    assert care_state["care_state"] == "covered"
    assert care_state["current_caregiver_id"] == caregiver

    child_needs = loads(child_state["needs_json"], {})
    child_needs.update({"hunger": 90, "hygiene": 90})
    caregiver_needs = loads(connection.execute(
        "SELECT needs_json FROM resident_state WHERE season_id=? AND resident_id=?",
        (season["id"], caregiver),
    ).fetchone()[0], {})
    caregiver_needs["hunger"] = 0
    connection.execute(
        "UPDATE resident_state SET needs_json=? WHERE season_id=? AND resident_id=?",
        (dumps(child_needs), season["id"], child["id"]),
    )
    connection.execute(
        "UPDATE resident_state SET needs_json=?,activity='caring for a child at home' WHERE season_id=? AND resident_id=?",
        (dumps(caregiver_needs), season["id"], caregiver),
    )
    connection.execute(
        "UPDATE seasons SET current_tick=78,current_day=0,world_minutes=390 WHERE id=?",
        (season["id"],),
    )
    advance_tick(connection)
    self_care = connection.execute(
        "SELECT activity FROM resident_state WHERE season_id=? AND resident_id=?",
        (season["id"], caregiver),
    ).fetchone()[0]
    assert "meal" in self_care
    advance_tick(connection)
    recovered = connection.execute(
        "SELECT location,needs_json FROM resident_state WHERE season_id=? AND resident_id=?",
        (season["id"], caregiver),
    ).fetchone()
    assert recovered["location"] == child["home"]
    assert loads(recovered["needs_json"], {})["hunger"] > 0
    connection.close()


def test_school_care_places_children_inside_the_provider(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="97" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    child = connection.execute(
        """
        SELECT r.id,c.provider_business_id,b.name provider_name,
          COALESCE(p.map_location,p.name,'Krabville School') provider_location
        FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id AND l.current_stage='child'
        JOIN childcare_arrangements c ON c.child_resident_id=r.id AND c.status='active'
        JOIN businesses b ON b.id=c.provider_business_id
        LEFT JOIN properties p ON p.id=b.property_id
        ORDER BY r.id LIMIT 1
        """
    ).fetchone()
    assert child
    child_needs = loads(connection.execute(
        "SELECT needs_json FROM resident_state WHERE season_id=? AND resident_id=?",
        (season["id"], child["id"]),
    ).fetchone()[0], {})
    child_needs["social"] = 0
    connection.execute(
        "UPDATE resident_state SET needs_json=? WHERE season_id=? AND resident_id=?",
        (dumps(child_needs), season["id"], child["id"]),
    )
    connection.execute(
        "UPDATE seasons SET current_tick=108,current_day=0,world_minutes=540 WHERE id=?",
        (season["id"],),
    )
    advance_tick(connection)
    child_state = connection.execute(
        "SELECT activity,location FROM resident_state WHERE season_id=? AND resident_id=?",
        (season["id"], child["id"]),
    ).fetchone()
    care_state = connection.execute(
        "SELECT care_state,current_caregiver_id,current_care_provider_id FROM resident_season_state WHERE season_id=? AND resident_id=?",
        (season["id"], child["id"]),
    ).fetchone()
    assert child_state["location"] == child["provider_location"]
    assert child["provider_name"] in child_state["activity"]
    assert "socializing" in child_state["activity"]
    assert care_state["care_state"] == "institutional"
    assert care_state["current_caregiver_id"] is None
    assert care_state["current_care_provider_id"] == child["provider_business_id"]
    advance_tick(connection)
    recovered = loads(connection.execute(
        "SELECT needs_json FROM resident_state WHERE season_id=? AND resident_id=?",
        (season["id"], child["id"]),
    ).fetchone()[0], {})
    assert recovered["social"] > 0
    connection.close()


def test_dependents_are_not_billed_and_old_personal_debt_is_reversed(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="96" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    dependent = connection.execute(
        """
        SELECT r.id,r.name FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        WHERE l.current_stage IN ('baby','child') ORDER BY r.id LIMIT 1
        """
    ).fetchone()
    settle_daily_economy(connection, int(season["id"]), 0, 48)
    assert not connection.execute(
        "SELECT 1 FROM financial_transactions WHERE season_id=? AND external_key=?",
        (season["id"], f"settlement:0:resident:{dependent['id']}"),
    ).fetchone()

    loan = int(connection.execute(
        """
        INSERT INTO financial_accounts(
          resident_id,name,account_type,opening_balance_cents,opened_season_id,opened_tick
        ) VALUES(?,'Legacy dependent loan','loan',0,?,48) RETURNING id
        """,
        (dependent["id"], season["id"]),
    ).fetchone()[0])
    connection.execute(
        """
        INSERT INTO debts(
          borrower_account_id,debt_type,principal_cents,outstanding_cents,
          annual_rate_basis_points,minimum_payment_cents,opened_season_id,opened_tick,status
        ) VALUES(?,'credit',5802,5802,750,2500,?,48,'current')
        """,
        (loan, season["id"]),
    )
    clearing = int(connection.execute(
        """
        SELECT a.id FROM financial_accounts a JOIN businesses b ON b.id=a.business_id
        WHERE b.name='Krabville Credit Union' AND a.name='Operating'
        """
    ).fetchone()[0])
    transaction_id = int(connection.execute(
        """
        INSERT INTO financial_transactions(
          season_id,tick,category,description,status,external_key,created_at,posted_at
        ) VALUES(?,48,'daily_settlement','Legacy bad charge','posted','legacy-dependent-charge',
          '2026-01-01T00:00:00Z','2026-01-01T00:00:00Z') RETURNING id
        """,
        (season["id"],),
    ).fetchone()[0])
    connection.executemany(
        "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,?)",
        ((transaction_id, loan, -5802, "legacy debt"), (transaction_id, clearing, 5802, "legacy offset")),
    )

    assert repair_dependent_finances(connection) == 1
    assert account_balance(connection, loan) == 0
    assert connection.execute("SELECT status FROM financial_accounts WHERE id=?", (loan,)).fetchone()[0] == "closed"
    debt = connection.execute("SELECT status,outstanding_cents FROM debts WHERE borrower_account_id=?", (loan,)).fetchone()
    assert debt["status"] == "forgiven"
    assert debt["outstanding_cents"] == 0
    assert not list(connection.execute(
        """
        SELECT t.id FROM financial_transactions t JOIN transaction_entries e ON e.transaction_id=t.id
        WHERE t.status='posted' GROUP BY t.id HAVING SUM(e.amount_cents)<>0
        """
    ))
    connection.close()


def test_daily_settlement_reuses_a_closed_emergency_credit_account(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="97" * 32)
    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
    teen = connection.execute(
        """
        SELECT r.id FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        WHERE l.current_stage='teen' ORDER BY r.id LIMIT 1
        """
    ).fetchone()
    account_id = int(connection.execute(
        """
        INSERT INTO financial_accounts(
          resident_id,name,account_type,opening_balance_cents,status,
          opened_season_id,opened_tick,closed_season_id,closed_tick
        ) VALUES(?,'Emergency credit','loan',0,'closed',?,0,?,0) RETURNING id
        """,
        (teen["id"], season["id"], season["id"]),
    ).fetchone()[0])
    connection.execute(
        """
        INSERT INTO debts(
          borrower_account_id,debt_type,principal_cents,outstanding_cents,
          annual_rate_basis_points,minimum_payment_cents,opened_season_id,opened_tick,
          closed_season_id,closed_tick,status
        ) VALUES(?,'credit',5000,0,750,2500,?,0,?,0,'forgiven')
        """,
        (account_id, season["id"], season["id"]),
    )

    settle_daily_economy(connection, int(season["id"]), 0, 48)

    account = connection.execute(
        "SELECT id,status,closed_season_id,closed_tick FROM financial_accounts WHERE resident_id=? AND name='Emergency credit'",
        (teen["id"],),
    ).fetchone()
    assert account["id"] == account_id
    assert account["status"] == "open"
    assert account["closed_season_id"] is None
    assert account["closed_tick"] is None
    assert connection.execute(
        "SELECT COUNT(*) FROM financial_accounts WHERE resident_id=? AND name='Emergency credit'",
        (teen["id"],),
    ).fetchone()[0] == 1
    current = connection.execute(
        "SELECT outstanding_cents FROM debts WHERE borrower_account_id=? AND status='current'",
        (account_id,),
    ).fetchone()
    assert current and current["outstanding_cents"] > 0
    connection.close()
