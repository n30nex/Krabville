from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import __version__
from .config import Settings
from .db import assert_schema, connect, dumps, now_iso, open_database
from .inference import FakeProvider, process_one
from .world import TICKS_PER_DAY, advance_tick, start_season


METADATA_VERSION = 1
LAST_VERIFIED_FILE = "last-verified-backup.json"


class BackupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_path(backup_path: Path) -> Path:
    return backup_path.with_name(f"{backup_path.name}.metadata.json")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _schema_metadata(connection: sqlite3.Connection) -> dict[str, Any]:
    state = assert_schema(connection)
    rows = [
        [int(row["version"]), str(row["checksum"])]
        for row in connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        )
    ]
    return {
        **state,
        "manifestSha256": hashlib.sha256(dumps(rows).encode("ascii")).hexdigest(),
    }


def _database_metadata(connection: sqlite3.Connection) -> dict[str, Any]:
    quick_rows = [str(row[0]) for row in connection.execute("PRAGMA quick_check")]
    foreign_key_errors = len(list(connection.execute("PRAGMA foreign_key_check")))
    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    unbalanced = 0
    if {"financial_transactions", "transaction_entries"} <= tables:
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
    return {
        "quickCheck": quick_rows,
        "foreignKeyErrors": foreign_key_errors,
        "unbalancedTransactions": unbalanced,
    }


def _season_metadata(connection: sqlite3.Connection) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT id,number,status,current_tick,current_day FROM seasons ORDER BY number DESC LIMIT 1"
    ).fetchone()
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "number": int(row["number"]),
        "status": str(row["status"]),
        "tick": int(row["current_tick"]),
        "day": int(row["current_day"]),
    }


def _inspect_database(path: Path) -> dict[str, Any]:
    connection = connect(path, readonly=True)
    try:
        return {
            "schema": _schema_metadata(connection),
            "database": _database_metadata(connection),
            "season": _season_metadata(connection),
        }
    finally:
        connection.close()


def _assert_clean_database(metadata: dict[str, Any]) -> None:
    database = metadata["database"]
    if database["quickCheck"] != ["ok"]:
        raise BackupError("backup database quick_check failed")
    if database["foreignKeyErrors"]:
        raise BackupError("backup database has foreign-key errors")
    if database["unbalancedTransactions"]:
        raise BackupError("backup database has unbalanced transactions")


def create_backup(settings: Settings, output: Path | None = None) -> dict[str, Any]:
    settings.ensure_directories()
    if output is None:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = settings.data_dir / "backups" / f"krabville-{stamp}.db"
    output = output.expanduser().resolve()
    if output == settings.database_path.resolve():
        raise BackupError("backup output cannot replace the live database")
    metadata_path = _metadata_path(output)
    if output.exists() or metadata_path.exists():
        raise BackupError("backup output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    try:
        temporary.unlink(missing_ok=True)
        source = open_database(settings, readonly=True)
        try:
            destination = sqlite3.connect(temporary)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)

    inspection = _inspect_database(output)
    _assert_clean_database(inspection)
    metadata = {
        "metadataVersion": METADATA_VERSION,
        "createdAt": now_iso(),
        "release": {"version": __version__, "commit": settings.release_commit},
        "file": {
            "name": output.name,
            "bytes": output.stat().st_size,
            "sha256": _sha256(output),
        },
        **inspection,
    }
    _write_json(metadata_path, metadata)
    return verify_backup(settings, output)


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BackupError("backup metadata is missing or invalid") from error
    if not isinstance(value, dict) or value.get("metadataVersion") != METADATA_VERSION:
        raise BackupError("backup metadata version is unsupported")
    required = {"createdAt", "release", "file", "schema", "database", "season"}
    if not required <= value.keys():
        raise BackupError("backup metadata is missing required fields")
    try:
        created_at = dt.datetime.fromisoformat(str(value["createdAt"]))
        release = value["release"]
        version = str(release["version"])
        commit = str(release["commit"])
    except (KeyError, TypeError, ValueError) as error:
        raise BackupError("backup release metadata is invalid") from error
    if (
        created_at.utcoffset() != dt.timedelta(0)
        or not 1 <= len(version) <= 32
        or not 1 <= len(commit) <= 64
    ):
        raise BackupError("backup release metadata is invalid")
    return value


def verify_backup(
    settings: Settings,
    backup_path: Path,
    *,
    record: bool = True,
) -> dict[str, Any]:
    backup_path = backup_path.expanduser().resolve()
    if not backup_path.is_file():
        raise BackupError("backup database is missing")
    metadata_path = _metadata_path(backup_path)
    expected = _load_metadata(metadata_path)
    actual = {
        "file": {
            "name": backup_path.name,
            "bytes": backup_path.stat().st_size,
            "sha256": _sha256(backup_path),
        },
        **_inspect_database(backup_path),
    }
    for key in ("file", "schema", "database", "season"):
        if expected.get(key) != actual[key]:
            raise BackupError(f"backup {key} metadata does not match")
    _assert_clean_database(actual)

    result = {
        **expected,
        "verifiedAt": now_iso(),
        "backup": str(backup_path),
        "metadata": str(metadata_path),
    }
    if record:
        _write_json(
            settings.data_dir / LAST_VERIFIED_FILE,
            {
                "available": True,
                "verifiedAt": result["verifiedAt"],
                "createdAt": expected["createdAt"],
                "file": expected["file"],
                "schema": expected["schema"],
                "season": expected["season"],
            },
        )
    return result


