from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from krabville.commerce_v2 import repair_dependent_finances, seed_commerce  # noqa: E402
from krabville.config import Settings  # noqa: E402
from krabville.db import connect, seed_residents  # noqa: E402
from krabville.world import advance_tick, start_season  # noqa: E402


RELEASE = "v2.2.1"
RELEASE_COMMIT = "f630a9502b029097deeecbbc85b0f74aca4e99f9"
RELEASE_SCHEMA = 13
FIXTURE_TICK = 44
FIXED_TIME = "2026-08-09T00:00:00+00:00"
FIXED_SEED = "23" * 32
APPLICATION_ID = 0x4B565332  # KVS2
DEFAULT_OUTPUT = Path(__file__).with_name("krabville-v2.2.1-schema-013.sqlite3.gz")


def _settings(database_path: Path) -> Settings:
    root = database_path.parent
    return Settings(
        data_dir=root,
        database_path=database_path,
        asset_dir=root / "assets",
        report_dir=root / "reports",
        frontend_dir=root / "frontend",
        control_socket=root / "control.sock",
        bind_host="127.0.0.1",
        port=18890,
        tick_seconds=0.01,
        fake_provider=True,
        primary_model="gpt-5.3-codex-spark",
        primary_reasoning="low",
        fallback_model="gpt-5.6-luna",
        fallback_reasoning="low",
        call_limit=150,
        token_guard=1_500_000,
        inference_timeout=10,
        voter_secret="fixture-only-secret-with-enough-entropy",
        public_origin="http://testserver",
        auto_continue=False,
        release_commit=RELEASE_COMMIT,
    )


def _apply_release_migrations(connection: sqlite3.Connection) -> None:
    migration_dir = ROOT / "src" / "krabville" / "migrations"
    for migration in sorted(migration_dir.glob("*.sql")):
        version = int(migration.stem.split("_", 1)[0])
        if version > RELEASE_SCHEMA:
            break
        connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(?,?)",
            (version, FIXED_TIME),
        )
    versions = [
        int(row[0])
        for row in connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
    ]
    if versions != list(range(1, RELEASE_SCHEMA + 1)):
        raise RuntimeError(f"release migrations are incomplete: {versions}")


def build_fixture(output: Path = DEFAULT_OUTPUT) -> dict[str, str | int]:
    """Build the public synthetic v2.2.1 release fixture.

    Regenerate this artifact from the recorded v2.2.1 source commit. The fixed
    seed, clock, and tick make its semantic contents deterministic; no live
    database, credentials, network data, or operator identifiers are read.
    """
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        dir=output.parent, prefix=".v22-fixture-"
    ) as staging:
        staging_dir = Path(staging)
        database_path = staging_dir / "krabville.db"
        compressed_path = staging_dir / output.name
        settings = _settings(database_path)
        settings.ensure_directories()
        connection = connect(database_path)
        try:
            _apply_release_migrations(connection)
            with ExitStack() as stack:
                for module in (
                    "krabville.db",
                    "krabville.runtime_v2",
                    "krabville.world",
                ):
                    stack.enter_context(
                        patch(f"{module}.now_iso", return_value=FIXED_TIME)
                    )
                stack.enter_context(
                    patch("krabville.commerce_v2._now", return_value=FIXED_TIME)
                )
                seed_residents(connection)
                seed_commerce(connection)
                repair_dependent_finances(connection)
                start_season(connection, seed_hex=FIXED_SEED)
                for _ in range(FIXTURE_TICK):
                    advance_tick(connection)
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={RELEASE_SCHEMA}")
            connection.commit()
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("fixture integrity check failed")
            if list(connection.execute("PRAGMA foreign_key_check")):
                raise RuntimeError("fixture foreign-key check failed")
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("VACUUM")
        finally:
            connection.close()

        with database_path.open("rb") as source, compressed_path.open("wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
            ) as target:
                shutil.copyfileobj(source, target)
        compressed_path.replace(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {
        "release": RELEASE,
        "commit": RELEASE_COMMIT,
        "schema": RELEASE_SCHEMA,
        "tick": FIXTURE_TICK,
        "sha256": digest,
        "compressedBytes": output.stat().st_size,
    }


if __name__ == "__main__":
    print(json.dumps(build_fixture(), indent=2, sort_keys=True))
