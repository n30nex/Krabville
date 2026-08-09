from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Cookie, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .backup import last_verified_backup
from .commerce_v2 import item_asset_index
from .config import Settings
from .content import LOCATION_POINTS
from .db import (
    applied_schema_version,
    connect,
    dumps,
    loads,
    now_iso,
    open_database,
    required_schema_version,
    transaction,
)
from .public_events import PUBLIC_EVENT_KINDS, serialize_public_event
from .security import VoteSecurity, new_csrf
from .runtime_v2 import account_balance, population_target_for_season
from .world import _season_chapter, _weather, diagnose


class VoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choiceId: str = Field(min_length=1, max_length=8, pattern=r"^[A-Z0-9_-]+$")
    csrfToken: str = Field(min_length=20, max_length=128)


def _public_label(value: Any, default: str = "Not available") -> str:
    text = str(value or "").strip().replace("_", " ").replace("-", " ")
    return text.title() if text else default


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    """Return a table's columns without making optional migrations mandatory."""
    if not table.replace("_", "").isalnum():
        return set()
    try:
        return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}
    except sqlite3.OperationalError:
        return set()


def _row_value(row: sqlite3.Row, *names: str, default: Any = None) -> Any:
    keys = set(row.keys())
    return next((row[name] for name in names if name in keys), default)


def _optional_rows(
    connection: sqlite3.Connection,
    table: str,
    where: str = "",
    parameters: tuple[Any, ...] = (),
) -> list[sqlite3.Row]:
    if not _table_columns(connection, table):
        return []
    try:
        return list(connection.execute(f"SELECT * FROM {table} {where}", parameters))
    except sqlite3.OperationalError:
        return []


def _gini(values: list[int]) -> float:
    non_negative = sorted(max(0, value) for value in values)
    total = sum(non_negative)
    if not non_negative or total == 0:
        return 0.0
    weighted = sum((index + 1) * value for index, value in enumerate(non_negative))
    return round((2 * weighted) / (len(non_negative) * total) - (len(non_negative) + 1) / len(non_negative), 3)


