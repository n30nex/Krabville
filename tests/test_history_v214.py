from __future__ import annotations

from krabville.db import initialize
from krabville.history_v214 import repair_v214
from krabville.reporter import rebuild_verified_chronicles, verify_archive
from krabville.world import start_season


def test_history_repair_closes_goals_normalizes_epilogue_and_rebuilds_from_ledger(
    settings_factory,
) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    season_id = int(start_season(connection, seed_hex="71" * 32)["seasonId"])
    resident = connection.execute("SELECT id,name FROM residents ORDER BY id LIMIT 1").fetchone()
    connection.execute(
        """
        INSERT INTO activities(season_id,tick,resident_id,kind,summary,source,created_at)
        VALUES(?,10,?,'work','Hana completed a recorded task.','local','now')
        """,
        (season_id, resident["id"]),
    )
    life_event_id = int(
        connection.execute(
            """
            INSERT INTO life_events(
              season_id,tick,event_type,subject_resident_id,title,summary,severity,created_at
            ) VALUES(?,2016,'lifecycle',?,'Season boundary','A recorded lifecycle change occurred.',60,'now')
            RETURNING id
            """,
            (season_id, resident["id"]),
        ).fetchone()[0]
    )
    connection.execute(
        "INSERT INTO life_event_participants(life_event_id,resident_id,role) VALUES(?,?,'subject')",
        (life_event_id, resident["id"]),
    )
    ledger_id = int(
        connection.execute(
            """
            INSERT INTO story_ledger(
              season_id,tick,day,entry_type,headline,summary,significance,
              visibility,life_event_id,created_at
            ) VALUES(?,2016,7,'lifecycle','Season boundary',
              'A recorded lifecycle change occurred.',60,'public',?,'now')
            RETURNING id
            """,
            (season_id, life_event_id),
        ).fetchone()[0]
    )
    connection.execute(
        """
        UPDATE seasons SET status='complete',current_tick=2016,current_day=6,
          world_minutes=1435,seed_revealed=1,model_locked=1,completed_at='now'
        WHERE id=?
        """,
        (season_id,),
    )

    repair_v214(connection)
    rebuilt = rebuild_verified_chronicles(connection, season_id)
    verified = verify_archive(connection, season_id)

    assert len(rebuilt["chronicles"]) == 7
    assert verified == {
        "seasonId": season_id,
        "days": 7,
        "verified": True,
        "sources": ["ledger_local"],
        "invalidLedgerIds": [],
    }
    epilogue = connection.execute(
        "SELECT day,phase FROM story_ledger WHERE id=?", (ledger_id,)
    ).fetchone()
    assert tuple(epilogue) == (6, "epilogue")
    assert connection.execute(
        "SELECT COUNT(*) FROM goals WHERE season_id=? AND status='active'", (season_id,)
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM story_ledger_participants WHERE ledger_id=?", (ledger_id,)
    ).fetchone()[0] == 1
    prose = " ".join(
        row[0] for row in connection.execute(
            "SELECT narrative FROM daily_chronicles WHERE season_id=?", (season_id,)
        )
    )
    assert "Mara" not in prose
    connection.close()
