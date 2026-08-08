from __future__ import annotations

from collections import Counter
import hashlib
import json
import sqlite3

from krabville.db import initialize, loads
from krabville.population_v2 import MAX_ADULTS, MAX_LIVING
from krabville.simulation_v2 import NEED_NAMES
from krabville.world import DAYS_PER_SEASON, TARGET_TICKS, TICKS_PER_DAY, advance_tick, start_season


SEEDS = ("17" * 32, "18" * 32, "19" * 32, "20" * 32)
DRAMA_TYPES = {
    "argument",
    "romance",
    "gossip",
    "financial_trouble",
    "career_change",
    "illness",
    "betrayal",
    "reconciliation",
    "accident",
    "friendship",
}


def _population_counts(connection: sqlite3.Connection) -> tuple[int, int]:
    living, adults = connection.execute(
        """
        SELECT COUNT(*),COALESCE(SUM(current_stage IN ('adult','senior')),0)
        FROM resident_lifecycle WHERE alive=1
        """
    ).fetchone()
    assert living <= MAX_LIVING
    assert adults <= MAX_ADULTS
    return int(living), int(adults)


def _finish_naturally(connection: sqlite3.Connection, season_id: int) -> None:
    connection.execute(
        """
        UPDATE seasons SET current_tick=?,current_day=?,world_minutes=? WHERE id=?
        """,
        (TARGET_TICKS - 1, DAYS_PER_SEASON - 1, 23 * 60 + 50, season_id),
    )
    result = advance_tick(connection)
    assert result == {"advanced": True, "status": "complete", "tick": TARGET_TICKS}
    season = connection.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
    assert season["completion_reason"] == "natural"
    assert season["seed_revealed"] == 1
    assert season["model_locked"] == 1


def _stable_digests(connection: sqlite3.Connection) -> dict[str, str]:
    queries = {
        "population": """
            SELECT r.slug,r.name,r.traits_json,i.family_name,i.appearance_key,
                   l.current_stage,l.seasons_in_stage,l.alive,l.death_cause
            FROM residents r JOIN resident_identities i ON i.resident_id=r.id
            JOIN resident_lifecycle l ON l.resident_id=r.id ORDER BY r.slug
        """,
        "decisions": """
            SELECT s.number,r.slug,d.tick,d.phase,d.chosen_action,d.chosen_destination,
                   d.public_thought,d.utility_score,d.committed_tick,d.resolved_tick
            FROM decision_history d JOIN seasons s ON s.id=d.season_id
            JOIN residents r ON r.id=d.resident_id ORDER BY s.number,d.tick,r.slug,d.id
        """,
        "polls": """
            SELECT s.number,p.day,p.status,o.choice_id,o.event_slug,o.category,o.votes,
                   o.id=p.winner_option_id
            FROM polls p JOIN seasons s ON s.id=p.season_id
            JOIN poll_options o ON o.poll_id=p.id ORDER BY s.number,p.day,o.choice_id
        """,
        "economy": """
            SELECT s.number,t.tick,t.category,t.external_key,a.name,e.amount_cents,e.memo
            FROM financial_transactions t JOIN seasons s ON s.id=t.season_id
            LEFT JOIN transaction_entries e ON e.transaction_id=t.id
            LEFT JOIN financial_accounts a ON a.id=e.account_id
            ORDER BY s.number,t.tick,t.external_key,e.id
        """,
        "story": """
            SELECT s.number,l.tick,l.entry_type,l.headline,l.summary,l.significance,l.visibility
            FROM story_ledger l JOIN seasons s ON s.id=l.season_id
            ORDER BY s.number,l.tick,l.id
        """,
        "needs": """
            SELECT s.number,r.slug,n.need_key,n.satisfaction,n.trend,n.updated_tick
            FROM resident_needs n JOIN seasons s ON s.id=n.season_id
            JOIN residents r ON r.id=n.resident_id
            ORDER BY s.number,r.slug,n.need_key
        """,
        "relationships": """
            SELECT s.number,a.slug,b.slug,x.affinity,x.trust,x.tension,x.familiarity,
                   x.attraction,x.affection,x.commitment,x.resentment,x.interactions
            FROM relationships x JOIN seasons s ON s.id=x.season_id
            JOIN residents a ON a.id=x.resident_a JOIN residents b ON b.id=x.resident_b
            ORDER BY s.number,a.slug,b.slug
        """,
    }
    return {
        name: hashlib.sha256(
            json.dumps([tuple(row) for row in connection.execute(query)], separators=(",", ":")).encode()
        ).hexdigest()
        for name, query in queries.items()
    }