def _season(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()


def _public_weather(season: sqlite3.Row) -> dict[str, Any]:
    weather = loads(season["weather_json"], {})
    season_number = int(season["number"])
    if weather.get("season") != _season_chapter(season_number):
        return _weather(season["seed_hex"], int(season["current_day"]), season_number)
    return weather


def _usage(
    connection: sqlite3.Connection,
    season_id: int,
    settings: Settings,
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COUNT(*) calls,COALESCE(SUM(total_tokens),0) total,
          COALESCE(SUM(input_tokens),0) input,COALESCE(SUM(cached_input_tokens),0) cached,
          COALESCE(SUM(output_tokens),0) output,COALESCE(SUM(reasoning_tokens),0) reasoning
        FROM model_usage WHERE season_id=?
        """,
        (season_id,),
    ).fetchone()
    models = {
        item["model"]: {"calls": int(item["calls"]), "tokens": int(item["tokens"])}
        for item in connection.execute(
            "SELECT model,COUNT(*) calls,COALESCE(SUM(total_tokens),0) tokens FROM model_usage WHERE season_id=? GROUP BY model",
            (season_id,),
        )
    }
    return {
        "calls": int(row["calls"]),
        "callLimit": settings.call_limit,
        "totalTokens": int(row["total"]),
        "tokenGuard": settings.token_guard,
        "inputTokens": int(row["input"]),
        "cachedInputTokens": int(row["cached"]),
        "outputTokens": int(row["output"]),
        "reasoningTokens": int(row["reasoning"]),
        "models": models,
    }


def _poll_payload(connection: sqlite3.Connection, season_id: int) -> dict[str, Any] | None:
    poll = connection.execute(
        "SELECT * FROM polls WHERE season_id=? ORDER BY day DESC LIMIT 1", (season_id,)
    ).fetchone()
    if not poll:
        return None
    options = [
        {
            "choiceId": row["choice_id"],
            "title": row["title"],
            "category": row["category"],
            "preview": row["preview"],
            "votes": int(row["votes"]),
            "winner": int(row["id"]) == int(poll["winner_option_id"] or 0),
        }
        for row in connection.execute(
            "SELECT * FROM poll_options WHERE poll_id=? ORDER BY choice_id", (poll["id"],)
        )
    ]
    total_votes = sum(int(option["votes"]) for option in options)
    winner = next((option for option in options if option["winner"]), None)
    poll_columns = set(poll.keys())
    stored_source = str(poll["selection_source"]) if "selection_source" in poll_columns else "pending"
    selection_source = None
    if poll["status"] in {"closed", "applied"} and winner:
        selection_source = (
            "visitors" if stored_source == "visitor"
            else stored_source if stored_source == "town"
            else "visitors" if total_votes else "town"
        )
    return {
        "id": int(poll["id"]),
        "day": int(poll["day"]),
        "status": poll["status"],
        "opensTick": int(poll["opens_tick"]),
        "closesTick": int(poll["closes_tick"]),
        "options": options,
        "totalVotes": total_votes,
        "selectionSource": selection_source,
        "winnerLabel": (
            "Visitors selected" if selection_source == "visitors"
            else "Town selected" if selection_source == "town"
            else None
        ),
    }


def _decision_factors(connection: sqlite3.Connection, decision_id: int) -> dict[int, list[dict[str, Any]]]:
    if not decision_id or not _table_columns(connection, "decision_factors"):
        return {}
    factors: dict[int, list[dict[str, Any]]] = {}
    for row in connection.execute(
        """
        SELECT option_rank,factor_kind,factor_key,weight,explanation
        FROM decision_factors WHERE decision_id=? ORDER BY option_rank,ABS(weight) DESC
        """,
        (decision_id,),
    ):
        factors.setdefault(int(row["option_rank"]), []).append({
            "kind": str(row["factor_kind"]),
            "key": str(row["factor_key"]),
            "weight": round(float(row["weight"]), 2),
            "explanation": str(row["explanation"] or ""),
        })
    return factors


def _goal_evidence(
    connection: sqlite3.Connection,
    season_id: int,
    resident_id: int | None = None,
) -> list[dict[str, Any]]:
    columns = _table_columns(connection, "goal_evidence")
    if not columns:
        goal_columns = _table_columns(connection, "goals")
        if "evidence_json" not in goal_columns:
            return []
        resident_filter = "AND resident_id=?" if resident_id is not None else ""
        parameters: tuple[Any, ...] = (season_id, resident_id) if resident_id is not None else (season_id,)
        evidence_rows = []
        for goal in connection.execute(
            f"SELECT id,resident_id,progress,completed_tick,evidence_json FROM goals WHERE season_id=? {resident_filter} ORDER BY id",
            parameters,
        ):
            evidence = loads(goal["evidence_json"], {})
            if isinstance(evidence, dict):
                activity_count = len(evidence.get("activityIds", []))
                commitment_count = len(evidence.get("commitmentIds", []))
            elif isinstance(evidence, list):
                activity_count = sum(
                    1 for item in evidence
                    if isinstance(item, dict) and isinstance(item.get("activityId"), int)
                )
                commitment_count = sum(
                    1 for item in evidence
                    if isinstance(item, dict) and isinstance(item.get("commitmentId"), int)
                )
            else:
                activity_count = commitment_count = 0
            if not activity_count and not commitment_count:
                continue
            parts = []
            if activity_count:
                parts.append(f"{activity_count} recorded activit{'y' if activity_count == 1 else 'ies'}")
            if commitment_count:
                parts.append(f"{commitment_count} completed commitment{'s' if commitment_count != 1 else ''}")
            evidence_rows.append({
                "id": None,
                "goalId": int(goal["id"]),
                "tick": int(goal["completed_tick"] or 0),
                "kind": "goal_evidence",
                "summary": " and ".join(parts).capitalize(),
                "progressDelta": int(goal["progress"] or 0),
                "ledgerId": None,
                "verified": True,
            })
        return evidence_rows
    where = []
    parameters: list[Any] = []
    if "season_id" in columns:
        where.append("season_id=?")
        parameters.append(season_id)
    if resident_id is not None and "resident_id" in columns:
        where.append("resident_id=?")
        parameters.append(resident_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    order = " ORDER BY tick DESC,id DESC" if {"tick", "id"}.issubset(columns) else ""
    try:
        rows = list(connection.execute(f"SELECT * FROM goal_evidence {clause}{order} LIMIT 120", tuple(parameters)))
    except sqlite3.OperationalError:
        return []
    if resident_id is not None and "resident_id" not in columns and "goal_id" in columns:
        goal_ids = {
            int(row[0])
            for row in connection.execute(
                "SELECT id FROM goals WHERE season_id=? AND resident_id=?", (season_id, resident_id)
            )
        }
        rows = [row for row in rows if int(_row_value(row, "goal_id", default=-1)) in goal_ids]
    return [
        {
            "id": _row_value(row, "id"),
            "goalId": _row_value(row, "goal_id", "goalId"),
            "tick": int(_row_value(row, "tick", "created_tick", default=0) or 0),
            "kind": str(_row_value(row, "evidence_type", "kind", default="activity")),
            "summary": str(_row_value(row, "summary", "description", "evidence", default="Goal progress recorded")),
            "progressDelta": int(_row_value(row, "progress_delta", "delta", default=0) or 0),
            "ledgerId": _row_value(row, "ledger_id"),
            "verified": bool(_row_value(row, "verified", default=True)),
        }
        for row in rows
    ]


def _life_goals(connection: sqlite3.Connection, resident_id: int | None = None) -> list[dict[str, Any]]:
    columns = _table_columns(connection, "life_goals")
    if not columns or "resident_id" not in columns:
        return []
    resident_filter = "WHERE lg.resident_id=?" if resident_id is not None else ""
    ordering = "CASE lg.status WHEN 'active' THEN 0 ELSE 1 END,lg.id DESC" if "status" in columns else "lg.id DESC"
    parameters: tuple[Any, ...] = (resident_id,) if resident_id is not None else ()
    try:
        rows = list(connection.execute(
            f"""
            SELECT lg.*,r.slug resident_slug,r.name resident_name
            FROM life_goals lg JOIN residents r ON r.id=lg.resident_id
            {resident_filter}
            ORDER BY {ordering} LIMIT 72
            """,
            parameters,
        ))
    except sqlite3.OperationalError:
        return []

    evidence_by_goal: dict[int, list[dict[str, Any]]] = {}
    activity_ids: set[int] = set()
    raw_evidence: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        goal_id = int(row["id"])
        value = loads(_row_value(row, "evidence_json", default="[]"), [])
        if isinstance(value, dict):
            value = [
                {"activityId": activity_id}
                for activity_id in value.get("activityIds", [])
            ]
        entries = [item for item in value if isinstance(item, dict)][-16:] if isinstance(value, list) else []
        raw_evidence[goal_id] = entries
        for item in entries:
            try:
                activity_ids.add(int(item["activityId"]))
            except (KeyError, TypeError, ValueError):
                pass

    activities: dict[int, sqlite3.Row] = {}
    if activity_ids and _table_columns(connection, "activities"):
        ordered_ids = sorted(activity_ids)
        for start in range(0, len(ordered_ids), 500):
            batch = ordered_ids[start:start + 500]
            placeholders = ",".join("?" for _ in batch)
            try:
                activities.update({
                    int(item["id"]): item
                    for item in connection.execute(
                        f"SELECT id,resident_id,tick,kind,summary FROM activities WHERE id IN ({placeholders})",
                        tuple(batch),
                    )
                })
            except sqlite3.OperationalError:
                activities = {}
                break

    for row in rows:
        goal_id = int(row["id"])
        resident = int(row["resident_id"])
        evidence: list[dict[str, Any]] = []
        for index, item in enumerate(raw_evidence[goal_id]):
            try:
                activity_id = int(item.get("activityId"))
            except (TypeError, ValueError):
                activity_id = 0
            activity = activities.get(activity_id)
            verified = bool(activity and int(activity["resident_id"] or 0) == resident)
            action = str(item.get("action") or (activity["kind"] if activity else "life progress"))
            evidence.append({
                "id": f"life-{goal_id}-{index + 1}",
                "goalId": goal_id,
                "goalScope": "life",
                "tick": int(activity["tick"] if verified else item.get("tick") or 0),
                "kind": "life_goal_activity",
                "summary": str(activity["summary"]) if verified else f"{_public_label(action)} advanced this life goal",
                "progressDelta": int(item.get("progressDelta") or 2),
                "ledgerId": None,
                "verified": verified,
            })
        evidence_by_goal[goal_id] = evidence

    return [
        {
            "id": int(row["id"]),
            "resident": str(row["resident_slug"]),
            "residentName": str(row["resident_name"]),
            "scope": "life",
            "category": str(_row_value(row, "category", default="life")),
            "description": str(_row_value(row, "description", default="Build a meaningful life in Krabville.")),
            "status": str(_row_value(row, "status", default="active")),
            "progress": int(_row_value(row, "progress", default=0) or 0),
            "createdSeasonId": _row_value(row, "created_season_id"),
            "createdTick": int(_row_value(row, "created_tick", default=0) or 0),
            "completedSeasonId": _row_value(row, "completed_season_id"),
            "completedTick": _row_value(row, "completed_tick"),
            "evidence": evidence_by_goal[int(row["id"])],
            "evidenceCount": len(evidence_by_goal[int(row["id"])]),
        }
        for row in rows
    ]


def _care_schedules(connection: sqlite3.Connection, resident_id: int | None = None) -> list[dict[str, Any]]:
    if not _table_columns(connection, "childcare_arrangements"):
        return []
    schedule_exists = bool(_table_columns(connection, "childcare_schedule"))
    schedule_select = (
        "s.day_of_week,s.start_minute,s.end_minute" if schedule_exists
        else "NULL day_of_week,NULL start_minute,NULL end_minute"
    )
    schedule_join = "LEFT JOIN childcare_schedule s ON s.arrangement_id=c.id" if schedule_exists else ""
    resident_filter = "AND c.child_resident_id=?" if resident_id is not None else ""
    parameters: tuple[Any, ...] = (resident_id,) if resident_id is not None else ()
    try:
        rows = connection.execute(
            f"""
            SELECT c.id,c.child_resident_id,c.arrangement_type,c.status,c.cost_per_day_cents,
              child.slug child_slug,child.name child_name,carer.slug caregiver_slug,
              carer.name caregiver_name,provider.name provider_name,{schedule_select}
            FROM childcare_arrangements c
            JOIN residents child ON child.id=c.child_resident_id
            LEFT JOIN residents carer ON carer.id=c.caregiver_resident_id
            LEFT JOIN businesses provider ON provider.id=c.provider_business_id
            {schedule_join}
            WHERE c.status IN ('planned','active') {resident_filter}
            ORDER BY c.child_resident_id,c.id,day_of_week,start_minute
            """,
            parameters,
        )
    except sqlite3.OperationalError:
        return []
    return [
        {
            "arrangementId": int(row["id"]),
            "resident": str(row["child_slug"]),
            "residentName": str(row["child_name"]),
            "type": str(row["arrangement_type"]),
            "typeLabel": _public_label(row["arrangement_type"]),
            "status": str(row["status"]),
            "statusLabel": _public_label(row["status"]),
            "caregiver": row["caregiver_name"] or row["provider_name"],
            "caregiverSlug": row["caregiver_slug"],
            "day": int(row["day_of_week"]) if row["day_of_week"] is not None else None,
            "startMinute": int(row["start_minute"]) if row["start_minute"] is not None else None,
            "endMinute": int(row["end_minute"]) if row["end_minute"] is not None else None,
            "costPerDay": int(row["cost_per_day_cents"] or 0) / 100,
            "scheduleLabel": (
                f"Day {int(row['day_of_week']) + 1}, {int(row['start_minute'] or 0) // 60:02d}:"
                f"{int(row['start_minute'] or 0) % 60:02d}-{int(row['end_minute'] or 0) // 60:02d}:"
                f"{int(row['end_minute'] or 0) % 60:02d}"
                if row["day_of_week"] is not None else "Schedule pending"
            ),
        }
        for row in rows
    ]


def _health_details(connection: sqlite3.Connection, resident_id: int | None = None) -> list[dict[str, Any]]:
    if not _table_columns(connection, "health_conditions"):
        return []
    resident_filter = "AND h.resident_id=?" if resident_id is not None else ""
    parameters: tuple[Any, ...] = (resident_id,) if resident_id is not None else ()
    try:
        rows = connection.execute(
            f"""
            SELECT h.*,r.slug resident_slug,r.name resident_name,b.name provider_name
            FROM health_conditions h JOIN residents r ON r.id=h.resident_id
            LEFT JOIN businesses b ON b.id=h.provider_business_id
            WHERE h.status IN ('latent','active','recovering','terminal') {resident_filter}
            ORDER BY h.severity DESC,h.id
            """,
            parameters,
        )
    except sqlite3.OperationalError:
        return []
    conditions = []
    for row in rows:
        severity = int(row["severity"])
        severity_label = "Mild" if severity < 25 else "Moderate" if severity < 60 else "Serious" if severity < 85 else "Critical"
        conditions.append({
            "id": int(row["id"]),
            "resident": str(row["resident_slug"]),
            "residentName": str(row["resident_name"]),
            "key": str(row["condition_key"]),
            "name": str(row["name"]),
            "type": str(row["condition_type"]),
            "typeLabel": _public_label(row["condition_type"]),
            "severity": severity,
            "severityLabel": severity_label,
            "status": str(row["status"]),
            "statusLabel": _public_label(row["status"]),
            "contagious": bool(row["contagious"]),
            "contagionLabel": "Contagious" if row["contagious"] else "Not contagious",
            "provider": row["provider_name"],
            "treatmentCost": int(row["treatment_cost_cents"] or 0) / 100,
        })
    return conditions


def _housing_recovery(connection: sqlite3.Connection, season_id: int) -> dict[str, Any]:
    shelter_rows: list[sqlite3.Row] = []
    if _table_columns(connection, "property_occupancy"):
        try:
            shelter_rows = list(connection.execute(
                """
                SELECT DISTINCT h.id household_id,h.name household_name,p.name property_name,
                  r.slug resident_slug,r.name resident_name
                FROM property_occupancy o JOIN properties p ON p.id=o.property_id
                JOIN households h ON h.id=o.household_id
                JOIN household_members hm ON hm.household_id=h.id AND hm.ended_season_id IS NULL
                JOIN residents r ON r.id=hm.resident_id
                JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
                WHERE o.ended_season_id IS NULL AND p.property_type='shelter'
                ORDER BY h.id,r.id
                """
            ))
        except sqlite3.OperationalError:
            shelter_rows = []
    recovery_table = next(
        (name for name in ("housing_recovery", "housing_recovery_plans") if _table_columns(connection, name)),
        None,
    )
    plans: list[dict[str, Any]] = []
    if recovery_table:
        columns = _table_columns(connection, recovery_table)
        where = "WHERE season_id=?" if "season_id" in columns else ""
        parameters: tuple[Any, ...] = (season_id,) if where else ()
        for row in _optional_rows(connection, recovery_table, where, parameters):
            status = str(_row_value(row, "status", default="planned"))
            stage = str(_row_value(row, "stage", "recovery_stage", default="assessment"))
            stable_days = int(_row_value(row, "stable_days", default=0) or 0)
            plans.append({
                "id": _row_value(row, "id"),
                "householdId": _row_value(row, "household_id"),
                "residentId": _row_value(row, "resident_id"),
                "status": status,
                "statusLabel": _public_label(status),
                "stage": stage,
                "stageLabel": _public_label(stage),
                "arrearsDays": int(_row_value(row, "arrears_days", default=0) or 0),
                "failedAttempts": int(_row_value(row, "failed_attempts", default=0) or 0),
                "stableDays": stable_days,
                "stabilityLabel": f"{stable_days} stable day{'s' if stable_days != 1 else ''}",
                "nextStep": str(_row_value(row, "next_step", "summary", default="Housing review pending")),
            })
    return {
        "available": recovery_table is not None,
        "trackingLabel": "Recovery tracking active" if recovery_table else "Recovery tracking unavailable",
        "shelterResidents": len(shelter_rows),
        "shelterHouseholds": len({int(row["household_id"]) for row in shelter_rows}),
        "residents": [
            {"slug": row["resident_slug"], "name": row["resident_name"], "household": row["household_name"], "shelter": row["property_name"]}
            for row in shelter_rows
        ],
        "plans": plans,
    }


def _model_circuits(connection: sqlite3.Connection, season_id: int) -> dict[str, Any]:
    table = next(
        (name for name in ("model_circuits", "model_circuit_state") if _table_columns(connection, name)),
        None,
    )
    if not table:
        return {"available": False, "summaryLabel": "Circuit telemetry unavailable", "circuits": []}
    columns = _table_columns(connection, table)
    where = "WHERE season_id=?" if "season_id" in columns else ""
    parameters: tuple[Any, ...] = (season_id,) if where else ()
    circuits = []
    for row in _optional_rows(connection, table, where, parameters):
        status = str(_row_value(row, "status", "state", default="closed"))
        circuits.append({
            "jobKind": str(_row_value(row, "job_kind", "kind", default="unknown")),
            "jobLabel": _public_label(_row_value(row, "job_kind", "kind", default="model job")),
            "model": _row_value(row, "model"),
            "status": status,
            "statusLabel": {
                "closed": "Primary route healthy",
                "open": "Fallback route active",
                "half_open": "Primary route probe due",
                "probing": "Testing primary route",
            }.get(status, _public_label(status)),
            "consecutiveFailures": int(_row_value(row, "consecutive_failures", "failures", default=0) or 0),
            "day": _row_value(row, "day"),
            "openedDay": _row_value(row, "opened_day", "day"),
            "openedAt": _row_value(row, "opened_at"),
            "probeDay": _row_value(row, "probe_day", "next_probe_day"),
            "fallbackModel": _row_value(row, "fallback_model"),
            "updatedAt": _row_value(row, "updated_at"),
        })
    active = sum(item["status"] != "closed" for item in circuits)
    return {
        "available": True,
        "summaryLabel": f"Fallback active for {active} job type{'s' if active != 1 else ''}" if active else "Primary routes healthy",
        "circuits": circuits,
    }


def _story_ledger(connection: sqlite3.Connection, season_id: int, limit: int = 120) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    columns = _table_columns(connection, "story_ledger")
    if not columns:
        empty = {"available": False, "verified": 0, "unverified": 0, "legacy": 0, "participantLinks": 0}
        return [], empty
    participant_map: dict[int, list[dict[str, str]]] = {}
    if _table_columns(connection, "story_ledger_participants"):
        try:
            for row in connection.execute(
                """
                SELECT p.ledger_id,r.slug,r.name,p.role FROM story_ledger_participants p
                JOIN residents r ON r.id=p.resident_id JOIN story_ledger l ON l.id=p.ledger_id
                WHERE l.season_id=? ORDER BY p.ledger_id,r.id
                """,
                (season_id,),
            ):
                participant_map.setdefault(int(row["ledger_id"]), []).append({
                    "slug": str(row["slug"]), "name": str(row["name"]), "role": str(row["role"])
                })
        except sqlite3.OperationalError:
            participant_map = {}
    verified_ledger_ids: set[int] = set()
    chronicle_columns = _table_columns(connection, "daily_chronicles")
    if {"verified", "ledger_ids_json"}.issubset(chronicle_columns):
        for chronicle in connection.execute(
            "SELECT verified,ledger_ids_json FROM daily_chronicles WHERE season_id=?", (season_id,)
        ):
            if chronicle["verified"]:
                verified_ledger_ids.update(int(value) for value in loads(chronicle["ledger_ids_json"], []) if str(value).isdigit())
    rows = connection.execute(
        "SELECT * FROM story_ledger WHERE season_id=? ORDER BY tick DESC,id DESC LIMIT ?",
        (season_id, limit),
    )
    verification_available = (
        "verification_status" in columns
        or "verified" in columns
        or {"verified", "ledger_ids_json"}.issubset(chronicle_columns)
    )
    ledger: list[dict[str, Any]] = []
    for row in rows:
        raw_status = _row_value(row, "verification_status")
        raw_verified = _row_value(row, "verified")
        status = str(raw_status) if raw_status is not None else (
            "verified" if raw_verified or int(row["id"]) in verified_ledger_ids
            else "unverified" if raw_verified is not None or verification_available
            else "legacy"
        )
        day = int(row["day"])
        phase = str(_row_value(row, "phase", default="epilogue" if day >= 7 else "day"))
        participants = participant_map.get(int(row["id"]), [])
        ledger.append({
            "id": row["id"], "tick": int(row["tick"]), "day": day,
            "category": row["entry_type"], "title": row["headline"], "summary": row["summary"],
            "participants": [item["slug"] for item in participants],
            "participantDetails": participants,
            "phase": phase,
            "epilogue": phase == "epilogue" or day >= 7,
            "verificationStatus": status,
            "verified": status == "verified" if verification_available else None,
        })
    summary = {
        "available": verification_available,
        "verified": sum(item["verificationStatus"] == "verified" for item in ledger),
        "unverified": sum(item["verificationStatus"] == "unverified" for item in ledger),
        "legacy": sum(item["verificationStatus"] == "legacy" for item in ledger),
        "participantLinks": sum(len(item["participants"]) for item in ledger),
    }
    return ledger, summary


def _economy_v22(
    connection: sqlite3.Connection,
    season_id: int,
    resident_net_worth: list[int],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    daily: dict[int, dict[str, float | list[int]]] = {}

    def bucket(day: int) -> dict[str, float | list[int]]:
        return daily.setdefault(day, {
            "residentIncome": 0.0, "residentSpending": 0.0,
            "retailVolume": 0.0, "businessRevenue": 0.0,
            "businessExpenses": 0.0, "residentWealth": [],
        })

    try:
        for row in connection.execute(
            """
            SELECT t.tick,t.category,a.resident_id,a.business_id,e.amount_cents
            FROM financial_transactions t JOIN transaction_entries e ON e.transaction_id=t.id
            JOIN financial_accounts a ON a.id=e.account_id
            WHERE t.season_id=? AND t.status='posted'
            """,
            (season_id,),
        ):
            values = bucket(int(row["tick"]) // 288)
            amount = int(row["amount_cents"])
            if row["resident_id"] is not None:
                key = "residentIncome" if amount > 0 else "residentSpending"
                values[key] = float(values[key]) + abs(amount) / 100
            if row["business_id"] is not None:
                key = "businessRevenue" if amount > 0 else "businessExpenses"
                values[key] = float(values[key]) + abs(amount) / 100
            if row["category"] == "retail_purchase":
                values["retailVolume"] = float(values["retailVolume"]) + abs(amount) / 200
    except sqlite3.OperationalError:
        pass
    try:
        for row in connection.execute(
            """
            SELECT day,net_worth_cents FROM financial_snapshots
            WHERE season_id=? AND owner_kind='resident' ORDER BY day,owner_id
            """,
            (season_id,),
        ):
            wealth = bucket(int(row["day"]))["residentWealth"]
            if isinstance(wealth, list):
                wealth.append(int(row["net_worth_cents"]))
    except sqlite3.OperationalError:
        pass
    prices: dict[int, float] = {}
    try:
        prices = {
            int(row["day"]): float(row["average_price"] or 0) / 100
            for row in connection.execute(
                """
                SELECT day,AVG(average_price_cents) average_price FROM price_history
                WHERE season_id=? AND units_sold>0 GROUP BY day ORDER BY day
                """,
                (season_id,),
            )
        }
    except sqlite3.OperationalError:
        pass
    baseline_price = next((value for _, value in sorted(prices.items()) if value > 0), 0.0)
    history = []
    for day in sorted(set(daily) | set(prices)):
        values = bucket(day)
        wealth = sorted(values["residentWealth"]) if isinstance(values["residentWealth"], list) else []
        median = wealth[len(wealth) // 2] / 100 if wealth else None
        price = prices.get(day)
        history.append({
            "day": day,
            "residentMedianWealth": median,
            "disposableIncome": float(values["residentIncome"]) - float(values["residentSpending"]),
            "cpi": round(100 * price / baseline_price, 2) if price and baseline_price else None,
            "retailVolume": round(float(values["retailVolume"]), 2),
            "businessRevenue": round(float(values["businessRevenue"]), 2),
            "businessProfit": round(float(values["businessRevenue"]) - float(values["businessExpenses"]), 2),
        })
    total_income = sum(float(values["residentIncome"]) for values in daily.values())
    total_spending = sum(float(values["residentSpending"]) for values in daily.values())
    business_revenue = sum(float(values["businessRevenue"]) for values in daily.values())
    business_expenses = sum(float(values["businessExpenses"]) for values in daily.values())
    retail_volume = sum(float(values["retailVolume"]) for values in daily.values())
    eligible = int(connection.execute(
        "SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1 AND current_stage IN ('teen','adult','senior')"
    ).fetchone()[0])
    employed = int(connection.execute("SELECT COUNT(DISTINCT resident_id) FROM employment WHERE status='active'").fetchone()[0])
    debt = connection.execute(
        """
        SELECT COUNT(*) total,SUM(CASE WHEN status IN ('late','defaulted') THEN 1 ELSE 0 END) delinquent
        FROM debts WHERE status IN ('current','late','defaulted')
        """
    ).fetchone()
    current_cpi = next((item["cpi"] for item in reversed(history) if item["cpi"] is not None), None)
    return {
        "residentMedianWealth": (sorted(resident_net_worth)[len(resident_net_worth) // 2] / 100 if resident_net_worth else 0),
        "disposableIncome": round((total_income - total_spending) / max(1, eligible), 2),
        "cpi": current_cpi,
        "retailVolume": round(retail_volume, 2),
        "businessRevenue": round(business_revenue, 2),
        "businessProfit": round(business_revenue - business_expenses, 2),
        "employmentRate": round(100 * employed / max(1, eligible), 1),
        "debtDelinquencyRate": round(100 * int(debt["delinquent"] or 0) / max(1, int(debt["total"] or 0)), 1),
        "delinquentDebts": int(debt["delinquent"] or 0),
        "wealthGini": _gini(resident_net_worth),
    }, history


def _resident_live_v2(
    connection: sqlite3.Connection,
    season_id: int,
    resident_id: int,
    row: sqlite3.Row,
) -> dict[str, Any]:
    wants = [
        {
            "title": item["kind"].replace("_", " ").title(),
            "text": item["description"],
            "status": item["status"],
            "confidence": int(item["priority"]),
        }
        for item in connection.execute(
            """
            SELECT kind,description,status,priority FROM resident_wants
            WHERE season_id=? AND resident_id=? AND status IN ('active','pursuing')
            ORDER BY priority DESC,id LIMIT 8
            """,
            (season_id, resident_id),
        )
    ]
    decision_id = int(row["current_decision_id"] or 0)
    factors = _decision_factors(connection, decision_id)
    candidates = [
        {
            "activity": item["action"],
            "destination": item["destination"],
            "score": round(float(item["utility_score"]), 1),
            "confidence": "chosen" if item["selected"] else f"option {item['option_rank']}",
            "reason": next(
                (factor["explanation"] for factor in factors.get(int(item["option_rank"]), []) if factor["explanation"]),
                "Need, schedule, weather, relationships, and current goals",
            ),
            "drivers": [
                factor["key"].replace("_", " ").title()
                for factor in factors.get(int(item["option_rank"]), [])[:4]
            ],
            "factors": factors.get(int(item["option_rank"]), []),
        }
        for item in connection.execute(
            """
            SELECT option_rank,action,destination,utility_score,selected
            FROM decision_options WHERE decision_id=? ORDER BY option_rank
            """,
            (decision_id,),
        )
    ] if decision_id else []
    urgent = [
        str(item["need_key"])
        for item in connection.execute(
            """
            SELECT need_key FROM resident_needs
            WHERE season_id=? AND resident_id=? AND satisfaction<35
            ORDER BY satisfaction,need_key LIMIT 3
            """,
            (season_id, resident_id),
        )
    ]
    stage = str(row["life_stage"] or "adult")
    stage_index = int(row["stage_season_index"] or 0)
    stage_span = {"baby": 1, "child": 1, "teen": 1, "adult": 4, "senior": 2}.get(stage)
    age_label = f"{stage.title()}, season {stage_index + 1} of {stage_span}" if stage_span else stage.title()
    return {
        "needsHighIsGood": True,
        "lifeStage": stage,
        "ageLabel": age_label,
        "household": row["household_name"],
        "householdId": row["household_id"],
        "wants": [item for item in wants if item["title"] != "Aspiration"],
        "aspirations": [item for item in wants if item["title"] == "Aspiration"],
        "decisionCandidates": candidates,
        "decisionFactors": factors.get(
            next((int(item["option_rank"]) for item in connection.execute(
                "SELECT option_rank FROM decision_options WHERE decision_id=? AND selected=1 LIMIT 1",
                (decision_id,),
            )), 0),
            [],
        ) if decision_id else [],
        "pondering": {
            "active": row["decision_state"] == "pondering",
            "thought": row["public_thought"],
            "urgentNeeds": urgent,
            "untilTick": int(row["action_until_tick"]),
        },
        "urgentNeeds": urgent,
        "spriteVariant": resident_id % 12,
    }


def _resident_base_v2(
    connection: sqlite3.Connection,
    season_id: int,
    row: sqlite3.Row,
    indoor_locations: set[str],
) -> dict[str, Any]:
    path = loads(row["path_json"], [])
    activity = str(row["activity"])
    location = str(row["location"])
    outdoors = any(word in activity.casefold() for word in ("walk", "explor", "outside", "garden"))
    indoors = not path and location in indoor_locations and not outdoors
    return {
        "slug": row["slug"],
        "name": row["name"],
        "role": row["role"],
        "routine": row["routine"],
        "about": row["about"],
        "home": row["home"],
        "workplace": row["workplace"],
        "color": row["color"],
        "traits": loads(row["traits_json"], {}),
        "possessions": loads(row["possessions_json"], []),
        "x": float(row["x"]),
        "y": float(row["y"]),
        "destinationX": float(row["destination_x"]),
        "destinationY": float(row["destination_y"]),
        "location": location,
        "activity": activity,
        "publicThought": row["public_thought"],
        "intention": row["intention"],
        "reflection": row["reflection"],
        "mood": row["mood"],
        "needs": loads(row["needs_json"], {}),
        "path": path,
        "indoors": indoors,
        "building": location if indoors else None,
        "updatedTick": int(row["updated_tick"]),
        "care": {
            "state": str(row["care_state"] or "independent"),
            "caregiver": row["caregiver_name"] or row["care_provider_name"],
        },
        **_resident_live_v2(connection, season_id, int(row["id"]), row),
    }


def _resident_detail_v2(
    connection: sqlite3.Connection,
    season_id: int,
    resident_id: int,
) -> dict[str, Any]:
    family = [
        {
            "slug": item["slug"],
            "name": item["name"],
            "relation": item["relation_type"].replace("_", " "),
            "lifeStage": item["current_stage"],
            "household": item["household_name"],
        }
        for item in connection.execute(
            """
            SELECT other.slug,other.name,f.relation_type,l.current_stage,h.name household_name
            FROM family_links f JOIN residents other ON other.id=f.relative_resident_id
            JOIN resident_lifecycle l ON l.resident_id=other.id
            LEFT JOIN household_members hm ON hm.resident_id=other.id AND hm.ended_season_id IS NULL
            LEFT JOIN households h ON h.id=hm.household_id
            WHERE f.resident_id=? AND f.ended_season_id IS NULL ORDER BY f.relation_type,other.name
            """,
            (resident_id,),
        )
    ]
    beliefs = [
        {
            "title": item["stance"].title(),
            "text": item["statement"],
            "status": f"{item['confidence']}% confidence",
            "confidence": int(item["confidence"]),
        }
        for item in connection.execute(
            """
            SELECT b.stance,b.confidence,f.statement FROM resident_beliefs b
            JOIN facts f ON f.id=b.fact_id WHERE b.resident_id=?
            ORDER BY b.updated_tick DESC LIMIT 16
            """,
            (resident_id,),
        )
    ]
    secrets = [
        {
            "title": item["status"].replace("_", " ").title(),
            "text": item["statement"],
            "status": f"Sensitivity {item['sensitivity']}",
            "revealed": item["status"] == "public",
        }
        for item in connection.execute(
            """
            SELECT s.status,s.sensitivity,f.statement FROM secrets s JOIN facts f ON f.id=s.fact_id
            WHERE s.owner_resident_id=? ORDER BY s.created_tick DESC LIMIT 12
            """,
            (resident_id,),
        )
    ]
    condition_details = _health_details(connection, resident_id)
    conditions = [str(item["name"]) for item in condition_details]
    care = list(connection.execute(
        """
        SELECT c.arrangement_type,c.cost_per_day_cents,r.name caregiver_name,b.name provider_name
        FROM childcare_arrangements c LEFT JOIN residents r ON r.id=c.caregiver_resident_id
        LEFT JOIN businesses b ON b.id=c.provider_business_id
        WHERE c.child_resident_id=? AND c.status='active'
        """,
        (resident_id,),
    ))
    current_care = connection.execute(
        """
        SELECT v.care_state,r.name caregiver_name,b.name provider_name
        FROM resident_season_state v
        LEFT JOIN residents r ON r.id=v.current_caregiver_id
        LEFT JOIN businesses b ON b.id=v.current_care_provider_id
        WHERE v.season_id=? AND v.resident_id=?
        """,
        (season_id, resident_id),
    ).fetchone()
    job = connection.execute(
        """
        SELECT j.title,b.name employer,e.status,e.performance,e.scheduled_minutes_per_day,e.wage_cents
        FROM employment e JOIN jobs j ON j.id=e.job_id LEFT JOIN businesses b ON b.id=j.business_id
        WHERE e.resident_id=? AND e.status IN ('active','leave','suspended') ORDER BY e.id DESC LIMIT 1
        """,
        (resident_id,),
    ).fetchone()
    balances: dict[str, int] = {}
    for account in connection.execute(
        "SELECT id,account_type FROM financial_accounts WHERE resident_id=? AND status='open'",
        (resident_id,),
    ):
        balances[str(account["account_type"])] = balances.get(str(account["account_type"]), 0) + account_balance(connection, int(account["id"]))
    investments = int(connection.execute(
        """
        SELECT COALESCE(SUM(i.market_value_cents),0) FROM investments i
        JOIN financial_accounts a ON a.id=i.account_id WHERE a.resident_id=?
        """,
        (resident_id,),
    ).fetchone()[0])
    debt = int(connection.execute(
        """
        SELECT COALESCE(SUM(d.outstanding_cents),0) FROM debts d
        JOIN financial_accounts a ON a.id=d.borrower_account_id
        WHERE a.resident_id=? AND d.status IN ('current','late','defaulted')
        """,
        (resident_id,),
    ).fetchone()[0])
    properties = [
        {
            "id": int(item["id"]), "slug": item["slug"],
            "name": item["name"], "type": item["property_type"],
            "address": item["address"], "mapLocation": item["map_location"],
            "interiorVariant": int(item["interior_variant"]),
            "value": int(item["market_value_cents"]) / 100,
            "status": item["status"], "interiorAvailable": bool(item["interior_key"]),
        }
        for item in connection.execute(
            """
            SELECT DISTINCT p.* FROM properties p
            LEFT JOIN property_ownership own ON own.property_id=p.id
            LEFT JOIN household_members hm ON hm.household_id=own.household_id
            WHERE own.resident_id=? OR hm.resident_id=?
            """,
            (resident_id, resident_id),
        )
    ]
    life_ledger = [
        {
            "id": item["id"], "tick": int(item["tick"]),
            "category": item["event_type"], "title": item["title"], "summary": item["summary"],
        }
        for item in connection.execute(
            """
            SELECT id,tick,event_type,title,summary FROM life_events
            WHERE subject_resident_id=? OR related_resident_id=? ORDER BY season_id DESC,tick DESC LIMIT 30
            """,
            (resident_id, resident_id),
        )
    ]
    phone = connection.execute(
        "SELECT phone_number,device_name,active FROM resident_phones WHERE resident_id=?",
        (resident_id,),
    ).fetchone()
    calls = [
        {
            "tick": int(item["tick"]),
            "direction": "outgoing" if int(item["caller_resident_id"]) == resident_id else "incoming",
            "otherSlug": item["other_slug"],
            "otherName": item["other_name"],
            "purpose": item["purpose"],
            "summary": item["summary"],
            "visibility": item["visibility"],
            "durationMinutes": int(item["duration_minutes"]),
        }
        for item in connection.execute(
            """
            SELECT c.*,
              CASE WHEN c.caller_resident_id=? THEN recipient.slug ELSE caller.slug END other_slug,
              CASE WHEN c.caller_resident_id=? THEN recipient.name ELSE caller.name END other_name
            FROM communications c JOIN residents caller ON caller.id=c.caller_resident_id
            JOIN residents recipient ON recipient.id=c.recipient_resident_id
            WHERE c.season_id=? AND (c.caller_resident_id=? OR c.recipient_resident_id=?)
            ORDER BY c.tick DESC,c.id DESC LIMIT 30
            """,
            (resident_id, resident_id, season_id, resident_id, resident_id),
        )
    ]
    on_person = [
        {
            "name": item["name"], "category": item["category"],
            "quantity": float(item["quantity"]), "condition": int(item["condition_score"]),
            "assetKey": item["asset_key"], "assetIndex": item_asset_index(str(item["asset_key"])),
        }
        for item in connection.execute(
            """
            SELECT i.id item_id,i.name,i.category,i.asset_key,ri.quantity,ri.condition_score
            FROM resident_inventory ri JOIN item_catalog i ON i.id=ri.item_id
            WHERE ri.resident_id=? AND ri.quantity>0 ORDER BY i.category,i.name
            """,
            (resident_id,),
        )
    ]
    clothing = [item for item in on_person if item["category"] in {"clothing", "accessories"}]
    household = connection.execute(
        "SELECT household_id FROM household_members WHERE resident_id=? AND ended_season_id IS NULL",
        (resident_id,),
    ).fetchone()
    care_schedules = _care_schedules(connection, resident_id)
    goal_evidence = _goal_evidence(connection, season_id, resident_id)
    town_housing = _housing_recovery(connection, season_id)
    household_id = int(household[0]) if household else None
    housing_plans = [
        plan for plan in town_housing["plans"]
        if plan["residentId"] == resident_id or (household_id is not None and plan["householdId"] == household_id)
    ]
    shelter_record = next(
        (item for item in town_housing["residents"] if item["slug"] == connection.execute(
            "SELECT slug FROM residents WHERE id=?", (resident_id,)
        ).fetchone()[0]),
        None,
    )
    home_inventory = [
        {
            "name": item["name"], "category": item["category"],
            "quantity": float(item["quantity"]), "condition": int(item["condition_score"]),
            "assetKey": item["asset_key"], "assetIndex": item_asset_index(str(item["asset_key"])),
        }
        for item in connection.execute(
            """
            SELECT i.id item_id,i.name,i.category,i.asset_key,hi.quantity,hi.condition_score
            FROM household_inventory hi JOIN item_catalog i ON i.id=hi.item_id
            WHERE hi.household_id=? AND hi.quantity>0 ORDER BY i.category,i.name
            """,
            (household[0] if household else -1,),
        )
    ]
    account_rows = []
    for account in connection.execute(
        "SELECT id,name,account_type,status FROM financial_accounts WHERE resident_id=? ORDER BY id",
        (resident_id,),
    ):
        account_rows.append({
            "name": account["name"], "type": account["account_type"],
            "status": account["status"], "balance": account_balance(connection, int(account["id"])) / 100,
        })
    finance_history = [
        {
            "season": int(item["season_number"]), "day": int(item["day"]),
            "cash": int(item["cash_cents"]) / 100, "debt": int(item["debt_cents"]) / 100,
            "investments": int(item["investments_cents"]) / 100,
            "netWorth": int(item["net_worth_cents"]) / 100,
        }
        for item in connection.execute(
            """
            SELECT fs.*,s.number season_number FROM financial_snapshots fs
            JOIN seasons s ON s.id=fs.season_id
            WHERE fs.owner_kind='resident' AND fs.owner_id=? ORDER BY s.number,fs.day LIMIT 140
            """,
            (resident_id,),
        )
    ]
    transactions = [
        {
            "id": int(item["id"]), "tick": int(item["tick"]),
            "category": item["category"], "description": item["description"],
            "amount": int(item["resident_amount"]) / 100,
        }
        for item in connection.execute(
            """
            SELECT t.id,t.tick,t.category,t.description,SUM(e.amount_cents) resident_amount
            FROM financial_transactions t JOIN transaction_entries e ON e.transaction_id=t.id
            JOIN financial_accounts a ON a.id=e.account_id
            WHERE t.season_id=? AND a.resident_id=? AND t.status='posted'
            GROUP BY t.id ORDER BY t.tick DESC,t.id DESC LIMIT 40
            """,
            (season_id, resident_id),
        )
    ]
    liquid = sum(balances.get(name, 0) for name in ("cash", "chequing", "savings"))
    care_status = (
        "Care covered" if current_care and current_care["care_state"] in {"covered", "institutional"}
        else "Care gap" if current_care and current_care["care_state"] == "uncovered"
        else "Care plan active" if care else "Independent"
    )
    health_status = (
        "Treatment needed" if any(item["status"] in {"active", "terminal"} for item in condition_details)
        else "Recovering" if any(item["status"] == "recovering" for item in condition_details)
        else "Monitoring" if condition_details
        else "No active condition"
    )
    return {
        "family": family,
        "secrets": secrets,
        "beliefs": beliefs,
        "health": {
            "status": health_status,
            "careStatus": care_status,
            "conditions": conditions,
            "conditionDetails": condition_details,
            "care": [str(item["arrangement_type"]) for item in care],
            "careSchedules": care_schedules,
            "caregiver": (
                str(current_care["caregiver_name"] or current_care["provider_name"])
                if current_care and (current_care["caregiver_name"] or current_care["provider_name"])
                else str(care[0]["caregiver_name"] or care[0]["provider_name"]) if care else None
            ),
        },
        "career": ({
            "title": job["title"], "employer": job["employer"], "status": job["status"],
            "performance": int(job["performance"]),
            "schedule": f"{int(job['scheduled_minutes_per_day']) // 60}h {int(job['scheduled_minutes_per_day']) % 60:02d}m per workday",
            "income": int(job["wage_cents"]) * int(job["scheduled_minutes_per_day"]) / 6000,
        } if job else {"status": "dependent or between jobs"}),
        "finances": {
            "cash": balances.get("cash", 0) / 100,
            "chequing": balances.get("chequing", 0) / 100,
            "savings": balances.get("savings", 0) / 100,
            "investments": investments / 100,
            "debt": debt / 100,
            "netWorth": (liquid + investments - debt) / 100,
            "accounts": account_rows,
            "history": finance_history,
        },
        "phone": ({
            "number": phone["phone_number"], "device": phone["device_name"],
            "active": bool(phone["active"]),
        } if phone else None),
        "communications": calls,
        "clothing": clothing,
        "onPersonInventory": on_person,
        "homeInventory": home_inventory,
        "transactions": transactions,
        "properties": properties,
        "lifeLedger": life_ledger,
        "goalEvidence": goal_evidence,
        "lifeGoals": _life_goals(connection, resident_id),
        "housingRecovery": {
            "available": town_housing["available"],
            "trackingLabel": town_housing["trackingLabel"],
            "inShelter": shelter_record is not None,
            "shelter": shelter_record["shelter"] if shelter_record else None,
            "stateLabel": "Temporary shelter" if shelter_record else "Housed",
            "recoveryLabel": (
                housing_plans[0]["stageLabel"] if housing_plans
                else "No active recovery plan" if town_housing["available"]
                else "Recovery data unavailable"
            ),
            "plans": housing_plans,
        },
    }


def _town_v2(connection: sqlite3.Connection, season_id: int) -> dict[str, Any]:
    ledger, ledger_verification = _story_ledger(connection, season_id)
    households = []
    families = []
    for household in connection.execute("SELECT * FROM households WHERE status='active' ORDER BY id"):
        members = list(connection.execute(
            """
            SELECT r.slug,r.name,r.home,l.current_stage,hm.role FROM household_members hm
            JOIN residents r ON r.id=hm.resident_id JOIN resident_lifecycle l ON l.resident_id=r.id
            WHERE hm.household_id=? AND hm.ended_season_id IS NULL AND l.alive=1 ORDER BY r.id
            """,
            (household["id"],),
        ))
        account = connection.execute(
            "SELECT id FROM financial_accounts WHERE household_id=? AND name='Household chequing'",
            (household["id"],),
        ).fetchone()
        cash = account_balance(connection, int(account[0])) / 100 if account else 0
        home = str(members[0]["home"]) if members else "No current home"
        inventory = connection.execute(
            """
            SELECT COUNT(*),COALESCE(SUM(hi.quantity*i.base_price_cents),0)
            FROM household_inventory hi JOIN item_catalog i ON i.id=hi.item_id
            WHERE hi.household_id=? AND hi.quantity>0
            """,
            (household["id"],),
        ).fetchone()
        households.append({
            "id": household["id"], "name": household["name"], "home": home,
            "memberSlugs": [row["slug"] for row in members],
            "memberNames": [row["name"] for row in members], "cash": cash,
            "inventoryItems": int(inventory[0]), "inventoryValue": int(inventory[1]) / 100,
            "status": household["status"],
        })
        families.append({
            "id": household["id"], "name": household["name"],
            "members": [
                {"slug": row["slug"], "name": row["name"], "relation": row["role"], "lifeStage": row["current_stage"], "household": household["name"]}
                for row in members
            ],
            "summary": f"{len(members)} living residents share {home}.",
        })
    property_rows = []
    for prop in connection.execute("SELECT * FROM properties WHERE status<>'demolished' ORDER BY id"):
        map_location = str(prop["map_location"] or prop["address"])
        point = LOCATION_POINTS.get(map_location)
        household_occupants = [
            {"slug": item["slug"], "name": item["name"], "lifeStage": item["current_stage"]}
            for item in connection.execute(
                """
                SELECT DISTINCT r.slug,r.name,l.current_stage FROM property_occupancy po
                JOIN household_members hm ON hm.household_id=po.household_id AND hm.ended_season_id IS NULL
                JOIN residents r ON r.id=hm.resident_id JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
                WHERE po.property_id=? AND po.ended_season_id IS NULL ORDER BY r.id
                """,
                (prop["id"],),
            )
        ]
        inside = [
            {"slug": item["slug"], "name": item["name"], "activity": item["activity"]}
            for item in connection.execute(
                """
                SELECT r.slug,r.name,s.activity FROM resident_state s JOIN residents r ON r.id=s.resident_id
                WHERE s.season_id=? AND s.location=? AND s.path_json='[]' ORDER BY r.id
                """,
                (season_id, map_location),
            )
        ]
        owners = [
            str(item[0])
            for item in connection.execute(
                """
                SELECT COALESCE(r.name,h.name,b.name) FROM property_ownership own
                LEFT JOIN residents r ON r.id=own.resident_id LEFT JOIN households h ON h.id=own.household_id
                LEFT JOIN businesses b ON b.id=own.business_id
                WHERE own.property_id=? AND own.disposed_season_id IS NULL
                """,
                (prop["id"],),
            )
        ]
        business = connection.execute("SELECT id,slug,name,status FROM businesses WHERE property_id=? ORDER BY id DESC LIMIT 1", (prop["id"],)).fetchone()
        household_count = int(connection.execute(
            "SELECT COUNT(*) FROM property_occupancy WHERE property_id=? AND ended_season_id IS NULL",
            (prop["id"],),
        ).fetchone()[0])
        if business:
            inventory_summary = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(quantity),0) FROM business_inventory WHERE business_id=? AND quantity>0",
                (business["id"],),
            ).fetchone()
        else:
            inventory_summary = connection.execute(
                """
                SELECT COUNT(DISTINCT hi.item_id),COALESCE(SUM(hi.quantity),0)
                FROM property_occupancy po JOIN household_inventory hi ON hi.household_id=po.household_id
                WHERE po.property_id=? AND po.ended_season_id IS NULL AND hi.quantity>0
                """,
                (prop["id"],),
            ).fetchone()
        property_rows.append({
            "id": int(prop["id"]), "slug": prop["slug"], "name": prop["name"],
            "type": prop["property_type"], "address": prop["address"],
            "mapLocation": map_location, "owner": ", ".join(owners) or None,
            "occupants": household_occupants, "inside": inside,
            "value": int(prop["market_value_cents"]) / 100, "status": prop["status"],
            "condition": int(prop["condition_score"]),
            "interiorAvailable": bool(prop["interior_key"]),
            "interiorVariant": int(prop["interior_variant"]),
            "capacity": int(prop["resident_capacity"]),
            "householdCount": household_count,
            "inventoryItems": int(inventory_summary[0] or 0),
            "inventoryUnits": float(inventory_summary[1] or 0),
            "x": float(point[0]) if point else None, "y": float(point[1]) if point else None,
            "business": dict(business) if business else None,
        })
    cash_accounts = [
        int(row[0])
        for row in connection.execute(
            "SELECT id FROM financial_accounts WHERE status='open' AND account_type IN ('cash','chequing','savings','business')"
        )
    ]
    total_cash_cents = sum(account_balance(connection, account_id) for account_id in cash_accounts)
    total_debt_cents = int(connection.execute("SELECT COALESCE(SUM(outstanding_cents),0) FROM debts WHERE status IN ('current','late','defaulted')").fetchone()[0])
    total_investments_cents = int(connection.execute("SELECT COALESCE(SUM(market_value_cents),0) FROM investments").fetchone()[0])
    business_rows = []
    for business in connection.execute("SELECT * FROM businesses ORDER BY name"):
        account = connection.execute("SELECT id FROM financial_accounts WHERE business_id=? AND name='Operating'", (business["id"],)).fetchone()
        employees = int(connection.execute("SELECT COUNT(*) FROM employment e JOIN jobs j ON j.id=e.job_id WHERE j.business_id=? AND e.status='active'", (business["id"],)).fetchone()[0])
        inventory = connection.execute(
            "SELECT COALESCE(SUM(quantity),0),SUM(CASE WHEN quantity<=reorder_point THEN 1 ELSE 0 END),COUNT(*) FROM business_inventory WHERE business_id=?",
            (business["id"],),
        ).fetchone()
        sales = connection.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN e.amount_cents>0 THEN e.amount_cents ELSE 0 END),0)
            FROM transaction_entries e
            JOIN financial_transactions t ON t.id=e.transaction_id
            JOIN financial_accounts a ON a.id=e.account_id
            WHERE a.business_id=? AND t.season_id=?
              AND t.category IN ('retail_purchase','daily_settlement','wholesale_restock')
            """,
            (business["id"], season_id),
        ).fetchone()[0]
        prop = connection.execute("SELECT slug,map_location FROM properties WHERE id=?", (business["property_id"],)).fetchone() if business["property_id"] else None
        owner = connection.execute(
            """
            SELECT COALESCE(r.name,h.name) FROM business_owners own
            LEFT JOIN residents r ON r.id=own.resident_id LEFT JOIN households h ON h.id=own.household_id
            WHERE own.business_id=? AND own.disposed_season_id IS NULL ORDER BY own.id LIMIT 1
            """,
            (business["id"],),
        ).fetchone()
        business_rows.append({
            "id": int(business["id"]), "slug": business["slug"], "name": business["name"],
            "industry": business["industry"], "owner": owner[0] if owner else None,
            "employees": employees, "propertySlug": prop["slug"] if prop else None,
            "location": prop["map_location"] if prop else None,
            "cash": account_balance(connection, int(account[0])) / 100 if account else 0,
            "status": business["status"], "inventoryUnits": float(inventory[0] or 0),
            "lowStockItems": int(inventory[1] or 0), "inventoryItems": int(inventory[2] or 0),
            "sales": int(sales) / 100,
        })
    resident_net_worth = []
    for resident in connection.execute(
        """
        SELECT r.id FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        WHERE l.alive=1 AND l.current_stage IN ('teen','adult','senior')
        """
    ):
        accounts = [
            int(row[0])
            for row in connection.execute(
                """
                SELECT id FROM financial_accounts WHERE resident_id=? AND status='open'
                  AND account_type IN ('cash','chequing','savings')
                """,
                (resident["id"],),
            )
        ]
        liquid = sum(account_balance(connection, account_id) for account_id in accounts)
        investments = int(connection.execute(
            "SELECT COALESCE(SUM(i.market_value_cents),0) FROM investments i JOIN financial_accounts a ON a.id=i.account_id WHERE a.resident_id=?",
            (resident["id"],),
        ).fetchone()[0])
        debt = int(connection.execute(
            "SELECT COALESCE(SUM(d.outstanding_cents),0) FROM debts d JOIN financial_accounts a ON a.id=d.borrower_account_id WHERE a.resident_id=? AND d.status IN ('current','late','defaulted')",
            (resident["id"],),
        ).fetchone()[0])
        resident_net_worth.append(liquid + investments - debt)
    ordered_net_worth = sorted(resident_net_worth)
    median_net_worth = ordered_net_worth[len(ordered_net_worth) // 2] if ordered_net_worth else 0
    recent_transactions = [
        {
            "id": int(row["id"]), "tick": int(row["tick"]), "category": row["category"],
            "description": row["description"], "amount": int(row["volume"]) / 200,
        }
        for row in connection.execute(
            """
            SELECT t.id,t.tick,t.category,t.description,SUM(ABS(e.amount_cents)) volume
            FROM financial_transactions t JOIN transaction_entries e ON e.transaction_id=t.id
            WHERE t.season_id=? AND t.status='posted' GROUP BY t.id ORDER BY t.tick DESC,t.id DESC LIMIT 60
            """,
            (season_id,),
        )
    ]
    economy_history = [
        {
            "season": int(row["season_number"]), "day": int(row["day"]),
            "cash": int(row["cash"]) / 100, "debt": int(row["debt"]) / 100,
            "investments": int(row["investments"]) / 100, "netWorth": int(row["net_worth"]) / 100,
        }
        for row in connection.execute(
            """
            SELECT s.number season_number,fs.day,SUM(fs.cash_cents) cash,SUM(fs.debt_cents) debt,
              SUM(fs.investments_cents) investments,SUM(fs.net_worth_cents) net_worth
            FROM financial_snapshots fs JOIN seasons s ON s.id=fs.season_id
            GROUP BY fs.season_id,fs.day ORDER BY s.number,fs.day LIMIT 140
            """
        )
    ]
    communications = [
        {
            "tick": int(row["tick"]), "caller": row["caller_slug"],
            "callerName": row["caller_name"], "recipient": row["recipient_slug"],
            "recipientName": row["recipient_name"], "purpose": row["purpose"],
            "visibility": row["visibility"], "durationMinutes": int(row["duration_minutes"]),
            "summary": row["summary"] if row["visibility"] == "public" else "Private call",
        }
        for row in connection.execute(
            """
            SELECT c.*,caller.slug caller_slug,caller.name caller_name,
              recipient.slug recipient_slug,recipient.name recipient_name
            FROM communications c JOIN residents caller ON caller.id=c.caller_resident_id
            JOIN residents recipient ON recipient.id=c.recipient_resident_id
            WHERE c.season_id=? ORDER BY c.tick DESC,c.id DESC LIMIT 60
            """,
            (season_id,),
        )
    ]
    accounts = [
        {
            "ownerKind": "resident" if row["resident_id"] else "household" if row["household_id"] else "business",
            "owner": row["owner_name"], "residentSlug": row["resident_slug"],
            "name": row["name"], "type": row["account_type"], "status": row["status"],
            "balance": account_balance(connection, int(row["id"])) / 100,
        }
        for row in connection.execute(
            """
            SELECT a.*,COALESCE(r.name,h.name,b.name) owner_name,r.slug resident_slug
            FROM financial_accounts a
            LEFT JOIN residents r ON r.id=a.resident_id
            LEFT JOIN households h ON h.id=a.household_id
            LEFT JOIN businesses b ON b.id=a.business_id
            ORDER BY CASE WHEN a.resident_id IS NOT NULL THEN 0 WHEN a.household_id IS NOT NULL THEN 1 ELSE 2 END,
              owner_name,a.name
            """
        )
    ]
    relationship_summary = connection.execute(
        """
        SELECT COUNT(*) pairs,COALESCE(SUM(interactions),0) interactions,
          COALESCE(AVG(affinity),0) affinity,COALESCE(AVG(trust),0) trust,
          COALESCE(AVG(tension),0) tension,COALESCE(AVG(familiarity),0) familiarity
        FROM relationships WHERE season_id=?
        """,
        (season_id,),
    ).fetchone()
    strongest_connections = [
        {
            "residentA": row["resident_a_name"], "residentB": row["resident_b_name"],
            "affinity": int(row["affinity"]), "trust": int(row["trust"]),
            "tension": int(row["tension"]), "interactions": int(row["interactions"]),
        }
        for row in connection.execute(
            """
            SELECT a.name resident_a_name,b.name resident_b_name,r.affinity,r.trust,r.tension,r.interactions
            FROM relationships r JOIN residents a ON a.id=r.resident_a JOIN residents b ON b.id=r.resident_b
            WHERE r.season_id=? ORDER BY (r.affinity+r.trust+r.tension) DESC,r.interactions DESC LIMIT 12
            """,
            (season_id,),
        )
    ]
    inventory_by_category = [
        {"category": row["category"], "units": float(row["units"] or 0), "items": int(row["items"] or 0)}
        for row in connection.execute(
            """
            SELECT category,SUM(quantity) units,COUNT(DISTINCT item_id) items FROM (
              SELECT i.category,bi.item_id,bi.quantity FROM business_inventory bi JOIN item_catalog i ON i.id=bi.item_id
              UNION ALL
              SELECT i.category,hi.item_id,hi.quantity FROM household_inventory hi JOIN item_catalog i ON i.id=hi.item_id
              UNION ALL
              SELECT i.category,ri.item_id,ri.quantity FROM resident_inventory ri JOIN item_catalog i ON i.id=ri.item_id
            ) GROUP BY category ORDER BY units DESC
            """
        )
    ]
    movement_summary = [
        {"type": row["movement_type"], "units": float(row["units"] or 0), "events": int(row["events"] or 0)}
        for row in connection.execute(
            """
            SELECT movement_type,SUM(quantity) units,COUNT(*) events FROM inventory_movements
            WHERE season_id=? GROUP BY movement_type ORDER BY units DESC
            """,
            (season_id,),
        )
    ]
    price_history = [
        {"day": int(row["day"]), "averagePrice": int(row["average_price"] or 0) / 100, "unitsSold": float(row["units_sold"] or 0)}
        for row in connection.execute(
            """
            SELECT day,AVG(average_price_cents) average_price,SUM(units_sold) units_sold
            FROM price_history WHERE season_id=? AND units_sold>0 GROUP BY day ORDER BY day
            """,
            (season_id,),
        )
    ]
    transaction_stats = connection.execute(
        """
        SELECT COUNT(DISTINCT t.id) transactions,
          COALESCE(SUM(ABS(e.amount_cents)),0)/2 volume
        FROM financial_transactions t LEFT JOIN transaction_entries e ON e.transaction_id=t.id
        WHERE t.season_id=? AND t.status='posted'
        """,
        (season_id,),
    ).fetchone()
    service_revenue = int(connection.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN e.amount_cents>0 THEN e.amount_cents ELSE 0 END),0)
        FROM financial_transactions t JOIN transaction_entries e ON e.transaction_id=t.id
        JOIN financial_accounts a ON a.id=e.account_id
        WHERE t.season_id=? AND t.status='posted' AND a.business_id IS NOT NULL
          AND e.memo LIKE '%service:%'
        """,
        (season_id,),
    ).fetchone()[0])
    goods_sold = float(connection.execute(
        """
        SELECT COALESCE(SUM(quantity),0) FROM inventory_movements
        WHERE season_id=? AND movement_type='purchase'
        """,
        (season_id,),
    ).fetchone()[0])
    economy_indicators, economy_metric_history = _economy_v22(
        connection, season_id, resident_net_worth
    )
    housing_recovery = _housing_recovery(connection, season_id)
    economy_indicators["shelterOccupancy"] = housing_recovery["shelterResidents"]
    health_conditions = _health_details(connection)
    care_schedules = _care_schedules(connection)
    season_number = int(connection.execute("SELECT number FROM seasons WHERE id=?", (season_id,)).fetchone()[0])
    stage_counts = {
        str(row["current_stage"]): int(row["residents"])
        for row in connection.execute(
            "SELECT current_stage,COUNT(*) residents FROM resident_lifecycle WHERE alive=1 GROUP BY current_stage"
        )
    }
    living_count = sum(stage_counts.values())
    lifecycle_counts = {
        str(row["event_type"]): int(row["events"])
        for row in connection.execute(
            "SELECT event_type,COUNT(*) events FROM life_events WHERE event_type IN ('birth','arrival','death') GROUP BY event_type"
        )
    }
    arrivals = int(connection.execute(
        """
        SELECT COUNT(DISTINCT lep.resident_id) FROM life_event_participants lep
        JOIN life_events le ON le.id=lep.life_event_id
        WHERE le.event_type='arrival' AND lep.role='newcomer'
        """
    ).fetchone()[0])
    housing = connection.execute(
        """
        SELECT
          COALESCE(SUM(p.resident_capacity),0) capacity,
          COALESCE(SUM(CASE WHEN p.property_type='apartment' THEN p.resident_capacity ELSE 0 END),0) apartment_capacity,
          COUNT(*) properties,
          SUM(CASE WHEN p.property_type='apartment' THEN 1 ELSE 0 END) apartments
        FROM properties p
        WHERE p.property_type IN ('house','apartment','shelter') AND p.status<>'demolished'
        """
    ).fetchone()
    active_leases = int(connection.execute(
        "SELECT COUNT(*) FROM property_occupancy WHERE ended_season_id IS NULL"
    ).fetchone()[0])
    apartment_residents = int(connection.execute(
        """
        SELECT COUNT(DISTINCT hm.resident_id) FROM property_occupancy po
        JOIN properties p ON p.id=po.property_id AND p.property_type='apartment'
        JOIN household_members hm ON hm.household_id=po.household_id AND hm.ended_season_id IS NULL
        JOIN resident_lifecycle rl ON rl.resident_id=hm.resident_id AND rl.alive=1
        WHERE po.ended_season_id IS NULL
        """
    ).fetchone()[0])
    shared_buildings = int(connection.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT property_id FROM property_occupancy WHERE ended_season_id IS NULL
          GROUP BY property_id HAVING COUNT(*)>1
        )
        """
    ).fetchone()[0])
    exterior_season = _season_chapter(season_number)
    map_assets = {
        name: f"/assets/kvsim-town-v21-{name}.webp"
        for name in ("spring", "summer", "fall", "winter")
    }
    return {
        "world": {
            "width": 4608, "height": 3072, "coordinateSpace": "legacy",
            "mapAsset": map_assets[exterior_season],
            "mapAssets": map_assets,
            "interiorsAsset": "/assets/interiors-v4.png",
            "weatherAsset": "/assets/weather-seasons-v1.png",
            "inventoryAsset": "/assets/inventory-items-v2.png",
            "eventAsset": "/assets/event-props-v21.png",
        },
        "ledger": ledger,
        "townEvents": ledger,
        "ledgerVerification": ledger_verification,
        "epilogues": [entry for entry in ledger if entry["epilogue"]],
        "goalEvidence": _goal_evidence(connection, season_id),
        "careSchedules": care_schedules,
        "healthConditions": health_conditions,
        "housingRecovery": housing_recovery,
        "modelCircuits": _model_circuits(connection, season_id),
        "households": households,
        "families": families,
        "properties": property_rows,
        "buildings": property_rows,
        "communications": communications,
        "analytics": {
            "relationships": {
                "pairs": int(relationship_summary["pairs"] or 0),
                "interactions": int(relationship_summary["interactions"] or 0),
                "affinity": round(float(relationship_summary["affinity"] or 0), 1),
                "trust": round(float(relationship_summary["trust"] or 0), 1),
                "tension": round(float(relationship_summary["tension"] or 0), 1),
                "familiarity": round(float(relationship_summary["familiarity"] or 0), 1),
            },
            "strongestConnections": strongest_connections,
            "inventoryByCategory": inventory_by_category,
            "movements": movement_summary,
            "prices": price_history,
            "population": {
                "living": living_count,
                "target": population_target_for_season(season_number),
                "stages": stage_counts,
                "births": lifecycle_counts.get("birth", 0),
                "arrivals": arrivals,
                "deaths": lifecycle_counts.get("death", 0),
                "activeHouseholds": len(households),
            },
            "housing": {
                "residents": living_count,
                "capacity": int(housing["capacity"] or 0),
                "available": max(0, int(housing["capacity"] or 0) - living_count),
                "properties": int(housing["properties"] or 0),
                "activeLeases": active_leases,
                "apartments": int(housing["apartments"] or 0),
                "apartmentResidents": apartment_residents,
                "apartmentCapacity": int(housing["apartment_capacity"] or 0),
                "sharedBuildings": shared_buildings,
            },
            "economy": economy_indicators,
            "care": {
                "scheduledBlocks": len(care_schedules),
                "dependents": len({item["resident"] for item in care_schedules}),
            },
            "health": {
                "activeConditions": len(health_conditions),
                "recovering": sum(item["status"] == "recovering" for item in health_conditions),
                "contagious": sum(item["contagious"] for item in health_conditions),
            },
        },
        "economy": {
            "currency": "CAD", "totalCash": total_cash_cents / 100,
            "totalDebt": total_debt_cents / 100, "totalInvestments": total_investments_cents / 100,
            "medianNetWorth": median_net_worth / 100,
            "employed": int(connection.execute("SELECT COUNT(*) FROM employment WHERE status='active'").fetchone()[0]),
            "unemployed": int(connection.execute("SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1 AND current_stage='adult'").fetchone()[0]) - int(connection.execute("SELECT COUNT(*) FROM employment WHERE status='active'").fetchone()[0]),
            "businesses": business_rows,
            "accounts": accounts,
            "transactions": recent_transactions,
            "history": economy_history,
            "catalogItems": int(connection.execute("SELECT COUNT(*) FROM item_catalog WHERE active=1").fetchone()[0]),
            "stockUnits": float(connection.execute("SELECT COALESCE(SUM(quantity),0) FROM business_inventory").fetchone()[0]),
            "barters": int(connection.execute("SELECT COUNT(*) FROM barter_transactions WHERE season_id=?", (season_id,)).fetchone()[0]),
            "phoneCalls": int(connection.execute("SELECT COUNT(*) FROM communications WHERE season_id=?", (season_id,)).fetchone()[0]),
            "transactionCount": int(transaction_stats["transactions"] or 0),
            "transactionVolume": int(transaction_stats["volume"] or 0) / 100,
            "businessRevenue": sum(float(business["sales"] or 0) for business in business_rows),
            "serviceRevenue": service_revenue / 100,
            "goodsSold": goods_sold,
            "indicators": economy_indicators,
            "metricHistory": economy_metric_history,
        },
        "seasonSummaries": [
            {
                "id": row["id"], "number": row["number"], "status": row["status"],
                "progressPercent": round(100 * int(row["current_tick"]) / max(1, int(row["target_ticks"])), 2),
            }
            for row in connection.execute("SELECT id,number,status,current_tick,target_ticks FROM seasons ORDER BY number DESC LIMIT 20")
        ],
    }


