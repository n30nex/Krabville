from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import platform
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FRONTEND = ROOT / "frontend"
FIXTURE = ROOT / "tests" / "fixtures" / "krabville-v2.2.1-schema-013.sqlite3.gz"
FIXTURE_SHA256 = "9749386cb96381fb6581fec222db5b222fa18e2af5007779bdc31eb6afc566a5"
DEFAULT_OUTPUT = ROOT / ".qa" / "performance" / "kv23-201-baseline.json"
BASELINE_SOURCE_COMMIT = "d1243a53dc234eef606d2bf7c1a5fcdac5bba6ee"
BASELINE_RUNTIME_SCHEMA = 14

sys.path.insert(0, str(SRC))

from fastapi.testclient import TestClient  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402

from krabville.api import _state, create_app  # noqa: E402
from krabville.config import Settings  # noqa: E402
from krabville.db import initialize  # noqa: E402


class QueryCollector:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def begin(self, statement: str) -> int:
        operation = (
            statement.lstrip().split(None, 1)[0].upper()
            if statement.strip()
            else "UNKNOWN"
        )
        self.entries.append({"operation": operation, "elapsedNs": 0, "rows": 0})
        return len(self.entries) - 1

    def add_elapsed(self, index: int, elapsed_ns: int) -> None:
        self.entries[index]["elapsedNs"] += elapsed_ns

    def add_rows(self, index: int, count: int) -> None:
        self.entries[index]["rows"] += count

    @property
    def elapsed_ms(self) -> float:
        return sum(int(entry["elapsedNs"]) for entry in self.entries) / 1_000_000

    @property
    def operations(self) -> dict[str, int]:
        return dict(
            sorted(Counter(str(entry["operation"]) for entry in self.entries).items())
        )


class ProfiledCursor(sqlite3.Cursor):
    collector: QueryCollector
    entry_index: int

    def execute(self, sql: str, parameters: Any = ()) -> ProfiledCursor:
        self.entry_index = self.collector.begin(sql)
        started = time.perf_counter_ns()
        try:
            return super().execute(sql, parameters)
        finally:
            self.collector.add_elapsed(
                self.entry_index, time.perf_counter_ns() - started
            )

    def fetchone(self) -> sqlite3.Row | None:
        started = time.perf_counter_ns()
        try:
            row = super().fetchone()
        finally:
            self.collector.add_elapsed(
                self.entry_index, time.perf_counter_ns() - started
            )
        if row is not None:
            self.collector.add_rows(self.entry_index, 1)
        return row

    def fetchmany(self, size: int | None = None) -> list[sqlite3.Row]:
        started = time.perf_counter_ns()
        try:
            rows = super().fetchmany() if size is None else super().fetchmany(size)
        finally:
            self.collector.add_elapsed(
                self.entry_index, time.perf_counter_ns() - started
            )
        self.collector.add_rows(self.entry_index, len(rows))
        return rows

    def fetchall(self) -> list[sqlite3.Row]:
        started = time.perf_counter_ns()
        try:
            rows = super().fetchall()
        finally:
            self.collector.add_elapsed(
                self.entry_index, time.perf_counter_ns() - started
            )
        self.collector.add_rows(self.entry_index, len(rows))
        return rows

    def __next__(self) -> sqlite3.Row:
        started = time.perf_counter_ns()
        try:
            row = super().__next__()
        finally:
            self.collector.add_elapsed(
                self.entry_index, time.perf_counter_ns() - started
            )
        self.collector.add_rows(self.entry_index, 1)
        return row


class ProfiledConnection(sqlite3.Connection):
    collector: QueryCollector

    def cursor(self, factory: Any = None) -> sqlite3.Cursor:
        if factory is not None:
            return super().cursor(factory)

        def make_cursor(connection: sqlite3.Connection) -> ProfiledCursor:
            cursor = ProfiledCursor(connection)
            cursor.collector = self.collector
            return cursor

        return super().cursor(make_cursor)

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        return self.cursor().execute(sql, parameters)


