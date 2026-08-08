from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from PIL import Image

from krabville.db import initialize, now_iso
from krabville.reporter import generate_report
from krabville.world import start_season


def test_v2_report_renders_full_local_ledger(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    season_id = start_season(connection, seed_hex="a5" * 32)["seasonId"]
    residents = list(connection.execute("SELECT id,name FROM residents ORDER BY id LIMIT 3"))
    first, second, third = (int(row["id"]) for row in residents)

    connection.execute(
        "UPDATE resident_season_state SET life_stage='child',stress=72 WHERE season_id=? AND resident_id=?",
        (season_id, first),
    )
    connection.execute(
        """
        UPDATE resident_lifecycle SET birth_season_id=?,birth_tick=20
        WHERE resident_id=?
        """,
        (season_id, first),
    )
    connection.execute(
        """
        UPDATE resident_lifecycle SET current_stage='deceased',alive=0,
          death_season_id=?,death_tick=140,death_cause='natural causes'
        WHERE resident_id=?
        """,
        (season_id, third),
    )
    connection.execute(
        "UPDATE resident_season_state SET life_stage='deceased',care_state='deceased' WHERE season_id=? AND resident_id=?",
        (season_id, third),
    )
    connection.execute(
        "UPDATE resident_needs SET satisfaction=18 WHERE season_id=? AND resident_id=? AND need_key='social'",
        (season_id, first),
    )
    a, b = sorted((first, second))
    connection.execute(
        """
        UPDATE relationships SET affinity=82,trust=76,tension=31,interactions=9,
          affection=70,respect=65,commitment=55,resentment=22
        WHERE season_id=? AND resident_a=? AND resident_b=?
        """,
        (season_id, a, b),
    )

    account_one = connection.execute(
        """
        INSERT INTO financial_accounts(
          resident_id,name,account_type,opening_balance_cents,opened_season_id
        ) VALUES(?,?,'chequing',100000,?)
        """,
        (first, "Daily account", season_id),
    ).lastrowid
    account_two = connection.execute(
        """
        INSERT INTO financial_accounts(
          resident_id,name,account_type,opening_balance_cents,opened_season_id
        ) VALUES(?,?,'savings',25000,?)
        """,
        (second, "Rainy day", season_id),
    ).lastrowid
    transaction_id = connection.execute(
        """
        INSERT INTO financial_transactions(
          season_id,tick,category,description,status,external_key,created_at,posted_at
        ) VALUES(?,120,'wages','Weekly payroll','posted','report-test',?,?)
        """,
        (season_id, now_iso(), now_iso()),
    ).lastrowid
    connection.execute(
        "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,25000,'pay')",
        (transaction_id, account_one),
    )
    connection.execute(
        "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,-25000,'pay')",
        (transaction_id, account_two),
    )
    connection.execute(
        """
        INSERT INTO assets(
          resident_id,asset_type,name,value_cents,acquired_season_id,acquired_tick
        ) VALUES(?,'vehicle','Lagoon skiff',280000,?,40)
        """,
        (first, season_id),
    )
    connection.execute(
        """
        INSERT INTO investments(
          account_id,symbol,investment_type,units,average_cost_cents,
          market_value_cents,acquired_season_id,updated_season_id
        ) VALUES(?,'CVF','fund',4,10000,48000,?,?)
        """,
        (account_two, season_id, season_id),
    )
    connection.execute(
        """
        INSERT INTO debts(
          borrower_account_id,debt_type,principal_cents,outstanding_cents,
          opened_season_id,status
        ) VALUES(?,'personal',60000,42000,?,'late')
        """,
        (account_one, season_id),
    )

    life_event_id = connection.execute(
        """
        INSERT INTO life_events(
          season_id,tick,event_type,subject_resident_id,related_resident_id,
          title,summary,outcome,severity,permanent,created_at
        ) VALUES(?,180,'betrayal',?,?,'The broken promise',
          'A trusted promise fractured at the market.','Trust fell sharply.',88,1,?)
        """,
        (season_id, first, second, now_iso()),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO story_ledger(
          season_id,tick,day,entry_type,headline,summary,significance,
          visibility,life_event_id,created_at
        ) VALUES(?,180,2,'drama','A promise breaks',
          'The dispute changed two friendships and divided the market.',91,
          'omniscient',?,?)
        """,
        (season_id, life_event_id, now_iso()),
    )
    fact_id = connection.execute(
        """
        INSERT INTO facts(
          season_id,canonical_key,category,statement,occurred_tick,created_at
        ) VALUES(?,'report-secret','social','Someone hid the missing parcel.',90,?)
        """,
        (season_id, now_iso()),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO secrets(
          fact_id,owner_resident_id,sensitivity,status,created_tick,revealed_tick,
          revelation_summary
        ) VALUES(?, ?,80,'public',90,200,'The parcel was found.')
        """,
        (fact_id, second),
    )
    poll_id = connection.execute(
        """
        INSERT INTO polls(season_id,day,opens_tick,closes_tick,status,created_at)
        VALUES(?,0,24,264,'closed',?)
        """,
        (season_id, now_iso()),
    ).lastrowid
    option_id = connection.execute(
        """
        INSERT INTO poll_options(
          poll_id,choice_id,event_slug,title,category,preview,votes
        ) VALUES(?,'A','storm-watch','Prepare for the storm','environment','Secure the docks.',6)
        """,
        (poll_id,),
    ).lastrowid
    connection.execute("UPDATE polls SET winner_option_id=? WHERE id=?", (option_id, poll_id))
    connection.execute(
        """
        INSERT INTO daily_chronicles(
          season_id,day,title,narrative,statistics_json,created_at
        ) VALUES(?,0,'Day 1: A difficult morning','The town debated what the promise meant.','{}',?)
        """,
        (season_id, now_iso()),
    )

    output = generate_report(connection, season_id, settings)
    report = connection.execute("SELECT * FROM reports WHERE season_id=?", (season_id,)).fetchone()
    statistics = json.loads(report["statistics_json"])

    with Image.open(output) as image:
        assert image.size == (1920, 1080)
        assert image.mode == "RGB"
        assert image.getbbox() == (0, 0, 1920, 1080)
    assert statistics["lifecycle"]["available"] is True
    assert statistics["lifecycle"]["births"] == 1
    assert statistics["lifecycle"]["deaths"] == 1
    assert statistics["economy"]["postedTransactions"] == 1
    assert statistics["economy"]["debtCents"] >= 42000
    assert statistics["drama"]["lifeEvents"] == 1
    assert statistics["drama"]["revealedSecrets"] == 1
    assert statistics["ledger"]["entries"] == 1
    assert statistics["ledger"]["omniscientEntries"] == 1
    assert statistics["voting"]["votes"] == 6
    assert statistics["voting"]["winners"][0]["title"] == "Prepare for the storm"
    assert statistics["strongestBond"] == statistics["relationships"]["strongestBond"]
    assert report["headline"] == "Season 1 in focus: A promise breaks"
    connection.close()


def test_reporter_remains_compatible_with_legacy_schema(settings_factory) -> None:
    settings = settings_factory(name="legacy")
    settings.ensure_directories()
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    migration = Path(__file__).resolve().parents[1] / "src" / "krabville" / "migrations" / "001_initial.sql"
    connection.executescript(migration.read_text(encoding="utf-8"))
    created = now_iso()
    season_id = connection.execute(
        """
        INSERT INTO seasons(number,status,created_at,seed_hex,seed_commitment)
        VALUES(1,'complete',?,'legacy-seed','legacy-commitment')
        """,
        (created,),
    ).lastrowid
    resident_id = connection.execute(
        """
        INSERT INTO residents(
          slug,name,role,home,workplace,color,traits_json,possessions_json,created_at
        ) VALUES('legacy','Legacy Resident','Archivist','Home','Library','#44aabb','[]','[]',?)
        """,
        (created,),
    ).lastrowid
    connection.execute(
        """
        INSERT INTO resident_state(
          season_id,resident_id,x,y,destination_x,destination_y,location,activity,
          public_thought,intention,reflection,mood,needs_json
        ) VALUES(?,?,0,0,0,0,'Home','remembering','What a week.','Write it down.',
          'The record is safe.','calm','{}')
        """,
        (season_id, resident_id),
    )
    connection.execute(
        """
        INSERT INTO daily_chronicles(
          season_id,day,title,narrative,statistics_json,created_at
        ) VALUES(?,0,'Day 1: The old town','The first archive survived intact.','{}',?)
        """,
        (season_id, created),
    )

    output = generate_report(connection, season_id, settings)
    report = connection.execute("SELECT statistics_json FROM reports WHERE season_id=?", (season_id,)).fetchone()
    statistics = json.loads(report["statistics_json"])

    with Image.open(output) as image:
        assert image.size == (1920, 1080)
    assert statistics["residents"] == 1
    assert statistics["lifecycle"]["available"] is False
    assert statistics["economy"]["available"] is False
    assert statistics["drama"]["available"] is False
    assert statistics["ledger"]["available"] is False
    connection.close()
