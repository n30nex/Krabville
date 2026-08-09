from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .config import Settings
from .content import LOCATION_POINTS, RESIDENTS, RESIDENT_DETAILS


class MigrationError(RuntimeError):
    pass


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


def _migration_files(
    migration_dir: Path | None = None,
) -> list[tuple[int, Path, str]]:
    root = migration_dir or Path(__file__).with_name("migrations")
    migrations: list[tuple[int, Path, str]] = []
    versions: set[int] = set()
    for path in root.glob("*.sql"):
        try:
            version = int(path.stem.split("_", 1)[0])
        except ValueError as error:
            raise MigrationError(f"invalid migration filename: {path.name}") from error
        if version in versions:
            raise MigrationError(f"duplicate migration version: {version:03d}")
        versions.add(version)
        migrations.append(
            (version, path, hashlib.sha256(path.read_bytes()).hexdigest())
        )
    if not migrations:
        raise MigrationError(f"no migration files found in {root}")
    return sorted(migrations)


def required_schema_version(migration_dir: Path | None = None) -> int:
    return max(version for version, _, _ in _migration_files(migration_dir))


def applied_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    ).fetchone()
    return int(row[0])


def _migration_columns(connection: sqlite3.Connection) -> set[str]:
    if not connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone():
        return set()
    return {
        str(row[1]) for row in connection.execute("PRAGMA table_info(schema_migrations)")
    }


def _validate_applied_migrations(
    connection: sqlite3.Connection,
    migrations: list[tuple[int, Path, str]],
    *,
    require_complete: bool,
) -> dict[str, int | str]:
    columns = _migration_columns(connection)
    if not columns:
        raise MigrationError("schema_migrations is missing; run `krabville-manage bootstrap`")
    has_checksums = "checksum" in columns
    checksum_sql = "checksum" if has_checksums else "NULL AS checksum"
    applied = {
        int(row["version"]): row["checksum"]
        for row in connection.execute(
            f"SELECT version,{checksum_sql} FROM schema_migrations ORDER BY version"
        )
    }
    expected = {version: checksum for version, _, checksum in migrations}
    unknown = sorted(applied.keys() - expected.keys())
    if unknown:
        raise MigrationError(f"database contains unknown migration versions: {unknown}")
    for version, stored_checksum in applied.items():
        if stored_checksum is None:
            if has_checksums:
                raise MigrationError(f"migration {version:03d} has no recorded checksum")
            continue
        if str(stored_checksum) != expected[version]:
            raise MigrationError(
                f"migration {version:03d} checksum mismatch; applied migrations are immutable"
            )
    pending = sorted(expected.keys() - applied.keys())
    if require_complete:
        if not has_checksums:
            raise MigrationError(
                "migration checksum metadata is missing; run `krabville-manage bootstrap`"
            )
        if pending:
            raise MigrationError(
                f"database schema is not bootstrapped; pending migrations: {pending}"
            )
    return {
        "version": max(applied, default=0),
        "migrationCount": len(applied),
        "checksumState": "ok" if has_checksums and not pending else "incomplete",
    }


def assert_schema(
    connection: sqlite3.Connection, migration_dir: Path | None = None
) -> dict[str, int | str]:
    return _validate_applied_migrations(
        connection, _migration_files(migration_dir), require_complete=True
    )


def _apply_migration(
    connection: sqlite3.Connection,
    migration: tuple[int, Path, str],
    migrations: list[tuple[int, Path, str]],
) -> None:
    version, path, checksum = migration
    script = path.read_text(encoding="utf-8")
    try:
        connection.executescript(f"BEGIN IMMEDIATE;\n{script}\n")
        if "checksum" in _migration_columns(connection):
            connection.execute(
                "INSERT INTO schema_migrations(version,applied_at,checksum) VALUES(?,?,?)",
                (version, now_iso(), checksum),
            )
        else:
            connection.execute(
                "INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)",
                (version, now_iso()),
            )
        _validate_applied_migrations(
            connection, migrations, require_complete=False
        )
        connection.commit()
    except Exception as error:
        connection.rollback()
        if isinstance(error, MigrationError):
            raise
        raise MigrationError(f"migration {path.name} failed: {error}") from error


def migrate(
    connection: sqlite3.Connection, migration_dir: Path | None = None
) -> dict[str, int | str]:
    migrations = _migration_files(migration_dir)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    _validate_applied_migrations(connection, migrations, require_complete=False)
    applied = {
        int(row[0])
        for row in connection.execute("SELECT version FROM schema_migrations")
    }
    for migration in migrations:
        if migration[0] in applied:
            continue
        _apply_migration(connection, migration, migrations)
        applied.add(migration[0])
    return assert_schema(connection, migration_dir)


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
    try:
        migrate(connection)
        seed_residents(connection)
        from .commerce_v2 import repair_dependent_finances, seed_commerce

        seed_commerce(connection)
        repair_dependent_finances(connection)
        return connection
    except Exception:
        connection.close()
        raise


def open_database(
    settings: Settings, *, readonly: bool = False
) -> sqlite3.Connection:
    settings.ensure_directories()
    if not settings.database_path.is_file():
        raise MigrationError(
            "database is not bootstrapped; run `krabville-manage bootstrap`"
        )
    connection = connect(settings.database_path, readonly=readonly)
    try:
        assert_schema(connection)
        return connection
    except Exception:
        connection.close()
        raise


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
                   v.household_id,v.care_state,v.current_caregiver_id,
                   v.current_care_provider_id,v.preferred_action,v.preference_tags_json,
                   caregiver.name caregiver_name,
                   care_provider.name care_provider_name
            FROM residents r
            JOIN resident_state s ON s.resident_id=r.id
            LEFT JOIN resident_season_state v
              ON v.resident_id=r.id AND v.season_id=s.season_id
            LEFT JOIN residents caregiver ON caregiver.id=v.current_caregiver_id
            LEFT JOIN businesses care_provider ON care_provider.id=v.current_care_provider_id
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
