from __future__ import annotations

import contextlib
import datetime as dt
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .config import Settings
from .content import LOCATION_POINTS, RESIDENTS, RESIDENT_DETAILS


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def loads(value: str | bytes | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        connection = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5, isolation_level=None
        )
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    if not readonly:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
    return connection


@contextlib.contextmanager
def transaction(connection: sqlite3.Connection, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
    except Exception:
        connection.rollback()
        raise
    else:
        connection.commit()


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {
        int(row[0]) for row in connection.execute("SELECT version FROM schema_migrations")
    }
    migration_dir = Path(__file__).with_name("migrations")
    for migration in sorted(migration_dir.glob("*.sql")):
        version = int(migration.stem.split("_", 1)[0])
        if version in applied:
            continue
        connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            (version, now_iso()),
        )


def seed_residents(connection: sqlite3.Connection) -> None:
    if connection.execute(
        "SELECT 1 FROM resident_identities WHERE generation_seed LIKE 'v2:%' LIMIT 1"
    ).fetchone():
        return
    created = now_iso()
    for profile in RESIDENTS:
        connection.execute(
            """
            INSERT INTO residents(
              slug,name,role,home,workplace,color,traits_json,possessions_json,
              routine,about,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(slug) DO UPDATE SET
              name=excluded.name, role=excluded.role, home=excluded.home,
              workplace=excluded.workplace, color=excluded.color,
              traits_json=excluded.traits_json,routine=excluded.routine,
              about=excluded.about
            """,
            (
                profile.slug,
                profile.name,
                profile.role,
                profile.home,
                profile.workplace,
                profile.color,
                dumps(profile.traits),
                dumps(profile.possessions),
                RESIDENT_DETAILS[profile.slug]["routine"],
                RESIDENT_DETAILS[profile.slug]["about"],
                created,
            ),
        )


def initialize(settings: Settings) -> sqlite3.Connection:
    settings.ensure_directories()
    connection = connect(settings.database_path)
    migrate(connection)
    seed_residents(connection)
    return connection


