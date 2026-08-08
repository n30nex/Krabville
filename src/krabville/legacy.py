from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .db import dumps, initialize_resident_state, now_iso, transaction


def import_week_one(
    connection: sqlite3.Connection,
    payload: dict[str, Any],
    *,
    poster_source: Path | None = None,
    report_dir: Path | None = None,
) -> int:
    existing = connection.execute("SELECT id FROM seasons WHERE number=1").fetchone()
    if existing:
        return int(existing["id"])
    run = payload.get("run", {})
    world = payload.get("world", {})
    report = world.get("week_report", {})
    now = now_iso()
    seed = "legacy-week-one-no-replay-seed"
    with transaction(connection, immediate=True):
        cursor = connection.execute("""
            INSERT INTO seasons(number,status,created_at,started_at,completed_at,seed_hex,
              seed_commitment,seed_revealed,current_tick,current_day,world_minutes,target_ticks,
              model_locked,model_degraded,weather_json)
            VALUES(1,'complete',?,?,?,?,?,1,1008,6,1435,1008,1,0,?)
            """, (now, now, now, seed, "legacy-week-one", dumps(world.get("weather", {}))))
        season_id = int(cursor.lastrowid)
        initialize_resident_state(connection, season_id)
        resident_ids = {
            row["name"]: int(row["id"])
            for row in connection.execute("SELECT id,name FROM residents")
        }
        for resident in payload.get("residents", [])[:12]:
            resident_id = resident_ids.get(str(resident.get("name", "")))
            if not resident_id:
                continue
            thought = str(resident.get("thought", "")).strip()
            if not thought or thought.lower() == "this is blank":
                thought = str(resident.get("about", "A familiar week has changed the town."))
            connection.execute(
                """
                UPDATE resident_state SET activity=?,public_thought=?,intention=?,reflection=?,mood=?
                WHERE season_id=? AND resident_id=?
                """,
                (
                    str(resident.get("action", "remembering Week One"))[:240],
                    thought[:280],
                    str(resident.get("routine", "Continue a familiar routine."))[:240],
                    str(resident.get("about", "Week One became part of the town's memory."))[:360],
                    str(resident.get("mood", "steady"))[:40],
                    season_id,
                    resident_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO memories(
                  season_id,resident_id,kind,content,tags,salience,created_tick,durable
                ) VALUES(?,?,?,?,?,?,?,1)
                """,
                (
                    season_id,
                    resident_id,
                    "legacy_profile",
                    str(resident.get("about", "A Week One resident of Krabville."))[:500],
                    "legacy profile week-one",
                    8,
                    1008,
                ),
            )
        for relationship in world.get("relationships", []):
            left = resident_ids.get(str(relationship.get("a", "")))
            right = resident_ids.get(str(relationship.get("b", "")))
            if not left or not right or left == right:
                continue
            low, high = sorted((left, right))
            score = int(relationship.get("score", 0))
            interactions = max(0, int(relationship.get("interactions", 0)))
            connection.execute(
                """
                UPDATE relationships SET affinity=?,trust=?,tension=?,familiarity=?,interactions=?
                WHERE season_id=? AND resident_a=? AND resident_b=?
                """,
                (
                    max(0, score * 4),
                    max(0, score * 2),
                    max(0, -score * 4),
                    min(100, 10 + interactions * 3),
                    interactions,
                    season_id,
                    low,
                    high,
                ),
            )
        for day in world.get("days", [])[:7]:
            event = day.get("event", {})
            connection.execute("""
                INSERT INTO town_events(season_id,day,tick,slug,title,category,summary,prop,
                  strange,participants_json,source,relationship_delta_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """, (season_id, int(day.get("day", 0)), int(day.get("day", 0))*144,
                str(event.get("title", "legacy-event")).lower().replace(" ", "-")[:80],
                str(event.get("title", "Legacy event"))[:160], "legacy",
                str(event.get("summary", ""))[:600], "legacy-prop", int(bool(event.get("strange"))),
                dumps(event.get("participants", [])), "legacy", dumps({"change": event.get("relationship_change", 0)})))
            connection.execute("""
                INSERT INTO daily_chronicles(season_id,day,title,narrative,statistics_json,created_at)
                VALUES(?,?,?,?,?,?)
                """, (season_id, int(day.get("day", 0)), f"Day {int(day.get('day', 0))+1}: {event.get('title', 'Around the Lagoon')}",
                str(day.get("narrative", ""))[:1200], dumps({"activities": day.get("activity_changes", 0), "conversations": day.get("conversations", 0)}), now))
        poster_path = ""
        if poster_source and report_dir and poster_source.exists():
            report_dir.mkdir(parents=True, exist_ok=True)
            target = report_dir / "season-001.png"
            shutil.copy2(poster_source, target)
            poster_path = str(target)
        connection.execute("""
            INSERT INTO reports(season_id,headline,narrative,poster_path,statistics_json,created_at)
            VALUES(?,?,?,?,?,?)
            """, (season_id, str(report.get("headline", "Krabville Week One"))[:180],
            str(report.get("narrative", ""))[:5000], poster_path,
            dumps({"activities": report.get("activity_changes", 0), "conversations": report.get("conversations", 0), "strangeDays": report.get("strange_days", 0), "modelAttempts": report.get("model_calls", 0)}), now))
    return season_id