def _state(connection: sqlite3.Connection, settings: Settings) -> dict[str, Any]:
    season = _season(connection)
    if not season:
        return {
            "schemaVersion": 3,
            "ok": True,
            "season": None,
            "models": {
                "primary": settings.primary_model,
                "primaryReasoning": settings.primary_reasoning,
                "fallback": settings.fallback_model,
                "fallbackReasoning": settings.fallback_reasoning,
            },
            "currentEvent": None,
            "residents": [],
            "poll": None,
            "usage": {
                "calls": 0,
                "callLimit": settings.call_limit,
                "totalTokens": 0,
                "tokenGuard": settings.token_guard,
                "inputTokens": 0,
                "cachedInputTokens": 0,
                "outputTokens": 0,
                "reasoningTokens": 0,
                "models": {},
            },
            "events": [],
            "eventKinds": list(PUBLIC_EVENT_KINDS),
            "conversations": [],
            "goals": [],
            "lifeGoals": [],
            "props": [],
            "chronicles": [],
            "report": None,
            "ledger": [],
            "townEvents": [],
            "ledgerVerification": {"available": False, "verified": 0, "unverified": 0, "legacy": 0, "participantLinks": 0},
            "epilogues": [],
            "goalEvidence": [],
            "careSchedules": [],
            "healthConditions": [],
            "housingRecovery": {"available": False, "trackingLabel": "Recovery tracking unavailable", "shelterResidents": 0, "shelterHouseholds": 0, "residents": [], "plans": []},
            "modelCircuits": {"available": False, "summaryLabel": "Circuit telemetry unavailable", "circuits": []},
            "docket": {"source": "authoritative-ledger", "entries": [], "activeGoals": [], "lifeGoals": [], "epilogues": []},
            "world": {
                "width": 4608,
                "height": 3072,
                "coordinateSpace": "legacy",
                "mapAsset": "/assets/kvsim-town-v21-spring.webp",
                "mapAssets": {
                    name: f"/assets/kvsim-town-v21-{name}.webp"
                    for name in ("spring", "summer", "fall", "winter")
                },
                "interiorsAsset": "/assets/interiors-v4.png",
                "weatherAsset": "/assets/weather-seasons-v1.png",
                "inventoryAsset": "/assets/inventory-items-v2.png",
                "eventAsset": "/assets/event-props-v21.png",
            },
            "updatedAt": now_iso(),
        }
    season_id = int(season["id"])
    residents = []
    indoor_locations = {
        str(value)
        for row in connection.execute(
            "SELECT name,address,map_location FROM properties WHERE interior_key<>'' AND status NOT IN ('closed','demolished')"
        )
        for value in row
        if value
    }
    for row in connection.execute(
        """
        SELECT r.*,s.x,s.y,s.destination_x,s.destination_y,s.location,s.activity,
          s.public_thought,s.intention,s.reflection,s.mood,s.needs_json,s.path_json,
          s.action_until_tick,s.updated_tick,v.life_stage,v.stage_season_index,
          v.decision_state,v.current_decision_id,v.household_id,v.care_state,
          v.current_caregiver_id,v.current_care_provider_id,
          caregiver.name caregiver_name,care_provider.name care_provider_name,
          h.name household_name
        FROM residents r JOIN resident_state s ON s.resident_id=r.id
        LEFT JOIN resident_season_state v
          ON v.resident_id=r.id AND v.season_id=s.season_id
        LEFT JOIN residents caregiver ON caregiver.id=v.current_caregiver_id
        LEFT JOIN businesses care_provider ON care_provider.id=v.current_care_provider_id
        LEFT JOIN households h ON h.id=v.household_id
        WHERE s.season_id=? ORDER BY r.id
        """,
        (season_id,),
    ):
        residents.append(_resident_base_v2(connection, season_id, row, indoor_locations))
    recent = [
        serialize_public_event(row)
        for row in connection.execute(
            "SELECT * FROM event_stream WHERE season_id=? ORDER BY seq DESC LIMIT 60", (season_id,)
        )
    ][::-1]
    report = connection.execute("SELECT * FROM reports WHERE season_id=?", (season_id,)).fetchone()
    current_event = connection.execute(
        "SELECT * FROM town_events WHERE season_id=? ORDER BY day DESC,id DESC LIMIT 1", (season_id,)
    ).fetchone()
    conversations = [
        {
            "tick": int(row["tick"]),
            "residentA": row["a_slug"],
            "residentAName": row["a_name"],
            "residentB": row["b_slug"],
            "residentBName": row["b_name"],
            "location": row["location"],
            "dialogue": loads(row["dialogue_json"], []),
            "summary": row["summary"],
        }
        for row in connection.execute(
            """
            SELECT c.*,a.slug a_slug,a.name a_name,b.slug b_slug,b.name b_name
            FROM conversations c JOIN residents a ON a.id=c.resident_a
            JOIN residents b ON b.id=c.resident_b
            WHERE c.season_id=? ORDER BY c.id DESC LIMIT 12
            """,
            (season_id,),
        )
    ][::-1]
    goal_evidence = _goal_evidence(connection, season_id)
    life_goals = _life_goals(connection)
    evidence_by_goal: dict[int, list[dict[str, Any]]] = {}
    for item in goal_evidence:
        if item["goalId"] is not None:
            evidence_by_goal.setdefault(int(item["goalId"]), []).append(item)
    goals = [
        {
            "id": int(row["id"]),
            "resident": row["slug"],
            "residentName": row["name"],
            "scope": row["scope"],
            "description": row["description"],
            "status": row["status"],
            "progress": int(row["progress"]),
            "evidence": evidence_by_goal.get(int(row["id"]), []),
            "evidenceCount": len(evidence_by_goal.get(int(row["id"]), [])),
        }
        for row in connection.execute(
            """
            SELECT g.*,r.slug,r.name FROM goals g JOIN residents r ON r.id=g.resident_id
            WHERE g.season_id=? ORDER BY g.status,g.scope,g.id LIMIT 36
            """,
            (season_id,),
        )
    ]
    props = [
        {
            "location": row["location"],
            "prop": row["prop"],
            "status": row["status"],
            "createdTick": int(row["created_tick"]),
        }
        for row in connection.execute(
            "SELECT * FROM world_props WHERE season_id=? AND status='present' ORDER BY id",
            (season_id,),
        )
    ]
    chronicle_columns = _table_columns(connection, "daily_chronicles")
    chronicles = []
    for row in connection.execute(
        "SELECT * FROM daily_chronicles WHERE season_id=? ORDER BY day", (season_id,)
    ):
        status = _row_value(row, "verification_status")
        verified = _row_value(row, "verified")
        chronicles.append({
            "day": int(row["day"]), "title": row["title"], "narrative": row["narrative"],
            "source": str(_row_value(row, "source", default="legacy_model")),
            "ledgerIds": loads(_row_value(row, "ledger_ids_json", default="[]"), []),
            "verificationStatus": str(status) if status is not None else (
                "verified" if verified else "unverified" if verified is not None else "legacy"
            ),
            "verified": bool(verified) if "verified" in chronicle_columns else None,
        })
    town = _town_v2(connection, season_id)
    docket_entries = [entry for entry in town["ledger"] if not entry["epilogue"]][:16]
    complete = season["status"] == "complete"
    return {
        "schemaVersion": 3,
        "release": {"version": __version__, "commit": settings.release_commit},
        "ok": True,
        "season": {
            "id": season_id,
            "number": int(season["number"]),
            "status": season["status"],
            "tick": int(season["current_tick"]),
            "targetTicks": int(season["target_ticks"]),
            "day": int(season["current_day"]),
            "worldMinutes": int(season["world_minutes"]),
            "progressPercent": 100.0 if complete else round(
                100 * int(season["current_tick"]) / max(1, int(season["target_ticks"])), 2
            ),
            "seedCommitment": season["seed_commitment"],
            "revealedSeed": season["seed_hex"] if season["seed_revealed"] else None,
            "modelLocked": bool(season["model_locked"]),
            "modelDegraded": bool(season["model_degraded"]),
            "weather": _public_weather(season),
            "startedAt": season["started_at"],
            "completedAt": season["completed_at"],
            "completionReason": season["completion_reason"],
        },
        "models": {
            "primary": settings.primary_model,
            "primaryReasoning": settings.primary_reasoning,
            "fallback": settings.fallback_model,
            "fallbackReasoning": settings.fallback_reasoning,
        },
        "currentEvent": (
            {
                "day": int(current_event["day"]),
                "slug": current_event["slug"],
                "title": current_event["title"],
                "category": current_event["category"],
                "summary": current_event["summary"],
                "prop": current_event["prop"],
                "strange": bool(current_event["strange"]),
                "participants": loads(current_event["participants_json"], []),
            }
            if current_event else None
        ),
        "residents": residents,
        "poll": _poll_payload(connection, season_id),
        "usage": _usage(connection, season_id, settings),
        "events": recent,
        "eventKinds": list(PUBLIC_EVENT_KINDS),
        "conversations": conversations,
        "goals": goals,
        "lifeGoals": life_goals,
        "props": props,
        "chronicles": chronicles,
        "docket": {
            "source": "authoritative-ledger",
            "entries": docket_entries,
            "activeGoals": [goal for goal in goals if goal["status"] in {"active", "pursuing"}],
            "lifeGoals": [goal for goal in life_goals if goal["status"] == "active"],
            "epilogues": town["epilogues"],
            "verification": town["ledgerVerification"],
        },
        "report": (
            {
                "headline": report["headline"],
                "narrative": report["narrative"],
                "poster": f"/reports/season-{int(season['number']):03d}.png",
                "statistics": loads(report["statistics_json"], {}),
            }
            if report else None
        ),
        **town,
        "updatedAt": now_iso(),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    schema = open_database(settings, readonly=True)
    schema.close()
    security = VoteSecurity(settings.voter_secret)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        yield

    app = FastAPI(title="Krabville Public API", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["krab.canadaverse.org", "127.0.0.1", "localhost", "testserver"],
    )

    @app.middleware("http")
    async def harden(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Robots-Tag"] = "noindex, noarchive"
        if response.headers.get("Content-Type", "").lower().startswith("text/html"):
            response.headers["Cache-Control"] = "no-store, no-transform"
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        if not security.voter_key(request.cookies.get("kv_voter")):
            response.set_cookie("kv_voter", security.new_voter_cookie(), httponly=True, secure=secure, samesite="lax", max_age=7776000)
        if not request.cookies.get("kv_csrf"):
            response.set_cookie("kv_csrf", new_csrf(), httponly=False, secure=secure, samesite="lax", max_age=86400)
        return response

    def runtime_health() -> dict[str, Any]:
        connection = connect(settings.database_path, readonly=True)
        try:
            schema_version = applied_schema_version(connection)
            required_schema = required_schema_version()
            schema_current = schema_version == required_schema
            season = _season(connection)
            result = diagnose(
                connection,
                tick_seconds=settings.tick_seconds,
                tick_stale_seconds=settings.tick_stale_seconds,
            )
            season_payload = (
                {
                    "number": int(season["number"]),
                    "status": season["status"],
                    "day": int(season["current_day"]),
                    "tick": int(season["current_tick"]),
                    "targetTicks": int(season["target_ticks"]),
                    "progressPercent": round(
                        (int(season["current_tick"]) / int(season["target_ticks"])) * 100,
                        2,
                    ),
                    "modelLocked": bool(season["model_locked"]),
                    "modelDegraded": bool(season["model_degraded"]),
                }
                if season
                else None
            )
            return {
                **result,
                "ok": result["ok"] and schema_current,
                "status": result["status"] if schema_current else "failed",
                "release": {"version": __version__, "commit": settings.release_commit},
                "schema": {
                    "version": schema_version,
                    "required": required_schema,
                    "current": schema_current,
                },
                "seasonStatus": season["status"] if season else "draft",
                "season": season_payload,
                "models": {
                    "primary": settings.primary_model,
                    "primaryReasoning": settings.primary_reasoning,
                    "fallback": settings.fallback_model,
                    "fallbackReasoning": settings.fallback_reasoning,
                },
                "usage": _usage(connection, int(season["id"]), settings) if season else None,
                "backup": last_verified_backup(settings),
                "residentCount": result["residents"],
                "updatedAt": now_iso(),
            }
        finally:
            connection.close()

    @app.get("/livez")
    def livez():
        return {"ok": True, "release": {"version": __version__, "commit": settings.release_commit}}

    @app.get("/healthz")
    def healthz():
        payload = runtime_health()
        return JSONResponse(payload, status_code=200 if payload["ok"] else 503)

    @app.get("/readyz")
    def readyz():
        payload = runtime_health()
        ready = payload["database"] == "ok" and payload["schema"]["current"]
        return JSONResponse(payload, status_code=200 if ready else 503)

    @app.get("/metrics")
    def metrics():
        payload = runtime_health()
        runtime = payload["runtime"]
        freshness = runtime["tickFreshness"]
        queue = runtime["queue"]
        season = payload.get("season") or {}
        lines = [
            "# HELP krabville_runtime_healthy Whether database, tick, and queue checks pass.",
            "# TYPE krabville_runtime_healthy gauge",
            f"krabville_runtime_healthy {1 if payload['ok'] else 0}",
            "# HELP krabville_tick Current authoritative simulation tick.",
            "# TYPE krabville_tick gauge",
            f"krabville_tick {int(season.get('tick', 0))}",
            "# HELP krabville_tick_age_seconds Age of the latest persisted tick heartbeat.",
            "# TYPE krabville_tick_age_seconds gauge",
            f"krabville_tick_age_seconds {float(freshness.get('ageSeconds') or 0):.3f}",
            "# HELP krabville_tick_stale Whether a running simulation missed its freshness bound.",
            "# TYPE krabville_tick_stale gauge",
            f"krabville_tick_stale {1 if freshness['stale'] else 0}",
            "# HELP krabville_event_sequence Latest public event sequence.",
            "# TYPE krabville_event_sequence gauge",
            f"krabville_event_sequence {int(runtime['eventSequence'])}",
            "# HELP krabville_model_jobs Model jobs by bounded status.",
            "# TYPE krabville_model_jobs gauge",
        ]
        for status in ("queued", "leased", "complete", "failed", "cancelled"):
            lines.append(
                f'krabville_model_jobs{{status="{status}"}} {int(queue["counts"].get(status, 0))}'
            )
        lines.extend((
            "# HELP krabville_model_stale_leases Expired model leases awaiting recovery.",
            "# TYPE krabville_model_stale_leases gauge",
            f"krabville_model_stale_leases {int(queue['staleLeases'])}",
            "# HELP krabville_runtime_open_incidents Unresolved authoritative runtime incidents.",
            "# TYPE krabville_runtime_open_incidents gauge",
            f"krabville_runtime_open_incidents {int(runtime['incidents']['open'])}",
            "# HELP krabville_residents Living resident count.",
            "# TYPE krabville_residents gauge",
            f"krabville_residents {int(payload['residentCount'])}",
            "# HELP krabville_backup_verified Whether a verified backup is recorded.",
            "# TYPE krabville_backup_verified gauge",
            f"krabville_backup_verified {1 if payload['backup']['available'] else 0}",
        ))
        return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    @app.get("/api/v3/state")
    @app.get("/api/v2/state")
    def state():
        connection = connect(settings.database_path, readonly=True)
        try:
            return _state(connection, settings)
        finally:
            connection.close()

    @app.get("/api/krabville/state")
    def compatibility_state():
        value = state()
        season = value.get("season") or {}
        return {
            "ok": value["ok"],
            "simulation": "krabville-v2",
            "step": season.get("tick", 0),
            "run": {
                "status": season.get("status", "draft"),
                "current_step": season.get("tick", 0),
                "target_step": season.get("targetTicks", 2016),
                "run_progress_percent": season.get("progressPercent", 0),
                "day": season.get("day", 0),
                "residents": len(value.get("residents", [])),
            },
            "residents": value.get("residents", []),
            "world": {"weather": season.get("weather"), "today_event": value.get("currentEvent"), "week_report": value.get("report")},
            "tokens": value.get("usage", {}),
        }

    @app.get("/api/v3/events")
    @app.get("/api/v2/events")
    def events(after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            if not season:
                return {"events": [], "next": after, "eventKinds": list(PUBLIC_EVENT_KINDS)}
            rows = list(
                connection.execute(
                    "SELECT * FROM event_stream WHERE season_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (season["id"], after, limit),
                )
            )
            items = [serialize_public_event(row) for row in rows]
            return {
                "events": items,
                "next": items[-1]["seq"] if items else after,
                "eventKinds": list(PUBLIC_EVENT_KINDS),
            }
        finally:
            connection.close()

    @app.get("/api/v3/events/stream")
    @app.get("/api/v2/events/stream")
    async def event_stream(request: Request, last_event_id: str | None = Header(None, alias="Last-Event-ID")):
        start = int(last_event_id or request.query_params.get("after") or 0)

        async def stream():
            cursor = start
            while not await request.is_disconnected():
                connection = connect(settings.database_path, readonly=True)
                try:
                    season = _season(connection)
                    rows = list(
                        connection.execute(
                            "SELECT * FROM event_stream WHERE season_id=? AND seq>? ORDER BY seq LIMIT 100",
                            (season["id"], cursor),
                        ) if season else []
                    )
                finally:
                    connection.close()
                if rows:
                    for row in rows:
                        cursor = int(row["seq"])
                        data = json.dumps(serialize_public_event(row), separators=(",", ":"))
                        yield f"id: {cursor}\nevent: {row['event_type']}\ndata: {data}\n\n"
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.get("/api/v3/economy")
    def economy():
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            if not season:
                return {"economy": {}, "households": [], "properties": []}
            town = _town_v2(connection, int(season["id"]))
            return {
                "economy": town["economy"], "households": town["households"],
                "properties": town["properties"], "updatedAt": now_iso(),
            }
        finally:
            connection.close()

    @app.get("/api/v3/properties/{slug}")
    @app.get("/api/v3/buildings/{slug}")
    def property_detail(slug: str):
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            prop = connection.execute("SELECT * FROM properties WHERE slug=?", (slug,)).fetchone()
            if not prop:
                raise HTTPException(404, "property not found")
            season_id = int(season["id"]) if season else 0
            map_location = str(prop["map_location"] or prop["address"])
            residents = [
                {"slug": row["slug"], "name": row["name"], "activity": row["activity"], "mood": row["mood"]}
                for row in connection.execute(
                    """
                    SELECT r.slug,r.name,s.activity,s.mood FROM resident_state s
                    JOIN residents r ON r.id=s.resident_id
                    WHERE s.season_id=? AND s.location=? AND s.path_json='[]' ORDER BY r.id
                    """,
                    (season_id, map_location),
                )
            ]
            households = [
                {"id": int(row["id"]), "name": row["name"]}
                for row in connection.execute(
                    """
                    SELECT h.id,h.name FROM property_occupancy po JOIN households h ON h.id=po.household_id
                    WHERE po.property_id=? AND po.ended_season_id IS NULL
                    """,
                    (prop["id"],),
                )
            ]
            business = connection.execute("SELECT * FROM businesses WHERE property_id=? ORDER BY id DESC LIMIT 1", (prop["id"],)).fetchone()
            stock = []
            transactions = []
            if business:
                stock = [
                    {
                        "name": row["name"], "category": row["category"],
                        "quantity": float(row["quantity"]), "price": int(row["price_cents"]) / 100,
                        "lowStock": float(row["quantity"]) <= float(row["reorder_point"]),
                        "assetKey": row["asset_key"], "assetIndex": item_asset_index(str(row["asset_key"])),
                    }
                    for row in connection.execute(
                        """
                        SELECT i.id item_id,i.name,i.category,i.asset_key,bi.quantity,bi.price_cents,bi.reorder_point
                        FROM business_inventory bi JOIN item_catalog i ON i.id=bi.item_id
                        WHERE bi.business_id=? ORDER BY i.category,i.name
                        """,
                        (business["id"],),
                    )
                ]
                transactions = [
                    {
                        "id": int(row["id"]), "tick": int(row["tick"]),
                        "category": row["category"], "description": row["description"],
                        "amount": int(row["amount"]) / 100,
                    }
                    for row in connection.execute(
                        """
                        SELECT t.id,t.tick,t.category,t.description,SUM(e.amount_cents) amount
                        FROM financial_transactions t JOIN transaction_entries e ON e.transaction_id=t.id
                        JOIN financial_accounts a ON a.id=e.account_id
                        WHERE a.business_id=? AND t.status='posted' GROUP BY t.id
                        ORDER BY t.tick DESC,t.id DESC LIMIT 40
                        """,
                        (business["id"],),
                    )
                ]
            home_stock = []
            for household in households:
                home_stock.extend(
                    {
                        "name": row["name"], "category": row["category"],
                        "quantity": float(row["quantity"]), "assetKey": row["asset_key"],
                        "assetIndex": item_asset_index(str(row["asset_key"])),
                    }
                    for row in connection.execute(
                        """
                        SELECT i.id item_id,i.name,i.category,i.asset_key,hi.quantity FROM household_inventory hi
                        JOIN item_catalog i ON i.id=hi.item_id
                        WHERE hi.household_id=? AND hi.quantity>0 ORDER BY i.category,i.name
                        """,
                        (household["id"],),
                    )
                )
            return {
                "id": int(prop["id"]), "slug": prop["slug"], "name": prop["name"],
                "type": prop["property_type"], "address": prop["address"],
                "mapLocation": map_location, "status": prop["status"],
                "condition": int(prop["condition_score"]), "value": int(prop["market_value_cents"]) / 100,
                "interiorVariant": int(prop["interior_variant"]), "residents": residents,
                "capacity": int(prop["resident_capacity"]),
                "householdCount": len(households),
                "households": households, "business": dict(business) if business else None,
                "inventory": stock or home_stock, "transactions": transactions,
            }
        finally:
            connection.close()

    @app.get("/api/v3/residents/{slug}")
    @app.get("/api/v2/residents/{slug}")
    def resident(slug: str):
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            if not season:
                raise HTTPException(404, "season not found")
            resident_row = connection.execute(
                """
                SELECT r.*,s.x,s.y,s.destination_x,s.destination_y,s.location,s.activity,
                  s.public_thought,s.intention,s.reflection,s.mood,s.needs_json,s.path_json,
                  s.action_until_tick,s.updated_tick,v.life_stage,v.stage_season_index,
                  v.decision_state,v.current_decision_id,v.household_id,v.care_state,
                  v.current_caregiver_id,v.current_care_provider_id,
                  caregiver.name caregiver_name,care_provider.name care_provider_name,
                  h.name household_name
                FROM residents r JOIN resident_state s ON s.resident_id=r.id
                LEFT JOIN resident_season_state v
                  ON v.resident_id=r.id AND v.season_id=s.season_id
                LEFT JOIN residents caregiver ON caregiver.id=v.current_caregiver_id
                LEFT JOIN businesses care_provider ON care_provider.id=v.current_care_provider_id
                LEFT JOIN households h ON h.id=v.household_id
                WHERE s.season_id=? AND r.slug=?
                """,
                (season["id"], slug),
            ).fetchone()
            if not resident_row:
                raise HTTPException(404, "resident not found")
            resident_id = int(resident_row["id"])
            indoor_locations = {
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT map_location FROM properties WHERE interior_key<>'' AND status NOT IN ('closed','demolished')"
                )
                if row[0]
            }
            base = _resident_base_v2(
                connection, int(season["id"]), resident_row, indoor_locations
            )
            resident_evidence = _goal_evidence(connection, int(season["id"]), resident_id)
            evidence_by_goal: dict[int, list[dict[str, Any]]] = {}
            for item in resident_evidence:
                if item["goalId"] is not None:
                    evidence_by_goal.setdefault(int(item["goalId"]), []).append(item)
            goals = []
            for item in connection.execute(
                "SELECT id,scope,description,status,progress FROM goals WHERE season_id=? AND resident_id=? ORDER BY id DESC LIMIT 12",
                (season["id"], resident_id),
            ):
                goal = dict(item)
                goal["evidence"] = evidence_by_goal.get(int(item["id"]), [])
                goal["evidenceCount"] = len(goal["evidence"])
                goals.append(goal)
            memories = [dict(item) for item in connection.execute("SELECT kind,content,tags,valence,salience,location,created_tick FROM memories WHERE season_id=? AND resident_id=? ORDER BY created_tick DESC,id DESC LIMIT 20", (season["id"], resident_id))]
            relationships = [dict(item) for item in connection.execute("""
                SELECT CASE WHEN rel.resident_a=? THEN b.slug ELSE a.slug END otherSlug,
                  CASE WHEN rel.resident_a=? THEN b.name ELSE a.name END otherName,
                  rel.affinity,rel.trust,rel.tension,rel.familiarity,rel.interactions,
                  rel.attraction,rel.affection,rel.respect,rel.commitment,rel.resentment
                FROM relationships rel JOIN residents a ON a.id=rel.resident_a JOIN residents b ON b.id=rel.resident_b
                WHERE rel.season_id=? AND (rel.resident_a=? OR rel.resident_b=?)
                ORDER BY (rel.affinity+rel.trust-rel.tension) DESC
                """, (resident_id, resident_id, season["id"], resident_id, resident_id))]
            return {
                **base,
                "goals": goals, "memories": memories, "relationships": relationships,
                **_resident_detail_v2(connection, int(season["id"]), resident_id),
            }
        finally:
            connection.close()

    @app.get("/api/v3/relationships")
    @app.get("/api/v2/relationships")
    def relationships():
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            if not season:
                return {"relationships": []}
            rows = connection.execute("""
                SELECT a.slug aSlug,a.name aName,b.slug bSlug,b.name bName,
                  r.affinity,r.trust,r.tension,r.familiarity,r.interactions,r.last_interaction_tick lastInteractionTick
                FROM relationships r JOIN residents a ON a.id=r.resident_a JOIN residents b ON b.id=r.resident_b
                WHERE r.season_id=? ORDER BY (r.affinity+r.trust-r.tension) DESC
                """, (season["id"],))
            return {"relationships": [dict(row) for row in rows]}
        finally:
            connection.close()

    @app.get("/api/v3/polls/current")
    @app.get("/api/v2/polls/current")
    def current_poll():
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            return {"poll": _poll_payload(connection, int(season["id"])) if season else None}
        finally:
            connection.close()

    @app.post("/api/v3/polls/{poll_id}/vote")
    @app.post("/api/v2/polls/{poll_id}/vote")
    def vote(poll_id: int, body: VoteRequest, request: Request, kv_voter: str | None = Cookie(None), kv_csrf: str | None = Cookie(None)):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in {settings.public_origin.rstrip("/"), "http://127.0.0.1:18889", "http://127.0.0.1:18890", "http://testserver"}:
            raise HTTPException(403, "origin rejected")
        if not kv_csrf or not secrets_compare(kv_csrf, body.csrfToken):
            raise HTTPException(403, "csrf rejected")
        voter_key = security.voter_key(kv_voter)
        if not voter_key:
            raise HTTPException(401, "voter cookie required")
        address = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
        network_key = security.network_key(address)
        if not security.check_rate(network_key):
            raise HTTPException(429, "vote rate limit reached")
        connection = connect(settings.database_path)
        try:
            with transaction(connection, immediate=True):
                poll = connection.execute("SELECT * FROM polls WHERE id=?", (poll_id,)).fetchone()
                if not poll or poll["status"] != "open":
                    raise HTTPException(409, "poll is not open")
                option = connection.execute("SELECT * FROM poll_options WHERE poll_id=? AND choice_id=?", (poll_id, body.choiceId)).fetchone()
                if not option:
                    raise HTTPException(422, "invalid choice")
                connection.execute("""
                    INSERT INTO votes(poll_id,voter_key,network_key,option_id,updated_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(poll_id,voter_key) DO UPDATE SET
                      network_key=excluded.network_key,option_id=excluded.option_id,updated_at=excluded.updated_at
                    """, (poll_id, voter_key, network_key, option["id"], now_iso()))
                connection.execute("""
                    UPDATE poll_options SET votes=(SELECT COUNT(*) FROM votes WHERE votes.option_id=poll_options.id)
                    WHERE poll_id=?
                    """, (poll_id,))
            return {"ok": True, "poll": _poll_payload(connection, int(poll["season_id"]))}
        finally:
            connection.close()

    @app.get("/api/v3/seasons")
    @app.get("/api/v2/seasons")
    def seasons():
        connection = connect(settings.database_path, readonly=True)
        try:
            rows = connection.execute("SELECT id,number,status,created_at,started_at,completed_at,seed_commitment,seed_hex,seed_revealed,current_tick,target_ticks FROM seasons ORDER BY number DESC LIMIT 104")
            return {"seasons": [{"id": row["id"], "number": row["number"], "status": row["status"], "createdAt": row["created_at"], "startedAt": row["started_at"], "completedAt": row["completed_at"], "seedCommitment": row["seed_commitment"], "revealedSeed": row["seed_hex"] if row["seed_revealed"] else None, "progressPercent": round(100 * row["current_tick"] / max(1, row["target_ticks"]), 2)} for row in rows]}
        finally:
            connection.close()

    @app.get("/api/v3/seasons/{season_id}")
    @app.get("/api/v2/seasons/{season_id}")
    def season_detail(season_id: int):
        connection = connect(settings.database_path, readonly=True)
        try:
            season = connection.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
            if not season:
                raise HTTPException(404, "season not found")
            chronicles = [dict(row) for row in connection.execute("SELECT * FROM daily_chronicles WHERE season_id=? ORDER BY day", (season_id,))]
            report = connection.execute("SELECT * FROM reports WHERE season_id=?", (season_id,)).fetchone()
            ledger, ledger_verification = _story_ledger(connection, season_id, limit=500)
            public_season = {
                "id": int(season["id"]),
                "number": int(season["number"]),
                "status": season["status"],
                "createdAt": season["created_at"],
                "startedAt": season["started_at"],
                "completedAt": season["completed_at"],
                "seedCommitment": season["seed_commitment"],
                "revealedSeed": season["seed_hex"] if season["seed_revealed"] else None,
                "currentTick": int(season["current_tick"]),
                "targetTicks": int(season["target_ticks"]),
                "completionReason": season["completion_reason"],
                "weather": _public_weather(season),
            }
            public_chronicles = []
            for row in chronicles:
                statistics = loads(row.pop("statistics_json"), {})
                status = row.pop("verification_status", None)
                verified = row.pop("verified", None)
                ledger_ids = loads(row.pop("ledger_ids_json", "[]"), [])
                public_chronicles.append({
                    "day": int(row["day"]),
                    "title": str(row["title"]),
                    "narrative": str(row["narrative"]),
                    "source": str(row.get("source", "legacy_model")),
                    "createdAt": row.get("created_at"),
                    "statistics": statistics,
                    "ledgerIds": ledger_ids,
                    "verificationStatus": str(status) if status is not None else (
                        "verified" if verified else "unverified" if verified is not None else "legacy"
                    ),
                    "verified": bool(verified) if verified is not None else None,
                })
            public_report = None
            if report:
                public_report = {
                    "headline": report["headline"],
                    "narrative": report["narrative"],
                    "poster": f"/reports/season-{int(season['number']):03d}.png",
                    "statistics": loads(report["statistics_json"], {}),
                    "createdAt": report["created_at"],
                }
            return {
                "season": public_season,
                "chronicles": public_chronicles,
                "report": public_report,
                "ledger": ledger,
                "ledgerVerification": ledger_verification,
                "epilogues": [entry for entry in ledger if entry["epilogue"]],
                "goalEvidence": _goal_evidence(connection, season_id),
                "modelCircuits": _model_circuits(connection, season_id),
            }
        finally:
            connection.close()

    @app.get("/reports/{filename}")
    def report_file(filename: str):
        if not re_report_name(filename):
            raise HTTPException(404, "report not found")
        path = settings.report_dir / filename
        if not path.exists():
            raise HTTPException(404, "report not found")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public,max-age=3600"})

    if settings.frontend_dir.exists():
        asset_path = settings.frontend_dir / "assets"
        if asset_path.exists():
            app.mount("/assets", StaticFiles(directory=asset_path), name="assets")

        @app.get("/{path:path}", response_class=HTMLResponse)
        def frontend(path: str):
            candidate = (settings.frontend_dir / path).resolve()
            if path and candidate.is_file() and settings.frontend_dir in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(settings.frontend_dir / "index.html")

    return app


def secrets_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a, b)


def re_report_name(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"season-\d{3}\.png", value))


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.port, workers=1, proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
