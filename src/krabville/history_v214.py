from __future__ import annotations

import sqlite3
from typing import Any

from .db import dumps, loads, now_iso


TICKS_PER_DAY = 288
DEPENDENT_STAGES = {"baby", "child"}


def finalize_day_goals(
    connection: sqlite3.Connection,
    season_id: int,
    day: int,
) -> dict[str, int]:
    start = day * TICKS_PER_DAY
    end = start + TICKS_PER_DAY
    completed = deferred = 0
    goals = list(
        connection.execute(
            """
            SELECT * FROM goals
            WHERE season_id=? AND scope='daily' AND created_tick>=? AND created_tick<?
              AND status='active'
            ORDER BY id
            """,
            (season_id, start, end),
        )
    )
    for goal in goals:
        activity_ids = [
            int(row[0])
            for row in connection.execute(
                """
                SELECT id FROM activities
                WHERE season_id=? AND resident_id=? AND tick>=? AND tick<?
                ORDER BY id LIMIT 12
                """,
                (season_id, goal["resident_id"], start, end),
            )
        ]
        commitment_ids = [
            int(row[0])
            for row in connection.execute(
                """
                SELECT cc.id FROM communication_commitments cc
                JOIN communications c ON c.id=cc.communication_id
                WHERE c.season_id=? AND cc.resident_id=? AND cc.status='completed'
                  AND cc.completed_tick>=? AND cc.completed_tick<?
                ORDER BY cc.id LIMIT 12
                """,
                (season_id, goal["resident_id"], start, end),
            )
        ]
        evidence: dict[str, Any] = {
            "activityIds": activity_ids,
            "commitmentIds": commitment_ids,
        }
        is_complete = bool(activity_ids or commitment_ids)
        connection.execute(
            """
            UPDATE goals SET status=?,progress=?,completed_tick=?,evidence_json=?
            WHERE id=?
            """,
            (
                "complete" if is_complete else "deferred",
                100 if is_complete else int(goal["progress"]),
                end - 1 if is_complete else None,
                dumps(evidence),
                goal["id"],
            ),
        )
        if is_complete:
            completed += 1
        else:
            deferred += 1
    return {"completed": completed, "deferred": deferred}


def finalize_season_goals(connection: sqlite3.Connection, season_id: int) -> dict[str, int]:
    completed = deferred = 0
    for goal in connection.execute(
        """
        SELECT * FROM goals
        WHERE season_id=? AND scope='seasonal' AND status='active'
        ORDER BY id
        """,
        (season_id,),
    ):
        activity_ids = [
            int(row[0])
            for row in connection.execute(
                """
                SELECT id FROM activities
                WHERE season_id=? AND resident_id=? ORDER BY id LIMIT 24
                """,
                (season_id, goal["resident_id"]),
            )
        ]
        commitment_ids = [
            int(row[0])
            for row in connection.execute(
                """
                SELECT cc.id FROM communication_commitments cc
                JOIN communications c ON c.id=cc.communication_id
                WHERE c.season_id=? AND cc.resident_id=? AND cc.status='completed'
                ORDER BY cc.id LIMIT 24
                """,
                (season_id, goal["resident_id"]),
            )
        ]
        evidence_count = len(activity_ids) + len(commitment_ids)
        progress = min(100, evidence_count * 8)
        is_complete = evidence_count >= 7
        connection.execute(
            """
            UPDATE goals SET status=?,progress=?,completed_tick=?,evidence_json=?
            WHERE id=?
            """,
            (
                "complete" if is_complete else "deferred",
                progress,
                2015 if is_complete else None,
                dumps({"activityIds": activity_ids, "commitmentIds": commitment_ids}),
                goal["id"],
            ),
        )
        if is_complete:
            completed += 1
        else:
            deferred += 1
    return {"completed": completed, "deferred": deferred}