def _run_scenario(settings) -> dict[str, str]:
    connection = initialize(settings)
    first = start_season(connection, seed_hex=SEEDS[0])
    first_id = int(first["seasonId"])

    stages = Counter(
        row[0]
        for row in connection.execute(
            "SELECT current_stage FROM resident_lifecycle WHERE alive=1"
        )
    )
    assert stages == Counter({"adult": 8, "child": 2, "baby": 1, "teen": 1})
    assert _population_counts(connection) == (12, 8)
    assert connection.execute("SELECT COUNT(*) FROM childcare_arrangements").fetchone()[0] == 4
    housing = connection.execute(
        """
        SELECT COALESCE(SUM(resident_capacity),0) capacity,
          SUM(CASE WHEN status='available' THEN 1 ELSE 0 END) available_homes
        FROM properties WHERE property_type IN ('house','apartment')
        """
    ).fetchone()
    assert housing["capacity"] >= 32
    assert housing["available_homes"] >= 4

    need_rows = list(connection.execute(
        "SELECT resident_id,need_key,satisfaction FROM resident_needs WHERE season_id=?",
        (first_id,),
    ))
    assert len(need_rows) == 12 * len(NEED_NAMES)
    assert all(0 <= row["satisfaction"] <= 100 for row in need_rows)
    assert all(
        {row["need_key"] for row in need_rows if row["resident_id"] == resident_id}
        == set(NEED_NAMES)
        for resident_id in {row["resident_id"] for row in need_rows}
    )

    observed = connection.execute(
        "SELECT resident_id,needs_json FROM resident_state WHERE season_id=? ORDER BY resident_id LIMIT 1",
        (first_id,),
    ).fetchone()
    hunger_before = loads(observed["needs_json"], {})["hunger"]
    assert advance_tick(connection)["tick"] == 1
    hunger_after = loads(
        connection.execute(
            "SELECT needs_json FROM resident_state WHERE season_id=? AND resident_id=?",
            (first_id, observed["resident_id"]),
        ).fetchone()[0],
        {},
    )["hunger"]
    assert hunger_after < hunger_before
    pondering = list(connection.execute(
        """
        SELECT d.id,d.phase,d.tick,d.committed_tick,v.decision_state,COUNT(o.option_rank) option_count
        FROM decision_history d JOIN resident_season_state v
          ON v.season_id=d.season_id AND v.resident_id=d.resident_id
        JOIN decision_options o ON o.decision_id=d.id
        WHERE d.season_id=? GROUP BY d.id ORDER BY d.id
        """,
        (first_id,),
    ))
    assert len(pondering) == 12
    assert all(
        row["phase"] == "pondering"
        and row["decision_state"] == "pondering"
        and row["tick"] == 0
        and row["committed_tick"] is None
        and row["option_count"] == 3
        for row in pondering
    )
    assert advance_tick(connection)["tick"] == 2
    committed = list(connection.execute(
        "SELECT phase,committed_tick FROM decision_history WHERE season_id=? AND tick=0",
        (first_id,),
    ))
    assert len(committed) == 12
    assert all(row["phase"] == "committed" and row["committed_tick"] == 1 for row in committed)

    result = {"status": "running"}
    while result["status"] == "running":
        result = advance_tick(connection)
    assert result == {"advanced": True, "status": "complete", "tick": TARGET_TICKS}

    polls = list(connection.execute(
        """
        SELECT p.id,p.day,p.status,COUNT(o.id) choices,COUNT(DISTINCT o.category) categories
        FROM polls p JOIN poll_options o ON o.poll_id=p.id
        WHERE p.season_id=? GROUP BY p.id ORDER BY p.day
        """,
        (first_id,),
    ))
    assert len(polls) == DAYS_PER_SEASON
    assert all(row["status"] == "closed" and row["choices"] == 6 and row["categories"] == 6 for row in polls)
    assert {
        row[0]
        for row in connection.execute(
            """
            SELECT DISTINCT o.category FROM poll_options o
            JOIN polls p ON p.id=o.poll_id WHERE p.season_id=?
            """,
            (first_id,),
        )
    } == {"social", "civic", "environment", "economy", "relationship", "strange"}

    settlements = list(connection.execute(
        """
        SELECT t.tick,t.external_key,COALESCE(SUM(e.amount_cents),0) balance
        FROM financial_transactions t LEFT JOIN transaction_entries e ON e.transaction_id=t.id
        WHERE t.season_id=? AND t.category='daily_settlement'
        GROUP BY t.id ORDER BY t.tick,t.external_key
        """,
        (first_id,),
    ))
    assert len(settlements) == 12 * DAYS_PER_SEASON
    assert Counter(row["tick"] for row in settlements) == Counter(
        {day * TICKS_PER_DAY + 48: 12 for day in range(DAYS_PER_SEASON)}
    )
    assert all(row["balance"] == 0 for row in settlements)
    assert len({row["external_key"] for row in settlements}) == len(settlements)
    assert connection.execute("SELECT COUNT(*) FROM model_usage").fetchone()[0] == 0

    event_types = [
        row[0]
        for row in connection.execute(
            "SELECT event_type FROM life_events WHERE season_id=? ORDER BY tick,id", (first_id,)
        )
    ]
    assert sum(event_type in DRAMA_TYPES for event_type in event_types) == DAYS_PER_SEASON
    assert {"birth", "life_stage"} <= set(event_types)
    assert connection.execute(
        "SELECT COUNT(*) FROM secrets s JOIN facts f ON f.id=s.fact_id WHERE f.season_id=?",
        (first_id,),
    ).fetchone()[0] > 0
    assert connection.execute(
        "SELECT COUNT(*) FROM story_ledger WHERE season_id=?", (first_id,)
    ).fetchone()[0] >= len(event_types)

    births = list(connection.execute(
        """
        SELECT child.slug,child.traits_json,ci.family_name,ci.appearance_key,
               parent.slug parent_slug,parent.traits_json parent_traits,
               pi.family_name parent_family,pi.appearance_key parent_appearance
        FROM resident_lifecycle life JOIN residents child ON child.id=life.resident_id
        JOIN resident_identities ci ON ci.resident_id=child.id
        JOIN family_links family ON family.resident_id=child.id AND family.relation_type='parent'
        JOIN residents parent ON parent.id=family.relative_resident_id
        JOIN resident_identities pi ON pi.resident_id=parent.id
        WHERE life.birth_season_id=? ORDER BY child.slug,parent.slug
        """,
        (first_id,),
    ))
    assert len(births) == 2
    for birth in births:
        child_traits = loads(birth["traits_json"], {})
        parent_traits = loads(birth["parent_traits"], {})
        assert birth["family_name"] == birth["parent_family"]
        assert birth["appearance_key"] == birth["parent_appearance"]
        assert all(abs(child_traits[key] - parent_traits[key]) <= 7 for key in child_traits)
    _population_counts(connection)

    final_poll_winner = connection.execute(
        """
        SELECT o.event_slug FROM polls p JOIN poll_options o ON o.id=p.winner_option_id
        WHERE p.season_id=? AND p.day=?
        """,
        (first_id, DAYS_PER_SEASON - 1),
    ).fetchone()[0]
    second = start_season(connection, seed_hex=SEEDS[1])
    opening = connection.execute(
        "SELECT slug,source FROM town_events WHERE season_id=? AND day=0", (second["seasonId"],)
    ).fetchone()
    assert (opening["slug"], opening["source"]) == (final_poll_winner, "vote")
    _finish_naturally(connection, int(second["seasonId"]))
    _population_counts(connection)

    third = start_season(connection, seed_hex=SEEDS[2])
    _finish_naturally(connection, int(third["seasonId"]))
    _population_counts(connection)
    assert connection.execute(
        "SELECT COUNT(*) FROM life_events WHERE event_type='death' AND season_id<=?",
        (third["seasonId"],),
    ).fetchone()[0] > 0
    assert connection.execute(
        "SELECT COUNT(*) FROM financial_transactions WHERE category='inheritance'"
    ).fetchone()[0] > 0

    fourth = start_season(connection, seed_hex=SEEDS[3])
    assert fourth["number"] == 4
    assert connection.execute("SELECT COUNT(*) FROM seasons WHERE status='complete'").fetchone()[0] == 3
    _population_counts(connection)
    digests = _stable_digests(connection)
    connection.close()
    return digests


def test_runtime_v2_complete_season_boundaries_and_replay(settings_factory) -> None:
    first = _run_scenario(settings_factory(name="first"))
    second = _run_scenario(settings_factory(name="replay"))
    assert first == second