def last_verified_backup(settings: Settings) -> dict[str, Any]:
    path = settings.data_dir / LAST_VERIFIED_FILE
    if not path.is_file():
        return {"available": False}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        verified_at = str(value["verifiedAt"])
        created_at = str(value["createdAt"])
        dt.datetime.fromisoformat(verified_at)
        dt.datetime.fromisoformat(created_at)
        size = int(value["file"]["bytes"])
        schema_version = int(value["schema"]["version"])
        if size < 0 or schema_version < 1:
            raise ValueError("invalid backup status values")
        season = value.get("season")
        safe_season = None
        if isinstance(season, dict):
            status = str(season["status"])
            if status not in {"draft", "running", "paused", "closing", "complete"}:
                raise ValueError("invalid season status")
            safe_season = {
                "number": int(season["number"]),
                "status": status,
                "tick": int(season["tick"]),
                "day": int(season["day"]),
            }
        return {
            "available": value.get("available") is True,
            "verifiedAt": verified_at,
            "createdAt": created_at,
            "bytes": size,
            "schema": schema_version,
            "season": safe_season,
        }
    except (KeyError, OSError, TypeError, ValueError):
        return {"available": False}


def restore_dry_run(settings: Settings, backup_path: Path) -> dict[str, Any]:
    verified = verify_backup(settings, backup_path, record=False)
    settings.ensure_directories()
    with tempfile.TemporaryDirectory(
        prefix=".restore-", dir=settings.data_dir
    ) as directory:
        root = Path(directory)
        restored = root / "krabville.db"
        shutil.copy2(backup_path, restored)
        scratch = replace(
            settings,
            data_dir=root,
            database_path=restored,
            report_dir=root / "reports",
            control_socket=root / "control.sock",
            fake_provider=True,
            auto_continue=False,
            call_limit=max(settings.call_limit, 1_000_000),
            token_guard=max(settings.token_guard, 2_000_000_000),
        )
        connection = open_database(scratch)
        try:
            from .api import _state

            public_state = _state(connection, scratch)
            season = connection.execute(
                "SELECT * FROM seasons ORDER BY number DESC LIMIT 1"
            ).fetchone()
            if not season:
                start_season(connection, seed_hex="00" * 32)
                season = connection.execute(
                    "SELECT * FROM seasons ORDER BY number DESC LIMIT 1"
                ).fetchone()
            elif season["status"] != "running":
                replay_target = max(2, int(season["target_ticks"]))
                replay_tick = max(
                    0,
                    min(int(season["current_tick"]), replay_target - 2),
                )
                connection.execute(
                    """
                    UPDATE seasons SET status='running',model_locked=0,
                      current_tick=?,target_ticks=?,current_day=?,world_minutes=?,
                      completed_at=NULL,completion_reason=''
                    WHERE id=?
                    """,
                    (
                        replay_tick,
                        replay_target,
                        replay_tick // TICKS_PER_DAY,
                        replay_tick * 5,
                        season["id"],
                    ),
                )
                connection.commit()
                season = connection.execute(
                    "SELECT * FROM seasons WHERE id=?", (season["id"],)
                ).fetchone()
            tick_before = int(season["current_tick"])
            advanced = advance_tick(connection)
            tick_after = int(
                connection.execute(
                    "SELECT current_tick FROM seasons WHERE id=?", (season["id"],)
                ).fetchone()[0]
            )
            if not advanced.get("advanced") or tick_after != tick_before + 1:
                raise BackupError("disposable restore did not advance one tick")
            created = now_iso()
            probe_id = int(
                connection.execute(
                    """
                    INSERT INTO model_jobs(
                      season_id,day,tick,kind,priority,status,context_json,
                      created_at,updated_at
                    ) VALUES(?,?,?,'season_opener',-100,'queued',?,?,?)
                    """,
                    (
                        season["id"],
                        int(season["current_day"]),
                        tick_after,
                        dumps({"restoreProbe": True}),
                        created,
                        created,
                    ),
                ).lastrowid
            )
            connection.commit()
            if not process_one(connection, scratch, FakeProvider()):
                raise BackupError("disposable fake-provider job was not processed")
            probe = connection.execute(
                """
                SELECT job.status,COALESCE(SUM(usage.total_tokens),0) total_tokens
                FROM model_jobs job LEFT JOIN model_usage usage ON usage.job_id=job.id
                WHERE job.id=? GROUP BY job.id
                """,
                (probe_id,),
            ).fetchone()
            if not probe or probe["status"] != "complete":
                raise BackupError("disposable fake-provider job did not complete")
            after = {
                "schema": _schema_metadata(connection),
                "database": _database_metadata(connection),
                "season": _season_metadata(connection),
            }
            _assert_clean_database(after)
        finally:
            connection.close()
    return {
        "dryRun": True,
        "backupVerifiedAt": verified["verifiedAt"],
        "publicState": {
            "ok": bool(public_state.get("ok")),
            "schemaVersion": int(public_state.get("schemaVersion", 0)),
        },
        "replay": {
            "tickBefore": tick_before,
            "tickAfter": tick_after,
            "provider": "fake",
            "providerResult": True,
            "providerTokens": int(probe["total_tokens"]),
        },
        "database": after["database"],
    }