def normalize_archive_chapters(connection: sqlite3.Connection) -> int:
    changed = 0
    for season in connection.execute("SELECT id,number,weather_json FROM seasons WHERE number<=2"):
        weather = loads(season["weather_json"], {})
        if weather.get("season") != "spring":
            weather["season"] = "spring"
            connection.execute(
                "UPDATE seasons SET weather_json=? WHERE id=?",
                (dumps(weather), season["id"]),
            )
            changed += 1
        for snapshot in connection.execute(
            "SELECT tick,state_json FROM snapshots WHERE season_id=?",
            (season["id"],),
        ):
            state = loads(snapshot["state_json"], {})
            snapshot_weather = state.get("weather")
            if isinstance(snapshot_weather, dict) and snapshot_weather.get("season") != "spring":
                snapshot_weather["season"] = "spring"
                connection.execute(
                    "UPDATE snapshots SET state_json=? WHERE season_id=? AND tick=?",
                    (dumps(state), season["id"], snapshot["tick"]),
                )
    return changed


def repair_childcare(connection: sqlite3.Connection, season_id: int, tick: int) -> dict[str, int]:
    closed = created = schedules = 0
    obsolete = list(
        connection.execute(
            """
            SELECT arrangement.id FROM childcare_arrangements arrangement
            JOIN resident_lifecycle lifecycle ON lifecycle.resident_id=arrangement.child_resident_id
            WHERE arrangement.status IN ('planned','active')
              AND lifecycle.current_stage NOT IN ('baby','child')
            """
        )
    )
    for row in obsolete:
        connection.execute(
            """
            UPDATE childcare_arrangements
            SET status='ended',ended_season_id=?,ended_tick=? WHERE id=?
            """,
            (season_id, tick, row["id"]),
        )
        closed += 1

    dependents = list(
        connection.execute(
            """
            SELECT lifecycle.resident_id,lifecycle.current_stage,state.household_id
            FROM resident_lifecycle lifecycle
            LEFT JOIN resident_season_state state
              ON state.resident_id=lifecycle.resident_id AND state.season_id=?
            WHERE lifecycle.alive=1 AND lifecycle.current_stage IN ('baby','child')
            ORDER BY lifecycle.resident_id
            """,
            (season_id,),
        )
    )
    household_caregivers: dict[int, int] = {}
    for dependent in dependents:
        caregiver = connection.execute(
            """
            SELECT member.resident_id FROM household_members member
            JOIN resident_lifecycle lifecycle ON lifecycle.resident_id=member.resident_id
            WHERE member.household_id=? AND member.ended_season_id IS NULL
              AND member.resident_id<>? AND lifecycle.alive=1
              AND lifecycle.current_stage IN ('adult','senior')
            ORDER BY member.legal_guardian DESC,member.financially_responsible DESC,member.id
            LIMIT 1
            """,
            (dependent["household_id"], dependent["resident_id"]),
        ).fetchone()
        if caregiver:
            household_caregivers[int(dependent["resident_id"])] = int(caregiver["resident_id"])

    for arrangement in connection.execute(
        """
        SELECT id,arrangement_type FROM childcare_arrangements
        WHERE status='active'
        """
    ):
        if connection.execute(
            "SELECT 1 FROM childcare_schedule WHERE arrangement_id=? LIMIT 1",
            (arrangement["id"],),
        ).fetchone():
            continue
        period = (480, 900) if arrangement["arrangement_type"] == "school" else (0, 1440)
        for day in range(7):
            connection.execute(
                """
                INSERT OR IGNORE INTO childcare_schedule(
                  arrangement_id,day_of_week,start_minute,end_minute
                ) VALUES(?,?,?,?)
                """,
                (arrangement["id"], day, period[0], period[1]),
            )
            schedules += 1

    connection.execute(
        """
        UPDATE resident_season_state
        SET caregiver_coverage_minutes=0,care_state='independent',
            current_caregiver_id=NULL,current_care_provider_id=NULL
        WHERE season_id=? AND life_stage NOT IN ('baby','child')
        """,
        (season_id,),
    )
    day = min(6, tick // TICKS_PER_DAY)
    minute = tick % TICKS_PER_DAY * 5
    for dependent in dependents:
        intervals = [
            (int(row["start_minute"]), int(row["end_minute"]))
            for row in connection.execute(
                """
                SELECT schedule.start_minute,schedule.end_minute
                FROM childcare_schedule schedule
                JOIN childcare_arrangements arrangement ON arrangement.id=schedule.arrangement_id
                WHERE arrangement.child_resident_id=? AND arrangement.status='active'
                  AND schedule.day_of_week=? ORDER BY schedule.start_minute
                """,
                (dependent["resident_id"], day),
            )
        ]
        caregiver_id = household_caregivers.get(int(dependent["resident_id"]))
        if caregiver_id:
            if dependent["current_stage"] == "child":
                intervals.extend(((0, 480), (900, 1440)))
            elif not intervals:
                intervals.append((0, 1440))
        merged: list[list[int]] = []
        for start, end in intervals:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)
        coverage = sum(end - start for start, end in merged)
        active = connection.execute(
            """
            SELECT arrangement.caregiver_resident_id,arrangement.provider_business_id
            FROM childcare_arrangements arrangement
            JOIN childcare_schedule schedule ON schedule.arrangement_id=arrangement.id
            WHERE arrangement.child_resident_id=? AND arrangement.status='active'
              AND schedule.day_of_week=? AND schedule.start_minute<=? AND schedule.end_minute>?
            ORDER BY arrangement.id LIMIT 1
            """,
            (dependent["resident_id"], day, minute, minute),
        ).fetchone()
        connection.execute(
            """
            UPDATE resident_season_state
            SET caregiver_coverage_minutes=?,care_state=?,current_caregiver_id=?,
                current_care_provider_id=?
            WHERE season_id=? AND resident_id=?
            """,
            (
                min(1440, coverage),
                "covered" if coverage == 1440 else "uncovered",
                active["caregiver_resident_id"] if active else caregiver_id,
                active["provider_business_id"] if active else None,
                season_id,
                dependent["resident_id"],
            ),
        )
    return {"closed": closed, "created": created, "scheduleRows": schedules}