def emit(
    connection: sqlite3.Connection,
    season_id: int | None,
    tick: int,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    cursor = connection.execute(
        "INSERT INTO event_stream(season_id,tick,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
        (season_id, tick, event_type, dumps(payload), now_iso()),
    )
    return int(cursor.lastrowid)


def resident_rows(connection: sqlite3.Connection, season_id: int) -> list[sqlite3.Row]:
    return list(
        connection.execute(
            """
            SELECT r.*, s.x, s.y, s.destination_x, s.destination_y, s.location,
                   s.activity, s.public_thought, s.intention, s.reflection,
                   s.mood, s.needs_json, s.path_json, s.action_until_tick,
                   s.updated_tick,v.life_stage,v.decision_state,v.current_decision_id,
                   v.household_id,v.care_state
            FROM residents r
            JOIN resident_state s ON s.resident_id=r.id
            LEFT JOIN resident_season_state v
              ON v.resident_id=r.id AND v.season_id=s.season_id
            WHERE s.season_id=? ORDER BY r.id
            """,
            (season_id,),
        )
    )


def initialize_resident_state(
    connection: sqlite3.Connection,
    season_id: int,
    prior_season_id: int | None = None,
) -> None:
    residents = list(
        connection.execute(
            """
            SELECT r.* FROM residents r
            JOIN resident_lifecycle l ON l.resident_id=r.id
            WHERE l.alive=1 ORDER BY r.id
            """
        )
    )
    for resident in residents:
        x, y = LOCATION_POINTS[resident["home"]]
        prior = None
        if prior_season_id is not None:
            prior = connection.execute(
                "SELECT * FROM resident_state WHERE season_id=? AND resident_id=?",
                (prior_season_id, resident["id"]),
            ).fetchone()
        connection.execute(
            """
            INSERT OR IGNORE INTO resident_state(
              season_id,resident_id,x,y,destination_x,destination_y,location,
              activity,public_thought,intention,reflection,mood,needs_json,path_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                season_id,
                resident["id"],
                x,
                y,
                x,
                y,
                resident["home"],
                "settling into the morning",
                str(prior["public_thought"]) if prior else "The Lagoon feels full of possibility.",
                str(prior["intention"]) if prior else "Begin the day with a familiar routine.",
                str(prior["reflection"]) if prior else "A new week is beginning.",
                str(prior["mood"]) if prior else "calm",
                str(prior["needs_json"]) if prior else dumps(
                    {"energy": 82, "hunger": 18, "social": 52, "purpose": 60, "comfort": 75}
                ),
                "[]",
            ),
        )
        for other in residents:
            if int(resident["id"]) >= int(other["id"]):
                continue
            prior_relationship = None
            if prior_season_id is not None:
                prior_relationship = connection.execute(
                    """
                    SELECT * FROM relationships
                    WHERE season_id=? AND resident_a=? AND resident_b=?
                    """,
                    (prior_season_id, resident["id"], other["id"]),
                ).fetchone()
            connection.execute(
                """
                INSERT OR IGNORE INTO relationships(
                  season_id,resident_a,resident_b,affinity,trust,tension,familiarity,
                  interactions,last_interaction_tick,attraction,affection,respect,
                  commitment,resentment
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    season_id,
                    resident["id"],
                    other["id"],
                    int(prior_relationship["affinity"]) if prior_relationship else 0,
                    int(prior_relationship["trust"]) if prior_relationship else 0,
                    int(prior_relationship["tension"]) if prior_relationship else 0,
                    int(prior_relationship["familiarity"]) if prior_relationship else 10,
                    int(prior_relationship["interactions"]) if prior_relationship else 0,
                    prior_relationship["last_interaction_tick"] if prior_relationship else None,
                    int(prior_relationship["attraction"]) if prior_relationship else 0,
                    int(prior_relationship["affection"]) if prior_relationship else 0,
                    int(prior_relationship["respect"]) if prior_relationship else 0,
                    int(prior_relationship["commitment"]) if prior_relationship else 0,
                    int(prior_relationship["resentment"]) if prior_relationship else 0,
                ),
            )
        if prior_season_id is not None:
            memories = connection.execute(
                """
                SELECT * FROM memories WHERE season_id=? AND resident_id=?
                ORDER BY durable DESC,salience DESC,created_tick DESC,id DESC LIMIT 48
                """,
                (prior_season_id, resident["id"]),
            )
            for memory in memories:
                connection.execute(
                    """
                    INSERT INTO memories(
                      season_id,resident_id,kind,content,tags,valence,salience,
                      participants_json,location,created_tick,durable
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        season_id,
                        resident["id"],
                        memory["kind"],
                        memory["content"],
                        memory["tags"],
                        memory["valence"],
                        memory["salience"],
                        memory["participants_json"],
                        memory["location"],
                        0,
                        memory["durable"],
                    ),
                )


def retrieve_memories(
    connection: sqlite3.Connection,
    season_id: int,
    resident_id: int,
    query: str,
    *,
    participants: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    limit: int = 8,
) -> list[dict[str, Any]]:
    words = [word.lower() for word in __import__("re").findall(r"[A-Za-z0-9]{2,}", query)[:12]]
    candidates: list[sqlite3.Row]
    if words:
        expression = " OR ".join(f'"{word}"' for word in words)
        candidates = list(
            connection.execute(
                """
                SELECT m.*,bm25(memory_fts) AS text_rank
                FROM memory_fts JOIN memories m ON m.id=memory_fts.rowid
                WHERE memory_fts MATCH ? AND m.season_id=? AND m.resident_id=?
                ORDER BY text_rank LIMIT 64
                """,
                (expression, season_id, resident_id),
            )
        )
    else:
        candidates = []
    if not candidates:
        candidates = list(
            connection.execute(
                """
                SELECT m.*,0.0 AS text_rank FROM memories m
                WHERE m.season_id=? AND m.resident_id=?
                ORDER BY created_tick DESC,id DESC LIMIT 64
                """,
                (season_id, resident_id),
            )
        )
    latest_tick = int(
        connection.execute("SELECT current_tick FROM seasons WHERE id=?", (season_id,)).fetchone()[0]
    )
    participant_set = set(participants)
    tag_set = {value.lower() for value in tags}

    def score(row: sqlite3.Row) -> float:
        age = max(0, latest_tick - int(row["created_tick"]))
        recency = 8 / (1 + age / 72)
        row_participants = set(loads(row["participants_json"], []))
        row_tags = set(str(row["tags"]).lower().split())
        return (
            int(row["salience"]) * 3
            + recency
            + len(participant_set & row_participants) * 5
            + len(tag_set & row_tags) * 2
            + (4 if row["durable"] else 0)
            - max(0.0, float(row["text_rank"] or 0.0))
        )

    ranked = sorted(candidates, key=score, reverse=True)[: max(1, min(limit, 20))]
    return [
        {
            "kind": row["kind"],
            "content": row["content"],
            "tags": row["tags"],
            "salience": int(row["salience"]),
            "createdTick": int(row["created_tick"]),
        }
        for row in ranked
    ]