def open_profiled(path: Path, collector: QueryCollector) -> ProfiledConnection:
    connection = sqlite3.connect(
        f"file:{path.as_posix()}?mode=ro",
        uri=True,
        timeout=5,
        isolation_level=None,
        factory=ProfiledConnection,
    )
    connection.collector = collector
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    collector.entries.clear()
    return connection


def fixture_settings(root: Path) -> Settings:
    return Settings(
        data_dir=root,
        database_path=root / "krabville.db",
        asset_dir=FRONTEND / "public" / "assets",
        report_dir=root / "reports",
        frontend_dir=FRONTEND / "dist",
        control_socket=root / "control.sock",
        bind_host="127.0.0.1",
        port=0,
        tick_seconds=12.5,
        fake_provider=True,
        primary_model="gpt-5.3-codex-spark",
        primary_reasoning="low",
        fallback_model="gpt-5.6-luna",
        fallback_reasoning="low",
        call_limit=150,
        token_guard=1_500_000,
        inference_timeout=10,
        voter_secret="kv23-201-synthetic-fixture-secret",
        public_origin="http://127.0.0.1",
        auto_continue=False,
        tick_stale_seconds=1_000_000_000,
    )


def materialize_fixture(settings: Settings) -> dict[str, Any]:
    digest = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    if digest != FIXTURE_SHA256:
        raise RuntimeError(f"retained fixture checksum mismatch: {digest}")
    settings.ensure_directories()
    with (
        gzip.open(FIXTURE, "rb") as source,
        settings.database_path.open("wb") as target,
    ):
        shutil.copyfileobj(source, target)
    connection = initialize(settings)
    try:
        season = connection.execute(
            "SELECT number,current_tick FROM seasons ORDER BY number DESC LIMIT 1"
        ).fetchone()
        schema = int(
            connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
                0
            ]
        )
        return {
            "release": "2.2.1",
            "releaseCommit": "f630a9502b029097deeecbbc85b0f74aca4e99f9",
            "fixtureSchema": 13,
            "migratedSchema": schema,
            "season": int(season["number"]),
            "tick": int(season["current_tick"]),
            "sha256": digest,
        }
    finally:
        connection.close()


def summarize(values: list[float], digits: int = 3) -> dict[str, float]:
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )
    p95 = ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]
    return {
        "min": round(ordered[0], digits),
        "median": round(median, digits),
        "p95": round(p95, digits),
        "max": round(ordered[-1], digits),
    }


def profile_state(
    settings: Settings, *, samples: int = 7, warmups: int = 2
) -> dict[str, Any]:
    measurements: list[dict[str, Any]] = []
    payload_shape: dict[str, int] = {}
    operations: dict[str, int] = {}
    for index in range(warmups + samples):
        collector = QueryCollector()
        connection = open_profiled(settings.database_path, collector)
        try:
            started = time.perf_counter_ns()
            payload = _state(connection, settings)
            state_ms = (time.perf_counter_ns() - started) / 1_000_000
            started = time.perf_counter_ns()
            body = JSONResponse(payload).body
            serialization_ms = (time.perf_counter_ns() - started) / 1_000_000
        finally:
            connection.close()
        if index < warmups:
            continue
        operations = collector.operations
        payload_shape = {
            "residents": len(payload.get("residents", [])),
            "events": len(payload.get("events", [])),
            "properties": len(payload.get("properties", [])),
            "accounts": len(payload.get("economy", {}).get("accounts", [])),
        }
        measurements.append(
            {
                "queryCount": len(collector.entries),
                "databaseMs": collector.elapsed_ms,
                "stateBuildMs": state_ms,
                "serializationMs": serialization_ms,
                "rawBytes": len(body),
                "gzipBytes": len(gzip.compress(body, compresslevel=9, mtime=0)),
            }
        )

    route_ms: list[float] = []
    route_raw: list[float] = []
    route_gzip: list[float] = []
    with TestClient(create_app(settings), base_url="http://testserver") as client:
        client.get("/api/v3/state").raise_for_status()
        for _ in range(samples):
            started = time.perf_counter_ns()
            response = client.get("/api/v3/state")
            route_ms.append((time.perf_counter_ns() - started) / 1_000_000)
            response.raise_for_status()
            route_raw.append(float(len(response.content)))
            route_gzip.append(
                float(len(gzip.compress(response.content, compresslevel=9, mtime=0)))
            )

    return {
        "samples": samples,
        "warmups": warmups,
        "payloadShape": payload_shape,
        "queryCount": summarize(
            [float(value["queryCount"]) for value in measurements], digits=1
        ),
        "queryOperations": operations,
        "databaseMs": summarize([value["databaseMs"] for value in measurements]),
        "stateBuildMs": summarize([value["stateBuildMs"] for value in measurements]),
        "serializationMs": summarize(
            [value["serializationMs"] for value in measurements]
        ),
        "routeRoundTripMs": summarize(route_ms),
        "rawBytes": summarize(route_raw, digits=1),
        "gzipBytes": summarize(route_gzip, digits=1),
        "gzipRatio": round(sum(route_gzip) / sum(route_raw), 4),
    }


