from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from krabville.api import create_app
from krabville.backup import (
    BackupError,
    LAST_VERIFIED_FILE,
    create_backup,
    last_verified_backup,
    restore_dry_run,
    verify_backup,
)
from krabville.db import connect, initialize
from krabville.world import advance_tick, start_season, stop_now


def _running_world(settings) -> int:
    connection = initialize(settings)
    try:
        start_season(connection, seed_hex="91" * 32)
        for _ in range(3):
            advance_tick(connection)
        return int(
            connection.execute(
                "SELECT current_tick FROM seasons ORDER BY number DESC LIMIT 1"
            ).fetchone()[0]
        )
    finally:
        connection.close()


def test_online_backup_records_and_verifies_release_schema_and_integrity(
    settings_factory,
) -> None:
    settings = settings_factory(release_commit="a" * 40)
    source_tick = _running_world(settings)
    backup = settings.data_dir / "backups" / "test.db"

    result = create_backup(settings, backup)

    assert result["file"]["name"] == "test.db"
    assert result["file"]["bytes"] > 0
    assert len(result["file"]["sha256"]) == 64
    assert result["release"] == {"version": "2.2.1", "commit": "a" * 40}
    assert result["schema"]["version"] == 15
    assert result["schema"]["checksumState"] == "ok"
    assert len(result["schema"]["manifestSha256"]) == 64
    assert result["database"] == {
        "quickCheck": ["ok"],
        "foreignKeyErrors": 0,
        "unbalancedTransactions": 0,
    }
    assert result["season"]["tick"] == source_tick
    assert Path(result["metadata"]).is_file()
    assert verify_backup(settings, backup)["file"] == result["file"]

    with TestClient(create_app(settings), base_url="http://testserver") as client:
        health = client.get("/healthz").json()
        metrics = client.get("/metrics").text
    assert health["backup"]["available"] is True
    assert health["backup"]["schema"] == 15
    assert "krabville_backup_verified 1" in metrics


def test_public_backup_status_uses_a_fixed_allowlist(settings_factory) -> None:
    settings = settings_factory()
    _running_world(settings)
    create_backup(settings, settings.data_dir / "backups" / "public-status.db")
    status_path = settings.data_dir / LAST_VERIFIED_FILE
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    payload["file"]["name"] = "private-location.db"
    payload["season"]["privateNote"] = "do-not-publish"
    status_path.write_text(json.dumps(payload), encoding="utf-8")

    public = last_verified_backup(settings)

    assert set(public) == {
        "available",
        "verifiedAt",
        "createdAt",
        "bytes",
        "schema",
        "season",
    }
    assert set(public["season"]) == {"number", "status", "tick", "day"}
    assert "private" not in json.dumps(public).lower()


def test_verification_rejects_sidecar_or_database_tampering(settings_factory) -> None:
    settings = settings_factory()
    _running_world(settings)
    backup = settings.data_dir / "backups" / "tamper.db"
    result = create_backup(settings, backup)
    metadata = Path(result["metadata"])
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    payload["file"]["sha256"] = "0" * 64
    metadata.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BackupError, match="file metadata does not match"):
        verify_backup(settings, backup)


@pytest.mark.parametrize("field", ["release", "createdAt"])
def test_verification_requires_release_identity_and_creation_time(
    settings_factory, field: str
) -> None:
    settings = settings_factory()
    _running_world(settings)
    backup = settings.data_dir / "backups" / f"missing-{field}.db"
    result = create_backup(settings, backup)
    metadata = Path(result["metadata"])
    payload = json.loads(metadata.read_text(encoding="utf-8"))
    del payload[field]
    metadata.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BackupError, match="missing required fields"):
        verify_backup(settings, backup)


@pytest.mark.parametrize("completed", [False, True])
def test_disposable_restore_serves_state_and_advances_without_touching_source(
    settings_factory,
    completed: bool,
) -> None:
    settings = settings_factory()
    source_tick = _running_world(settings)
    if completed:
        connection = connect(settings.database_path)
        try:
            stop_now(connection)
        finally:
            connection.close()
    backup = settings.data_dir / "backups" / f"restore-{completed}.db"
    create_backup(settings, backup)

    result = restore_dry_run(settings, backup)

    assert result["dryRun"] is True
    assert result["publicState"] == {"ok": True, "schemaVersion": 3}
    assert result["replay"]["tickAfter"] == result["replay"]["tickBefore"] + 1
    assert result["replay"]["provider"] == "fake"
    assert result["replay"]["providerResult"] is True
    assert result["replay"]["providerTokens"] == 330
    assert result["database"] == {
        "quickCheck": ["ok"],
        "foreignKeyErrors": 0,
        "unbalancedTransactions": 0,
    }
    connection = connect(settings.database_path, readonly=True)
    try:
        assert (
            int(
                connection.execute(
                    "SELECT current_tick FROM seasons ORDER BY number DESC LIMIT 1"
                ).fetchone()[0]
            )
            == source_tick
        )
    finally:
        connection.close()


def test_disposable_restore_never_replays_a_negative_tick(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    try:
        start_season(connection, seed_hex="92" * 32)
        stop_now(connection)
    finally:
        connection.close()
    backup = settings.data_dir / "backups" / "stopped-at-zero.db"
    create_backup(settings, backup)

    replay = restore_dry_run(settings, backup)["replay"]

    assert replay["tickBefore"] == 0
    assert replay["tickAfter"] == 1
