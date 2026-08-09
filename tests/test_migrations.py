from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import krabville.cli as cli

from krabville.api import create_app
from krabville.db import (
    MigrationError,
    assert_schema,
    connect,
    initialize,
    migrate,
)
from krabville.engine import Engine
from krabville.inference import run_worker


def _checksum_migrations(root: Path) -> Path:
    root.mkdir()
    first = root / "001_widgets.sql"
    first.write_text(
        "CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT NOT NULL);\n",
        encoding="utf-8",
    )
    checksum = hashlib.sha256(first.read_bytes()).hexdigest()
    (root / "002_checksums.sql").write_text(
        "ALTER TABLE schema_migrations ADD COLUMN checksum TEXT;\n"
        f"UPDATE schema_migrations SET checksum='{checksum}' WHERE version=1;\n",
        encoding="utf-8",
    )
    return first


def test_modified_applied_migration_is_rejected(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    first = _checksum_migrations(migration_dir)
    connection = connect(tmp_path / "krabville.db")
    try:
        assert migrate(connection, migration_dir)["checksumState"] == "ok"
        first.write_text(
            first.read_text(encoding="utf-8") + "-- changed after apply\n",
            encoding="utf-8",
        )

        with pytest.raises(MigrationError, match="001 checksum mismatch"):
            migrate(connection, migration_dir)
    finally:
        connection.close()


def test_failed_migration_rolls_back_sql_and_metadata(tmp_path: Path) -> None:
    migration_dir = tmp_path / "migrations"
    _checksum_migrations(migration_dir)
    connection = connect(tmp_path / "krabville.db")
    try:
        migrate(connection, migration_dir)
        (migration_dir / "003_broken.sql").write_text(
            "CREATE TABLE partial_write (id INTEGER PRIMARY KEY);\n"
            "INSERT INTO table_that_does_not_exist VALUES (1);\n",
            encoding="utf-8",
        )

        with pytest.raises(MigrationError, match="migration 003_broken.sql failed"):
            migrate(connection, migration_dir)

        assert not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='partial_write'"
        ).fetchone()
        assert [
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ] == [1, 2]
    finally:
        connection.close()


def test_bootstrap_records_all_migration_checksums(settings_factory) -> None:
    connection = initialize(settings_factory())
    try:
        state = assert_schema(connection)
        rows = list(
            connection.execute(
                "SELECT version,checksum FROM schema_migrations ORDER BY version"
            )
        )
        assert state == {
            "version": len(rows),
            "migrationCount": len(rows),
            "checksumState": "ok",
        }
        assert [int(row["version"]) for row in rows] == list(range(1, len(rows) + 1))
        assert all(len(str(row["checksum"])) == 64 for row in rows)
    finally:
        connection.close()


def test_management_bootstrap_entrypoint(monkeypatch, capsys, settings_factory) -> None:
    settings = settings_factory()
    monkeypatch.setattr(cli.Settings, "from_env", lambda: settings)
    monkeypatch.setattr(sys, "argv", ["krabville-manage", "bootstrap"])

    cli.main()

    result = json.loads(capsys.readouterr().out)
    assert result == {
        "bootstrap": "ok",
        "schema": {
            "version": 15,
            "migrationCount": 15,
            "checksumState": "ok",
        },
    }
    assert settings.database_path.is_file()


@pytest.mark.parametrize(
    "starter",
    [
        create_app,
        Engine,
        lambda settings: run_worker(settings, once=True),
    ],
    ids=["web", "engine", "inference"],
)
def test_runtime_refuses_to_bootstrap_an_empty_database(
    starter, settings_factory
) -> None:
    settings = settings_factory()
    with pytest.raises(MigrationError, match="krabville-manage bootstrap"):
        starter(settings)
    assert not settings.database_path.exists()
