from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from krabville.api import create_app
from krabville.db import connect, migrate
from krabville.inference import FakeProvider, process_one
from krabville.world import advance_tick


FIXTURE = (
    Path(__file__).with_name("fixtures") / "krabville-v2.2.1-schema-013.sqlite3.gz"
)
FIXTURE_RELEASE_SCHEMA = 13
FIXTURE_APPLICATION_ID = 0x4B565332
FIXTURE_SHA256 = "9749386cb96381fb6581fec222db5b222fa18e2af5007779bdc31eb6afc566a5"
EXPECTED_REPLAY_DIGEST = (
    "455d7c0b531fd1d52d8c0aa9513be4ade77221fe466e3f1e9d3dde7b2af70bfb"
)
REPLAY_TICKS = 8


def _materialize_fixture(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(FIXTURE, "rb") as source, path.open("wb") as target:
        shutil.copyfileobj(source, target)


def _migration_versions(connection: sqlite3.Connection) -> list[int]:
    return [
        int(row[0])
        for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
    ]


def _current_migration_versions() -> list[int]:
    migration_dir = (
        Path(__file__).resolve().parents[1] / "src" / "krabville" / "migrations"
    )
    return [
        int(path.stem.split("_", 1)[0]) for path in sorted(migration_dir.glob("*.sql"))
    ]


def _assert_database_invariants(connection: sqlite3.Connection) -> dict[str, int | str]:
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_key_errors = len(list(connection.execute("PRAGMA foreign_key_check")))
    unbalanced = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT transaction_record.id
              FROM financial_transactions transaction_record
              LEFT JOIN transaction_entries entry
                ON entry.transaction_id=transaction_record.id
              WHERE transaction_record.status='posted'
              GROUP BY transaction_record.id
              HAVING COUNT(entry.id)<2 OR COALESCE(SUM(entry.amount_cents),0)<>0
            )
            """
        ).fetchone()[0]
    )
    posted = int(
        connection.execute(
            "SELECT COUNT(*) FROM financial_transactions WHERE status='posted'"
        ).fetchone()[0]
    )
    assert integrity == "ok"
    assert foreign_key_errors == 0
    assert unbalanced == 0
    return {
        "integrity": integrity,
        "foreignKeyErrors": foreign_key_errors,
        "postedTransactions": posted,
        "unbalancedTransactions": unbalanced,
    }


def _stable_replay_digest(connection: sqlite3.Connection) -> str:
    queries = {
        "season": """
            SELECT number,status,current_tick,current_day,world_minutes,model_locked,model_degraded
            FROM seasons ORDER BY number
        """,
        "residents": """
            SELECT resident.slug,state.location,state.activity,state.needs_json,state.path_json,
                   season_state.decision_state,season_state.preferred_action
            FROM resident_state state JOIN residents resident ON resident.id=state.resident_id
            LEFT JOIN resident_season_state season_state
              ON season_state.season_id=state.season_id
             AND season_state.resident_id=state.resident_id
            ORDER BY resident.slug
        """,
        "decisions": """
            SELECT resident.slug,decision.tick,decision.phase,decision.chosen_action,
                   decision.chosen_destination,decision.utility_score
            FROM decision_history decision JOIN residents resident ON resident.id=decision.resident_id
            ORDER BY decision.tick,resident.slug,decision.id
        """,
        "jobs": """
            SELECT kind,status,attempts,result_json,error_code
            FROM model_jobs ORDER BY id
        """,
        "usage": """
            SELECT attempt_number,model,status,input_tokens,output_tokens,total_tokens,error_class
            FROM model_usage ORDER BY id
        """,
        "accounting": """
            SELECT transaction_record.tick,transaction_record.category,transaction_record.external_key,
                   account.name,entry.amount_cents,entry.memo
            FROM financial_transactions transaction_record
            JOIN transaction_entries entry ON entry.transaction_id=transaction_record.id
            JOIN financial_accounts account ON account.id=entry.account_id
            ORDER BY transaction_record.id,entry.id
        """,
    }
    payload = {
        name: [tuple(row) for row in connection.execute(query)]
        for name, query in queries.items()
    }
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()


def _migrate_and_replay(settings) -> tuple[str, dict[str, int | str]]:
    connection = connect(settings.database_path)
    try:
        migrate(connection)
        assert _migration_versions(connection) == _current_migration_versions()
        assert process_one(connection, settings, FakeProvider())
        for _ in range(REPLAY_TICKS):
            result = advance_tick(connection)
            assert result["advanced"] is True
            assert result["status"] == "running"
        report = _assert_database_invariants(connection)
        assert (
            connection.execute(
                "SELECT current_tick FROM seasons WHERE status='running'"
            ).fetchone()[0]
            == 52
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM model_usage WHERE status='complete'"
            ).fetchone()[0]
            == 1
        )
        return _stable_replay_digest(connection), report
    finally:
        connection.close()


def test_retained_v22_fixture_migrates_reads_and_replays_deterministically(
    settings_factory,
) -> None:
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256

    read_settings = settings_factory(
        name="v22-read",
        token_guard=1_500_000,
        auto_continue=False,
        tick_stale_seconds=1_000_000_000,
    )
    _materialize_fixture(read_settings.database_path)
    connection = connect(read_settings.database_path)
    try:
        assert (
            connection.execute("PRAGMA application_id").fetchone()[0]
            == FIXTURE_APPLICATION_ID
        )
        assert (
            connection.execute("PRAGMA user_version").fetchone()[0]
            == FIXTURE_RELEASE_SCHEMA
        )
        assert _migration_versions(connection) == list(
            range(1, FIXTURE_RELEASE_SCHEMA + 1)
        )
        migrate(connection)
        assert _migration_versions(connection) == _current_migration_versions()
        assert {
            row[1] for row in connection.execute("PRAGMA table_info(resident_wants)")
        } >= {"source_need", "action_key", "expires_tick"}
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='life_goals'"
        ).fetchone()
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='housing_recovery'"
        ).fetchone()
        initial_report = _assert_database_invariants(connection)
        assert initial_report == {
            "integrity": "ok",
            "foreignKeyErrors": 0,
            "postedTransactions": 0,
            "unbalancedTransactions": 0,
        }
    finally:
        connection.close()

    with TestClient(create_app(read_settings), base_url="http://testserver") as client:
        health = client.get("/healthz")
        state = client.get("/api/v3/state")
        economy = client.get("/api/v3/economy")
        seasons = client.get("/api/v3/seasons")
        assert (
            health.status_code
            == state.status_code
            == economy.status_code
            == seasons.status_code
            == 200
        )
        payload = state.json()
        assert health.json()["database"] == "ok"
        assert payload["schemaVersion"] == 3
        assert payload["season"]["tick"] == 44
        assert len(payload["residents"]) == 12
        resident = client.get(f"/api/v3/residents/{payload['residents'][0]['slug']}")
        assert resident.status_code == 200
        assert resident.json()["slug"] == payload["residents"][0]["slug"]

    replay_results = []
    for name in ("v22-replay-a", "v22-replay-b"):
        settings = settings_factory(
            name=name, token_guard=1_500_000, auto_continue=False
        )
        _materialize_fixture(settings.database_path)
        replay_results.append(_migrate_and_replay(settings))

    assert replay_results[0] == replay_results[1]
    digest, report = replay_results[0]
    assert digest == EXPECTED_REPLAY_DIGEST
    assert report == {
        "integrity": "ok",
        "foreignKeyErrors": 0,
        "postedTransactions": 151,
        "unbalancedTransactions": 0,
    }


def test_retained_v22_fixture_contains_only_synthetic_public_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "fixture.sqlite3"
    _materialize_fixture(database_path)
    connection = sqlite3.connect(database_path)
    try:
        dump = "\n".join(connection.iterdump()).lower()
    finally:
        connection.close()
    for forbidden in (
        "neonx",
        "haggis",
        "192.168.0.",
        "/opt/canadaverse",
        "f:\\openclaw",
        "ctx7sk-",
        "discord_bot_token",
        "codex oauth",
    ):
        assert forbidden not in dump