def gzip_size(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), compresslevel=9, mtime=0))


def asset_inventory(dist: Path) -> dict[str, Any]:
    files = []
    for path in sorted(value for value in dist.rglob("*") if value.is_file()):
        relative = path.relative_to(dist).as_posix()
        files.append(
            {
                "path": f"/{relative}",
                "rawBytes": path.stat().st_size,
                "gzipBytes": gzip_size(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return {
        "fileCount": len(files),
        "rawBytes": sum(item["rawBytes"] for item in files),
        "gzipBytes": sum(item["gzipBytes"] for item in files),
        "files": files,
    }


def initial_transfer(
    inventory: dict[str, Any], browser: dict[str, Any]
) -> dict[str, Any]:
    by_path = {item["path"]: item for item in inventory["files"]}
    requested = {"/index.html"}
    for resource in browser.get("initialResources", []):
        path = unquote(urlsplit(str(resource.get("path", ""))).path)
        if path in by_path:
            requested.add(path)
    files = [by_path[path] for path in sorted(requested) if path in by_path]
    missing = sorted(path for path in requested if path not in by_path)
    return {
        "fileCount": len(files),
        "rawBytes": sum(item["rawBytes"] for item in files),
        "gzipBytes": sum(item["gzipBytes"] for item in files),
        "missingPaths": missing,
        "files": files,
    }


def executable_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (result.stdout or result.stderr).strip().splitlines()[0]


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout.strip()


def assert_baseline_source() -> None:
    current = git_commit()
    if current != BASELINE_SOURCE_COMMIT:
        raise RuntimeError(
            "KV23-201 must run from the pinned v2.2 source worktree "
            f"{BASELINE_SOURCE_COMMIT}; current HEAD is {current}"
        )


def assert_baseline_schema(fixture: dict[str, Any]) -> None:
    current = int(fixture["migratedSchema"])
    if current != BASELINE_RUNTIME_SCHEMA:
        raise RuntimeError(
            "KV23-201 must measure runtime schema "
            f"{BASELINE_RUNTIME_SCHEMA}; fixture migrated to schema {current}"
        )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_for_url(process: subprocess.Popen[str], url: str, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    last_error = "server did not answer"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"benchmark server exited with {process.returncode}")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"benchmark server did not become ready: {last_error}")


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def browser_profile(settings: Settings, duration_seconds: int) -> dict[str, Any]:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required for the browser baseline")
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KRABVILLE_")
    }
    env.update(
        {
            "PYTHONPATH": str(SRC),
            "KRABVILLE_DATA_DIR": str(settings.data_dir),
            "KRABVILLE_DATABASE": str(settings.database_path),
            "KRABVILLE_REPORT_DIR": str(settings.report_dir),
            "KRABVILLE_CONTROL_SOCKET": str(settings.control_socket),
            "KRABVILLE_ASSET_DIR": str(settings.asset_dir),
            "KRABVILLE_FRONTEND_DIR": str(settings.frontend_dir),
            "KRABVILLE_BIND": "127.0.0.1",
            "KRABVILLE_PORT": str(port),
            "KRABVILLE_PUBLIC_ORIGIN": url,
            "KRABVILLE_FAKE_PROVIDER": "true",
            "KRABVILLE_AUTO_CONTINUE": "false",
            "KRABVILLE_TICK_STALE_SECONDS": "1000000000",
            "KRABVILLE_VOTER_SECRET": "kv23-201-browser-fixture-secret",
        }
    )
    output = settings.data_dir / "browser-baseline.json"
    log_path = settings.data_dir / "browser-server.log"
    with log_path.open("w", encoding="utf-8", errors="replace") as server_log:
        server = subprocess.Popen(
            [sys.executable, "-m", "krabville.api"],
            cwd=ROOT,
            env=env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_for_url(server, f"{url}/livez")
            subprocess.run(
                [
                    node,
                    "scripts/profile-performance.mjs",
                    "--url",
                    url,
                    "--duration-seconds",
                    str(duration_seconds),
                    "--output",
                    str(output),
                ],
                cwd=FRONTEND,
                check=True,
            )
        finally:
            stop_process(server)
    return json.loads(output.read_text(encoding="utf-8"))


def build_frontend() -> None:
    npm = shutil.which("npm")
    if not npm:
        raise RuntimeError("npm is required to build the frontend baseline")
    subprocess.run([npm, "run", "build"], cwd=FRONTEND, check=True)


def write_report(
    output: Path,
    *,
    fixture: dict[str, Any],
    state: dict[str, Any],
    assets: dict[str, Any],
    browser: dict[str, Any] | None,
    duration_seconds: int,
) -> dict[str, Any]:
    transfer = initial_transfer(assets, browser) if browser else None
    report = {
        "schemaVersion": 1,
        "ticket": "KV23-201",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sourceCommit": git_commit(),
        "fixture": fixture,
        "protocol": {
            "stateSamples": state["samples"],
            "stateWarmups": state["warmups"],
            "viewport": {"width": 1366, "height": 768},
            "browserSoakSeconds": duration_seconds if browser else 0,
            "budgetsEnforced": False,
        },
        "environment": {
            "python": sys.version.split()[0],
            "node": executable_version([shutil.which("node") or "node", "--version"]),
            "platform": sys.platform,
            "machine": platform.machine(),
        },
        "state": state,
        "frontendBuild": assets,
        "initialTransfer": transfer,
        "browser": browser,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record the KVsim v2.2 performance baseline"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--browser-duration-seconds", type=int, default=600)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-browser", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.samples < 1 or args.warmups < 0 or args.browser_duration_seconds < 0:
        raise SystemExit(
            "samples must be positive; warmups and browser duration cannot be negative"
        )
    assert_baseline_source()
    if not args.skip_build:
        build_frontend()
    if not (FRONTEND / "dist" / "index.html").exists():
        raise SystemExit("frontend/dist is missing; run without --skip-build")

    with tempfile.TemporaryDirectory(prefix="krabville-kv23-201-") as temporary:
        settings = fixture_settings(Path(temporary))
        fixture = materialize_fixture(settings)
        assert_baseline_schema(fixture)
        state = profile_state(settings, samples=args.samples, warmups=args.warmups)
        browser = (
            None
            if args.skip_browser
            else browser_profile(settings, args.browser_duration_seconds)
        )
        assets = asset_inventory(FRONTEND / "dist")
        report = write_report(
            args.output.resolve(),
            fixture=fixture,
            state=state,
            assets=assets,
            browser=browser,
            duration_seconds=args.browser_duration_seconds,
        )

    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "queryCountMedian": report["state"]["queryCount"]["median"],
                "stateGzipBytesMedian": report["state"]["gzipBytes"]["median"],
                "initialTransferGzipBytes": (
                    report["initialTransfer"]["gzipBytes"]
                    if report["initialTransfer"]
                    else None
                ),
                "browserSoakSeconds": report["protocol"]["browserSoakSeconds"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
