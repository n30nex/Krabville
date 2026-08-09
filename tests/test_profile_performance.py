from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path

import pytest

from tools import profile_performance


def test_profiled_connection_counts_queries_and_fetch_work(tmp_path: Path) -> None:
    database = tmp_path / "profile.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE sample(value INTEGER)")
    connection.executemany("INSERT INTO sample(value) VALUES (?)", [(1,), (2,), (3,)])
    connection.commit()
    connection.close()

    collector = profile_performance.QueryCollector()
    profiled = profile_performance.open_profiled(database, collector)
    try:
        assert [
            row[0]
            for row in profiled.execute("SELECT value FROM sample ORDER BY value")
        ] == [1, 2, 3]
        assert profiled.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 3
    finally:
        profiled.close()

    assert len(collector.entries) == 2
    assert collector.operations == {"SELECT": 2}
    assert sum(entry["rows"] for entry in collector.entries) == 4
    assert collector.elapsed_ms >= 0


def test_asset_inventory_and_initial_transfer_are_content_based(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<main>Krabville</main>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('ready')", encoding="utf-8")

    inventory = profile_performance.asset_inventory(dist)
    transfer = profile_performance.initial_transfer(
        inventory,
        {
            "initialResources": [
                {"path": "/assets/app.js"},
                {"path": "/api/v3/state"},
            ]
        },
    )

    assert inventory["fileCount"] == 2
    assert transfer["fileCount"] == 2
    assert transfer["missingPaths"] == []
    assert transfer["rawBytes"] == sum(
        len(path.read_bytes()) for path in (dist / "index.html", assets / "app.js")
    )
    assert transfer["gzipBytes"] == sum(
        len(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0))
        for path in (dist / "index.html", assets / "app.js")
    )


def test_report_is_lf_only_and_omits_runtime_paths(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(profile_performance, "git_commit", lambda: "a" * 40)
    monkeypatch.setattr(
        profile_performance, "executable_version", lambda _command: "v1"
    )
    output = tmp_path / "baseline.json"

    profile_performance.write_report(
        output,
        fixture={"release": "2.2.1"},
        state={"samples": 1, "warmups": 0},
        assets={"fileCount": 0, "rawBytes": 0, "gzipBytes": 0, "files": []},
        browser=None,
        duration_seconds=0,
    )

    content = output.read_bytes()
    assert b"\r" not in content
    assert str(tmp_path).encode() not in content


def test_retained_v22_state_profile_is_runnable_and_stable(tmp_path: Path) -> None:
    settings = profile_performance.fixture_settings(tmp_path / "runtime")
    fixture = profile_performance.materialize_fixture(settings)
    result = profile_performance.profile_state(settings, samples=2, warmups=1)

    assert fixture["fixtureSchema"] == 13
    assert fixture["tick"] == 44
    assert result["payloadShape"]["residents"] == 12
    assert result["queryCount"]["min"] == result["queryCount"]["max"]
    assert result["queryCount"]["min"] > 0
    assert result["rawBytes"]["median"] > result["gzipBytes"]["median"] > 0
    assert result["databaseMs"]["median"] >= 0
    assert result["serializationMs"]["median"] >= 0
    assert json.dumps(result, sort_keys=True)


def test_historical_baseline_requires_exact_source_and_runtime_schema(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        profile_performance,
        "git_commit",
        lambda: profile_performance.BASELINE_SOURCE_COMMIT,
    )
    profile_performance.assert_baseline_source()
    profile_performance.assert_baseline_schema(
        {"migratedSchema": profile_performance.BASELINE_RUNTIME_SCHEMA}
    )

    monkeypatch.setattr(profile_performance, "git_commit", lambda: "f" * 40)
    with pytest.raises(RuntimeError, match="pinned v2.2 source worktree"):
        profile_performance.assert_baseline_source()
    with pytest.raises(RuntimeError, match="runtime schema 14"):
        profile_performance.assert_baseline_schema({"migratedSchema": 15})
