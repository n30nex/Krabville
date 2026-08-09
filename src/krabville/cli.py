from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import Settings
from .db import initialize
from .inference import FakeProvider, process_one
from .history_v214 import repair_v214
from .legacy import import_week_one
from .reporter import (
    generate_report,
    rebuild_verified_chronicles,
    verify_archive,
)
from .world import advance_tick, diagnose, queue_conversation_if_needed, start_season


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="krabville-manage")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    start = sub.add_parser("start")
    start.add_argument("--opening-slug")
    tick = sub.add_parser("tick")
    tick.add_argument("--count", type=int, default=1)
    run = sub.add_parser("run-fake-season")
    run.add_argument("--days", type=int, default=7)
    run.add_argument("--seasons", type=int, default=1)
    diagnose_parser = sub.add_parser("diagnose")
    diagnose_parser.add_argument("--json", action="store_true")
    legacy = sub.add_parser("import-week-one")
    legacy.add_argument("--payload", type=Path, required=True)
    legacy.add_argument("--poster", type=Path, required=True)
    report = sub.add_parser("report")
    report.add_argument("--season-id", type=int)
    repair = sub.add_parser("repair-v214")
    repair.add_argument("--seasons", type=int, nargs="*", default=[1, 2])
    return parser


def main() -> None:
    args = _parser().parse_args()
    settings = Settings.from_env()
    connection = initialize(settings)
    def runtime_diagnose():
        return diagnose(
            connection,
            tick_seconds=settings.tick_seconds,
            tick_stale_seconds=settings.tick_stale_seconds,
        )
    try:
        if args.command == "init":
            result = runtime_diagnose()
        elif args.command == "start":
            result = start_season(connection, opening_slug=args.opening_slug)
        elif args.command == "tick":
            result = {}
            for _ in range(max(0, args.count)):
                result = advance_tick(connection)
        elif args.command == "run-fake-season":
            result = {}
            for _ in range(max(1, min(52, args.seasons))):
                latest = connection.execute(
                    "SELECT status FROM seasons ORDER BY number DESC LIMIT 1"
                ).fetchone()
                if not latest or latest["status"] == "complete":
                    start_season(connection)
                target = max(1, min(7, args.days)) * 288
                while True:
                    season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
                    if not season or season["status"] == "complete" or int(season["current_tick"]) >= target:
                        break
                    result = advance_tick(connection)
                    if result.get("advanced") and int(result.get("tick", 0)) % 36 == 0:
                        queue_conversation_if_needed(connection)
                    while process_one(connection, settings, FakeProvider()):
                        pass
                season = connection.execute("SELECT id,status FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
                if season and season["status"] == "complete" and not connection.execute(
                    "SELECT 1 FROM reports WHERE season_id=?", (season["id"],)
                ).fetchone():
                    generate_report(connection, int(season["id"]), settings)
                    connection.commit()
                if not season or season["status"] != "complete":
                    break
            result = runtime_diagnose()
        elif args.command == "diagnose":
            result = runtime_diagnose()
        elif args.command == "import-week-one":
            payload = json.loads(args.payload.read_text(encoding="utf-8"))
            result = {
                "seasonId": import_week_one(
                    connection,
                    payload,
                    poster_source=args.poster,
                    report_dir=settings.report_dir,
                )
            }
        elif args.command == "report":
            season_id = args.season_id
            if not season_id:
                row = connection.execute("SELECT id FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
                if not row:
                    raise SystemExit("no season")
                season_id = int(row["id"])
            result = {"poster": str(generate_report(connection, season_id, settings))}
            connection.commit()
        elif args.command == "repair-v214":
            result = {"repair": repair_v214(connection), "archives": []}
            for number in sorted(set(args.seasons)):
                row = connection.execute(
                    "SELECT id,status FROM seasons WHERE number=?", (number,)
                ).fetchone()
                if not row or row["status"] != "complete":
                    continue
                season_id = int(row["id"])
                rebuild_verified_chronicles(connection, season_id)
                poster = generate_report(connection, season_id, settings)
                result["archives"].append(
                    {**verify_archive(connection, season_id), "poster": str(poster)}
                )
            connection.commit()
        else:
            raise SystemExit(2)
        print(json.dumps(result, indent=None if getattr(args, "json", False) else 2, default=str))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