def repair_v214(connection: sqlite3.Connection) -> dict[str, Any]:
    epilogues = connection.execute(
        "UPDATE story_ledger SET day=6,phase='epilogue' WHERE day=7"
    ).rowcount
    result: dict[str, Any] = {
        "archiveChapters": normalize_archive_chapters(connection),
        "epilogues": max(0, int(epilogues)),
        "seasons": {},
    }
    for season in connection.execute("SELECT id,number,status,current_tick FROM seasons ORDER BY number"):
        season_id = int(season["id"])
        days = 7 if season["status"] == "complete" else int(season["current_tick"]) // TICKS_PER_DAY
        daily = {"completed": 0, "deferred": 0}
        for day in range(min(7, days)):
            repaired = finalize_day_goals(connection, season_id, day)
            daily["completed"] += repaired["completed"]
            daily["deferred"] += repaired["deferred"]
        seasonal = finalize_season_goals(connection, season_id) if season["status"] == "complete" else {"completed": 0, "deferred": 0}
        care = repair_childcare(connection, season_id, int(season["current_tick"]))
        result["seasons"][str(season["number"])] = {
            "dailyGoals": daily,
            "seasonalGoals": seasonal,
            "care": care,
        }
    connection.execute(
        """
        INSERT OR REPLACE INTO model_circuits(
          season_id,day,job_kind,model,status,consecutive_failures,updated_at
        )
        SELECT jobs.season_id,jobs.day,jobs.kind,usage.model,'closed',0,?
        FROM model_usage usage JOIN model_jobs jobs ON jobs.id=usage.job_id
        GROUP BY jobs.season_id,jobs.day,jobs.kind,usage.model
        """,
        (now_iso(),),
    )
    return result
