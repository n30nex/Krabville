from __future__ import annotations

import datetime as dt
import hashlib
import heapq
import json
import math
import random
import secrets
import sqlite3
from collections import defaultdict
from typing import Any

from .config import Settings
from .commerce_v2 import (
    claim_due_commitment,
    run_daily_commerce,
    run_phone_window,
    seed_commerce,
)
from .content import (
    LOCATION_ACCESS,
    LOCATION_POINTS,
    MAJOR_EVENTS,
    MICRO_EVENTS,
    PATH_EDGES,
    PATH_NODES,
    EventTemplate,
)
from .db import (
    dumps,
    emit,
    initialize_resident_state,
    loads,
    now_iso,
    resident_rows,
    retrieve_memories,
    transaction,
)
from .runtime_v2 import (
    apply_lifecycle_boundary,
    bootstrap_population,
    grow_population,
    initialize_v2_season_state,
    resident_finances,
    settle_daily_economy,
)
from .population_v2 import ADULT_STAGES
from .simulation_v2 import (
    boredom_score,
    derive_mood,
    generate_short_term_wants,
    normalize_needs,
    score_candidate_actions,
    update_needs,
)


TICKS_PER_DAY = 288
DAYS_PER_SEASON = 7
TARGET_TICKS = TICKS_PER_DAY * DAYS_PER_SEASON
POLL_OPEN_TICK = 24
POLL_CLOSE_TICK = 264


def _rng(seed_hex: str, *parts: object) -> random.Random:
    material = seed_hex + "|" + "|".join(str(part) for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest, "big"))


def _event(slug: str) -> EventTemplate:
    return next(event for event in MAJOR_EVENTS if event.slug == slug)


def _season_row(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM seasons ORDER BY number DESC LIMIT 1"
    ).fetchone()


def current_season(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return _season_row(connection)


def _weather(seed_hex: str, day: int, season_number: int = 1) -> dict[str, Any]:
    rng = _rng(seed_hex, "weather", season_number, day)
    # KVsim 2.1 tells one 20-season generational arc through four five-season
    # climate chapters. Season 20 and later remain winter until a new arc starts.
    season_name = ("spring", "summer", "fall", "winter")[
        min(3, max(0, (season_number - 1) // 5))
    ]
    choices = {
        "spring": (
            ("clear", 15, 10), ("cloudy", 12, 15), ("rain", 10, 19),
            ("rain", 13, 14), ("windy", 11, 27), ("storm", 14, 36), ("fog", 8, 7),
        ),
        "summer": (
            ("clear", 24, 8), ("clear", 27, 11), ("cloudy", 22, 14),
            ("rain", 19, 18), ("windy", 21, 27), ("storm", 23, 34), ("fog", 18, 7),
        ),
        "fall": (
            ("clear", 15, 12), ("cloudy", 12, 17), ("rain", 10, 22),
            ("windy", 9, 32), ("windy", 13, 25), ("storm", 11, 39), ("fog", 7, 9),
        ),
        "winter": (
            ("clear", -6, 9), ("cloudy", -4, 14), ("snow", -7, 18),
            ("snow", -3, 24), ("first-snow", -1, 13), ("windy", -10, 31), ("fog", -5, 8),
        ),
    }[season_name]
    condition, base, wind = rng.choice(choices)
    return {
        "condition": condition,
        "temperatureC": base + rng.randint(-3, 3),
        "windKmh": max(2, wind + rng.randint(-4, 4)),
        "season": season_name,
    }


def _choose_catalyst(
    connection: sqlite3.Connection,
    seed_hex: str,
    day: int,
    preferred_slug: str | None = None,
) -> EventTemplate:
    if preferred_slug:
        try:
            return _event(preferred_slug)
        except StopIteration:
            pass
    recent = {
        row[0]
        for row in connection.execute(
            "SELECT slug FROM town_events ORDER BY id DESC LIMIT 12"
        )
    }
    candidates = [event for event in MAJOR_EVENTS if event.slug not in recent]
    return _rng(seed_hex, "catalyst", day).choice(candidates or list(MAJOR_EVENTS))


def _participant_slugs(connection: sqlite3.Connection, seed_hex: str, day: int) -> list[str]:
    slugs = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT r.slug FROM residents r
            JOIN resident_lifecycle l ON l.resident_id=r.id
            WHERE l.alive=1 ORDER BY r.id
            """
        )
    ]
    return _rng(seed_hex, "participants", day).sample(slugs, min(2, len(slugs)))


def _queue_job(
    connection: sqlite3.Connection,
    season_id: int,
    day: int,
    tick: int,
    kind: str,
    priority: int,
    context: dict[str, Any],
) -> int | None:
    existing = connection.execute(
        "SELECT id FROM model_jobs WHERE season_id=? AND day=? AND kind=? AND context_json=?",
        (season_id, day, kind, dumps(context)),
    ).fetchone()
    if existing:
        return None
    created = now_iso()
    cursor = connection.execute(
        """
        INSERT INTO model_jobs(
          season_id,day,tick,kind,priority,status,context_json,created_at,updated_at
        ) VALUES(?,?,?,?,?,'queued',?,?,?)
        """,
        (season_id, day, tick, kind, priority, dumps(context), created, created),
    )
    emit(connection, season_id, tick, "model_job", {"kind": kind, "status": "queued"})
    return int(cursor.lastrowid)


def _day_event(
    connection: sqlite3.Connection,
    season: sqlite3.Row,
    day: int,
    catalyst_slug: str | None,
) -> EventTemplate:
    event = _choose_catalyst(connection, season["seed_hex"], day, catalyst_slug)
    participants = _participant_slugs(connection, season["seed_hex"], day)
    cursor = connection.execute(
        """
        INSERT INTO town_events(
          season_id,day,tick,slug,title,category,summary,prop,strange,
          participants_json,source,relationship_delta_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            season["id"],
            day,
            day * TICKS_PER_DAY,
            event.slug,
            event.title,
            event.category,
            event.summary,
            event.prop,
            int(event.strange),
            dumps(participants),
            "vote" if catalyst_slug else "random",
            "{}",
        ),
    )
    event_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO world_props(season_id,event_id,location,prop,created_tick)
        VALUES(?,?,?,?,?)
        """,
        (season["id"], event_id, "Town Square", event.prop, day * TICKS_PER_DAY),
    )
    emit(
        connection,
        season["id"],
        day * TICKS_PER_DAY,
        "town_event",
        {
            "day": day,
            "slug": event.slug,
            "title": event.title,
            "category": event.category,
            "summary": event.summary,
            "prop": event.prop,
            "strange": event.strange,
            "participants": participants,
        },
    )
    resident_map = {
        row["slug"]: int(row["id"])
        for row in connection.execute("SELECT id,slug FROM residents")
    }
    if len(participants) == 2:
        a, b = sorted((resident_map[participants[0]], resident_map[participants[1]]))
        affinity = 2 if event.category in {"social", "civic", "strange"} else 1
        tension = 2 if event.slug in {"cafe-mixup", "quiet-hour", "time-slip"} else 0
        connection.execute(
            """
            UPDATE relationships SET affinity=MIN(100,affinity+?),
              trust=MIN(100,trust+1), tension=MIN(100,tension+?),
              familiarity=MIN(100,familiarity+3), interactions=interactions+1,
              last_interaction_tick=?
            WHERE season_id=? AND resident_a=? AND resident_b=?
            """,
            (affinity, tension, day * TICKS_PER_DAY, season["id"], a, b),
        )
    return event


def start_season(
    connection: sqlite3.Connection,
    *,
    opening_slug: str | None = None,
    seed_hex: str | None = None,
) -> dict[str, Any]:
    with transaction(connection, immediate=True):
        latest = _season_row(connection)
        if latest and latest["status"] in {"running", "paused", "closing"}:
            raise RuntimeError("a season is already active")
        number = int(latest["number"]) + 1 if latest else 1
        if opening_slug is None and latest:
            opening_slug = latest["next_catalyst_slug"]
        prior_season_id = int(latest["id"]) if latest else None
        seed_hex = seed_hex or secrets.token_hex(32)
        if len(seed_hex) != 64 or any(char not in "0123456789abcdefABCDEF" for char in seed_hex):
            raise ValueError("seed must be exactly 256 bits encoded as hexadecimal")
        seed_hex = seed_hex.lower()
        commitment = hashlib.sha256(bytes.fromhex(seed_hex)).hexdigest()
        bootstrap_population(connection, seed_hex)
        now = now_iso()
        cursor = connection.execute(
            """
            INSERT INTO seasons(
              number,status,created_at,started_at,seed_hex,seed_commitment,
              target_ticks,model_locked,weather_json
            ) VALUES(?,'running',?,?,?,?,?,0,?)
            """,
            (number, now, now, seed_hex, commitment, TARGET_TICKS, dumps(_weather(seed_hex, 0, number))),
        )
        season_id = int(cursor.lastrowid)
        initialize_resident_state(connection, season_id, prior_season_id)
        initialize_v2_season_state(connection, season_id, prior_season_id, seed_hex)
        seed_commerce(connection)
        season = connection.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
        event = _day_event(connection, season, 0, opening_slug)
        for resident in connection.execute(
            """
            SELECT r.id,r.name,r.role FROM residents r
            JOIN resident_lifecycle l ON l.resident_id=r.id
            WHERE l.alive=1 ORDER BY r.id
            """
        ):
            connection.execute(
                "INSERT INTO goals(season_id,resident_id,scope,description,created_tick) VALUES(?,?,?,?,0)",
                (
                    season_id,
                    resident["id"],
                    "seasonal",
                    f"Make meaningful progress as {resident['role']} while strengthening one town relationship.",
                ),
            )
            connection.execute(
                "INSERT INTO goals(season_id,resident_id,scope,description,created_tick) VALUES(?,?,?,?,0)",
                (
                    season_id,
                    resident["id"],
                    "daily",
                    f"Make one useful contribution while {event.title.lower()} shapes the town.",
                ),
            )
        _queue_job(
            connection,
            season_id,
            0,
            0,
            "season_opener",
            0,
            {
                "season": number,
                "event": event.title,
                "residents": int(connection.execute(
                    "SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1"
                ).fetchone()[0]),
            },
        )
        emit(
            connection,
            season_id,
            0,
            "season",
            {"status": "running", "number": number, "seedCommitment": commitment},
        )
    return {"seasonId": season_id, "number": number, "seedCommitment": commitment}


def _set_destination(
    connection: sqlite3.Connection,
    season_id: int,
    resident_id: int,
    current_x: float,
    current_y: float,
    location: str,
) -> None:
    dest_x, dest_y = LOCATION_POINTS[location]
    start_node = min(
        PATH_NODES,
        key=lambda node: math.hypot(
            PATH_NODES[node][0] - current_x,
            PATH_NODES[node][1] - current_y,
        ),
    )
    end_node = LOCATION_ACCESS[location]
    neighbours: dict[str, list[str]] = defaultdict(list)
    for left, right in PATH_EDGES:
        neighbours[left].append(right)
        neighbours[right].append(left)
    frontier: list[tuple[float, float, str, tuple[str, ...]]] = [
        (0.0, 0.0, start_node, ())
    ]
    visited: set[str] = set()
    route: tuple[str, ...] = (start_node, end_node)
    while frontier:
        _, cost, node, prior = heapq.heappop(frontier)
        if node in visited:
            continue
        visited.add(node)
        current_route = prior + (node,)
        if node == end_node:
            route = current_route
            break
        x, y = PATH_NODES[node]
        for neighbour in neighbours[node]:
            if neighbour in visited:
                continue
            nx, ny = PATH_NODES[neighbour]
            step = math.hypot(nx - x, ny - y)
            heuristic = math.hypot(
                PATH_NODES[end_node][0] - nx,
                PATH_NODES[end_node][1] - ny,
            )
            heapq.heappush(
                frontier,
                (cost + step + heuristic, cost + step, neighbour, current_route),
            )
    path = [[*PATH_NODES[node]] for node in route if node != start_node]
    if not path or path[-1] != [dest_x, dest_y]:
        path.append([dest_x, dest_y])
    connection.execute(
        """
        UPDATE resident_state SET destination_x=?,destination_y=?,location=?,path_json=?
        WHERE season_id=? AND resident_id=?
        """,
        (dest_x, dest_y, location, dumps(path), season_id, resident_id),
    )


def _action_for(
    row: sqlite3.Row,
    hour: float,
    event: sqlite3.Row | None,
    weather: dict[str, Any],
    memory_pull: float,
    nearby_residents: int,
) -> tuple[str, str]:
    needs = loads(row["needs_json"], {})
    participants = loads(event["participants_json"], []) if event else []
    traits = loads(row["traits_json"], {})
    energy = float(needs.get("energy", 70))
    hunger = float(needs.get("hunger", 25))
    social = float(needs.get("social", 45))
    purpose = float(needs.get("purpose", 55))
    meal_window = 6.5 <= hour < 8 or 12 <= hour < 13.5 or 18 <= hour < 19.5
    work_window = 8.5 <= hour < 12 or 13 <= hour < 17.5
    sleep_window = hour >= 22 or hour < 6
    evening = 17 <= hour < 22
    harsh_weather = weather.get("condition") in {"rain", "storm", "fog", "snow", "first-snow"}
    options: list[tuple[float, str, str]] = [
        (
            (100 - energy) * 1.25 + (95 if sleep_window else 0),
            "sleeping",
            str(row["home"]),
        ),
        (
            hunger * 1.35 + (52 if meal_window else 0) + social * 0.12,
            "sharing a meal",
            "Hobbs Cafe" if social > 48 else str(row["home"]),
        ),
        (
            (100 - purpose) * 0.8
            + (74 if work_window else 0)
            + float(traits.get("conscientiousness", 50)) * 0.2,
            f"working as {row['role']}",
            str(row["workplace"]),
        ),
        (
            social * 0.9
            + (35 if evening else 0)
            + float(traits.get("sociability", 50)) * 0.25
            - nearby_residents * 3,
            "spending time with neighbours",
            "Town Square",
        ),
        (
            (100 - purpose) * 0.75
            + float(traits.get("openness", 50)) * 0.24
            + memory_pull,
            "making progress on a personal project",
            str(row["workplace"]),
        ),
        (
            28
            + float(traits.get("openness", 50)) * 0.24
            + (18 if 7 <= hour < 21 else -20)
            - (30 if harsh_weather else 0),
            "taking an unhurried walk around the Lagoon",
            "Town Square",
        ),
    ]
    if event and row["slug"] in participants:
        options.append(
            (
                72
                + (38 if 14 <= hour < 18 else 0)
                + float(traits.get("agreeableness", 50)) * 0.2
                + memory_pull,
                f"responding to {event['title'].lower()}",
                "Town Square",
            )
        )
    _, activity, location = max(options, key=lambda option: option[0])
    return activity, location


def _thought_for(row: sqlite3.Row, activity: str, event: sqlite3.Row | None) -> tuple[str, str, str]:
    traits = loads(row["traits_json"], {})
    event_title = str(event["title"]) if event else "the changing day"
    if "responding" in activity:
        intention = f"Understand what {event_title.lower()} means for the neighbours involved."
        thought = f"This is unusual, but there is probably something useful I can do."
    elif "working" in activity:
        intention = f"Finish one useful piece of work before the afternoon changes course."
        thought = "Small, careful progress will make the rest of the day easier."
    elif "neighbours" in activity:
        intention = "Listen closely and leave the conversation better than it started."
        thought = "Someone in the square may know more about today's story."
    elif "sleeping" in activity:
        intention = "Rest until morning."
        thought = "The Lagoon can carry the story for a few quiet hours."
    else:
        intention = f"Stay open to {event_title.lower()} without abandoning the day's routine."
        thought = "The next useful idea may arrive while moving through town."
    mood = "curious" if int(traits.get("openness", 50)) > 75 else "steady"
    return thought, intention, mood


def _update_needs(needs: dict[str, float], activity: str) -> dict[str, float]:
    result = {key: float(value) for key, value in needs.items()}
    result["hunger"] = min(100, result.get("hunger", 20) + 0.35)
    result["energy"] = max(0, result.get("energy", 80) - 0.22)
    result["social"] = min(100, result.get("social", 50) + 0.25)
    result["purpose"] = max(0, result.get("purpose", 60) - 0.15)
    result["comfort"] = max(0, result.get("comfort", 70) - 0.08)
    if "sleeping" in activity:
        result["energy"] = min(100, result["energy"] + 1.1)
    if "meal" in activity:
        result["hunger"] = max(0, result["hunger"] - 2.5)
        result["comfort"] = min(100, result["comfort"] + 0.35)
    if "working" in activity or "project" in activity:
        result["purpose"] = min(100, result["purpose"] + 0.6)
    if "neighbours" in activity:
        result["social"] = max(0, result["social"] - 0.8)
    return {key: round(max(0, min(100, value)), 1) for key, value in result.items()}


def _move_resident(connection: sqlite3.Connection, season_id: int, row: sqlite3.Row) -> tuple[float, float]:
    path = loads(row["path_json"], [])
    if not path:
        return float(row["x"]), float(row["y"])
    target_x, target_y = map(float, path[0])
    x, y = float(row["x"]), float(row["y"])
    distance = math.hypot(target_x - x, target_y - y)
    speed = 38
    if distance <= speed:
        x, y = target_x, target_y
        path.pop(0)
    elif distance:
        x += (target_x - x) / distance * speed
        y += (target_y - y) / distance * speed
    connection.execute(
        "UPDATE resident_state SET x=?,y=?,path_json=? WHERE season_id=? AND resident_id=?",
        (round(x, 2), round(y, 2), dumps(path), season_id, row["id"]),
    )
    return x, y


def _v2_action_plan(row: sqlite3.Row, action: str, hour: float) -> tuple[str, str, int]:
    stage = str(row["life_stage"] or "adult")
    home = str(row["home"])
    workplace = str(row["workplace"])
    # The decision engine uses one tick to ponder and one to commit at wake-up.
    sleep_ticks = max(1, round(((5.75 - hour) if hour < 5.75 else (29.75 - hour)) * 12) - 2)
    if stage == "baby":
        if action == "restore_energy" or hour >= 20 or hour < 5.75:
            return "sleeping in the nursery", home, sleep_ticks if hour >= 20 or hour < 5.75 else 24
        if action == "eat_meal":
            return "having a bottle with a caregiver", home, 8
        return "playing safely with a caregiver", home, 12
    if hour >= 22 or hour < 5.75:
        return "sleeping safely at home", home, sleep_ticks
    if hour < 6.5:
        return (
            "getting breakfast before the day begins",
            "Hobbs Cafe" if int(row["id"]) % 2 else home,
            12,
        )
    if stage in {"child", "teen"} and 8 <= hour < 15:
        return "learning at school", "Oak Hill College", 18
    plans = {
        "restore_energy": ("sleeping", home, 48),
        "eat_meal": ("sharing a meal", "Hobbs Cafe" if stage in ADULT_STAGES else home, 12),
        "wash_up": ("washing up", home, 8),
        "seek_healthcare": ("visiting the clinic", "Lagoon Clinic", 18),
        "get_comfortable": ("relaxing at home", home, 18),
        "seek_safety": ("sheltering at home", home, 18),
        "have_fun": ("enjoying a favourite hobby", "Town Square", 18),
        "socialize": ("spending time with neighbours", "Town Square", 18),
        "join_community": ("joining community life", "Town Square", 24),
        "get_privacy": ("taking private time", home, 18),
        "pursue_purpose": ("making progress on a personal project", workplace, 24),
        "reclaim_autonomy": ("exploring the Lagoon", "Town Square", 18),
        "improve_finances": (f"working as {row['role']}", workplace, 36),
        "secure_childcare": ("arranging childcare", home, 18),
    }
    return plans.get(action, ("following a familiar routine", home, 18))


def _sync_needs(
    connection: sqlite3.Connection,
    season_id: int,
    resident_id: int,
    tick: int,
    before: dict[str, float],
    after: dict[str, float],
) -> None:
    connection.executemany(
        """
        INSERT INTO resident_needs(
          season_id,resident_id,need_key,satisfaction,trend,updated_tick
        ) VALUES(?,?,?,?,?,?)
        ON CONFLICT(season_id,resident_id,need_key) DO UPDATE SET
          satisfaction=excluded.satisfaction,trend=excluded.trend,updated_tick=excluded.updated_tick
        """,
        [
            (
                season_id,
                resident_id,
                name,
                int(round(after[name])),
                int(round(max(-100, min(100, after[name] - before.get(name, after[name]))))),
                tick,
            )
            for name in after
        ],
    )


def _care_links(
    connection: sqlite3.Connection,
    season_id: int,
    hour: float,
) -> tuple[dict[int, list[dict[str, Any]]], dict[int, dict[str, Any]]]:
    by_caregiver: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_child: dict[int, dict[str, Any]] = {}
    for child in connection.execute(
        """
        SELECT r.id,r.name,r.home,l.current_stage,v.household_id,c.id arrangement_id,
          c.caregiver_resident_id,c.provider_business_id
        FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
        JOIN resident_season_state v ON v.resident_id=r.id AND v.season_id=?
        LEFT JOIN childcare_arrangements c ON c.child_resident_id=r.id AND c.status='active'
        WHERE l.current_stage IN ('baby','child') ORDER BY r.id,c.id
        """,
        (season_id,),
    ):
        stage = str(child["current_stage"])
        if stage == "child" and child["provider_business_id"] and 8 <= hour < 15:
            provider = connection.execute(
                """
                SELECT b.name,COALESCE(p.map_location,p.name,'Krabville School') location
                FROM businesses b LEFT JOIN properties p ON p.id=b.property_id WHERE b.id=?
                """,
                (child["provider_business_id"],),
            ).fetchone()
            connection.execute(
                """
                UPDATE resident_season_state SET care_state='institutional',
                  current_caregiver_id=NULL,current_care_provider_id=?
                WHERE season_id=? AND resident_id=?
                """,
                (child["provider_business_id"], season_id, child["id"]),
            )
            if provider:
                by_child[int(child["id"])] = {
                    "childId": int(child["id"]), "childName": str(child["name"]),
                    "stage": stage, "home": str(child["home"]),
                    "location": str(provider["location"]), "caregiverName": str(provider["name"]),
                    "institutional": True,
                }
            continue
        caregiver = None
        if child["caregiver_resident_id"]:
            caregiver = connection.execute(
                """
                SELECT r.id,r.name FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
                WHERE r.id=? AND l.alive=1 AND l.current_stage IN ('adult','senior')
                """,
                (child["caregiver_resident_id"],),
            ).fetchone()
        if not caregiver:
            caregiver = connection.execute(
                """
                SELECT r.id,r.name FROM household_members hm JOIN residents r ON r.id=hm.resident_id
                JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
                LEFT JOIN employment e ON e.resident_id=r.id AND e.status IN ('active','leave')
                WHERE hm.household_id=? AND hm.ended_season_id IS NULL
                  AND l.current_stage IN ('adult','senior')
                ORDER BY CASE e.status WHEN 'leave' THEN 0 WHEN 'active' THEN 1 ELSE 2 END,r.id LIMIT 1
                """,
                (child["household_id"],),
            ).fetchone()
        if not caregiver:
            connection.execute(
                """
                UPDATE resident_season_state SET care_state='uncovered',
                  current_caregiver_id=NULL,current_care_provider_id=NULL
                WHERE season_id=? AND resident_id=?
                """,
                (season_id, child["id"]),
            )
            continue
        if stage == "baby":
            connection.execute(
                "UPDATE employment SET status='leave' WHERE resident_id=? AND status='active'",
                (caregiver["id"],),
            )
        link = {
            "childId": int(child["id"]), "childName": str(child["name"]),
            "stage": stage, "home": str(child["home"]),
            "location": str(child["home"]), "institutional": False,
            "caregiverId": int(caregiver["id"]), "caregiverName": str(caregiver["name"]),
        }
        by_child[int(child["id"])] = link
        by_caregiver[int(caregiver["id"])].append(link)
        connection.execute(
            """
            UPDATE resident_season_state SET care_state='covered',
              current_caregiver_id=?,current_care_provider_id=NULL
            WHERE season_id=? AND resident_id=?
            """,
            (caregiver["id"], season_id, child["id"]),
        )
    return by_caregiver, by_child


def _care_activity(link: dict[str, Any], needs: dict[str, float], *, caregiver: bool) -> str:
    name = str(link["childName"])
    if link.get("institutional"):
        provider = str(link["caregiverName"])
        if needs.get("hunger", 100) < 65:
            return f"having lunch at {provider}"
        if needs.get("hygiene", 100) < 55:
            return f"getting cleaned up at {provider}"
        if needs.get("social", 100) < 45:
            return f"socializing with classmates at {provider}"
        if needs.get("purpose", 100) < 45:
            return f"studying at {provider}"
        return f"learning and playing at {provider}"
    if needs.get("hunger", 100) < 65:
        return f"feeding {name} a bottle" if caregiver else f"having a bottle with {link['caregiverName']}"
    if needs.get("hygiene", 100) < 55:
        return f"changing and washing {name}" if caregiver else f"being changed and washed by {link['caregiverName']}"
    if not caregiver and needs.get("social", 100) < 45:
        return f"socializing safely with {link['caregiverName']}"
    return f"caring for {name} at home" if caregiver else f"playing safely with {link['caregiverName']}"


def _caregiver_activity(
    link: dict[str, Any],
    child_needs: dict[str, float],
    caregiver_needs: dict[str, float],
) -> str:
    if child_needs.get("hunger", 100) < 30 or child_needs.get("hygiene", 100) < 25:
        return _care_activity(link, child_needs, caregiver=True)
    name = str(link["childName"])
    options = (
        ("hunger", 45, f"sharing a meal at home while {name} stays close"),
        ("hygiene", 40, f"washing up while keeping {name} close by"),
        ("energy", 35, f"napping beside {name}"),
        ("privacy", 30, f"taking private time while keeping {name} close by"),
        ("fun", 30, f"enjoying a favourite hobby beside {name}"),
        ("social", 30, f"talking with a friend while keeping {name} close by"),
        ("autonomy", 25, f"making a personal choice while keeping {name} close by"),
    )
    urgent = [option for option in options if caregiver_needs.get(option[0], 100) < option[1]]
    if urgent:
        return min(urgent, key=lambda option: caregiver_needs.get(option[0], 100) / option[1])[2]
    return _care_activity(link, child_needs, caregiver=True)


def _place_inside(
    connection: sqlite3.Connection,
    season_id: int,
    resident_id: int,
    location: str,
) -> None:
    x, y = LOCATION_POINTS.get(location, LOCATION_POINTS["Town Square"])
    connection.execute(
        """
        UPDATE resident_state SET x=?,y=?,destination_x=?,destination_y=?,location=?,path_json='[]'
        WHERE season_id=? AND resident_id=?
        """,
        (x, y, x, y, location, season_id, resident_id),
    )


def _update_residents(connection: sqlite3.Connection, season: sqlite3.Row, tick: int) -> None:
    day_tick = tick % TICKS_PER_DAY
    hour = day_tick * 5 / 60
    event = connection.execute(
        "SELECT * FROM town_events WHERE season_id=? AND day=? ORDER BY id DESC LIMIT 1",
        (season["id"], tick // TICKS_PER_DAY),
    ).fetchone()
    rows = resident_rows(connection, season["id"])
    rows_by_id = {int(row["id"]): row for row in rows}
    care_by_caregiver, care_by_child = _care_links(connection, int(season["id"]), hour)
    location_counts: dict[str, int] = defaultdict(int)
    for resident in rows:
        location_counts[str(resident["location"])] += 1
    weather = loads(season["weather_json"], {})
    for row in rows:
        _move_resident(connection, season["id"], row)
        before = normalize_needs(loads(row["needs_json"], {}))
        needs_result = update_needs(
            {
                "needs": before,
                "elapsedMinutes": 5,
                "lifeStage": row["life_stage"],
                "activity": row["activity"],
                "weather": weather,
                "crowding": max(0, location_counts[str(row["location"])] - 1) * 8,
            }
        )
        needs = needs_result["needs"]
        mood = derive_mood({"needs": needs, "eventStress": 12 if event else 0})
        _sync_needs(connection, int(season["id"]), int(row["id"]), tick, before, needs)
        care_children = care_by_caregiver.get(int(row["id"]), [])
        receiving_care = care_by_child.get(int(row["id"]))
        urgent_care = False
        for item in care_children:
            child_needs = normalize_needs(loads(rows_by_id[item["childId"]]["needs_json"], {}))
            if child_needs.get("hunger", 100) < 30 or child_needs.get("hygiene", 100) < 25:
                urgent_care = True
                break
        if care_children and (5.75 <= hour < 22 or urgent_care):
            link = min(
                care_children,
                key=lambda item: min(normalize_needs(loads(rows_by_id[item["childId"]]["needs_json"], {})).values()),
            )
            child_needs = normalize_needs(loads(rows_by_id[link["childId"]]["needs_json"], {}))
            activity = _caregiver_activity(link, child_needs, needs)
            _place_inside(connection, int(season["id"]), int(row["id"]), str(link["home"]))
            if row["current_decision_id"]:
                connection.execute(
                    "UPDATE decision_history SET phase='interrupted',resolved_tick=?,interruption_reason='dependent care' WHERE id=? AND phase IN ('pondering','committed')",
                    (tick, row["current_decision_id"]),
                )
            connection.execute(
                """
                UPDATE resident_state SET activity=?,public_thought=?,intention=?,mood=?,needs_json=?,
                  action_until_tick=?,updated_tick=? WHERE season_id=? AND resident_id=?
                """,
                (activity, f"{link['childName']} needs me close by.", activity.capitalize(), mood["label"], dumps(needs), tick + 6, tick, season["id"], row["id"]),
            )
            connection.execute(
                """
                UPDATE resident_season_state SET decision_state='committed',current_decision_id=NULL,
                  mood_label=?,mood_valence=?,stress=?,health_score=?,updated_tick=?
                WHERE season_id=? AND resident_id=?
                """,
                (mood["label"], int(round(mood["valence"])), int(round(mood["stress"])), int(round(needs["health"])), tick, season["id"], row["id"]),
            )
            continue
        if receiving_care and (
            5.75 <= hour < 22 or needs.get("hunger", 100) < 30 or needs.get("hygiene", 100) < 25
        ):
            activity = _care_activity(receiving_care, needs, caregiver=False)
            if needs.get("hunger", 100) < 65:
                needs["hunger"] = min(100, needs["hunger"] + 3.5)
            if needs.get("hygiene", 100) < 55:
                needs["hygiene"] = min(100, needs["hygiene"] + 3.0)
            _sync_needs(connection, int(season["id"]), int(row["id"]), tick, before, needs)
            _place_inside(connection, int(season["id"]), int(row["id"]), str(receiving_care["location"]))
            connection.execute(
                """
                UPDATE resident_state SET activity=?,public_thought=?,intention=?,mood=?,needs_json=?,
                  action_until_tick=?,updated_tick=? WHERE season_id=? AND resident_id=?
                """,
                (activity, f"{receiving_care['caregiverName']} is looking after me.", activity.capitalize(), mood["label"], dumps(needs), tick + 6, tick, season["id"], row["id"]),
            )
            connection.execute(
                """
                UPDATE resident_season_state SET decision_state='committed',current_decision_id=NULL,
                  mood_label=?,mood_valence=?,stress=?,health_score=?,updated_tick=?
                WHERE season_id=? AND resident_id=?
                """,
                (mood["label"], int(round(mood["valence"])), int(round(mood["stress"])), int(round(needs["health"])), tick, season["id"], row["id"]),
            )
            continue
        changed = tick >= int(row["action_until_tick"])
        if changed:
            commitment = claim_due_commitment(
                connection, int(season["id"]), int(row["id"]), tick
            )
            if commitment:
                current_decision = int(row["current_decision_id"] or 0)
                if current_decision:
                    connection.execute(
                        """
                        UPDATE decision_history SET phase='interrupted',resolved_tick=?,
                          interruption_reason='phone commitment' WHERE id=?
                        """,
                        (tick, current_decision),
                    )
                activity = f"keeping a {commitment['type']} commitment"
                location = str(commitment["location"])
                _set_destination(
                    connection, int(season["id"]), int(row["id"]),
                    float(row["x"]), float(row["y"]), location,
                )
                connection.execute(
                    """
                    UPDATE resident_state SET activity=?,public_thought=?,intention=?,mood=?,
                      needs_json=?,action_until_tick=?,updated_tick=?
                    WHERE season_id=? AND resident_id=?
                    """,
                    (
                        activity, str(commitment["summary"]), activity.capitalize(), mood["label"],
                        dumps(needs), tick + 18, tick, season["id"], row["id"],
                    ),
                )
                connection.execute(
                    """
                    UPDATE resident_season_state SET decision_state='committed',current_decision_id=NULL,
                      mood_label=?,mood_valence=?,stress=?,health_score=?,updated_tick=?
                    WHERE season_id=? AND resident_id=?
                    """,
                    (
                        mood["label"], int(round(mood["valence"])), int(round(mood["stress"])),
                        int(round(needs["health"])), tick, season["id"], row["id"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO activities(season_id,tick,resident_id,kind,summary,location,source,created_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        season["id"], tick, row["id"], f"phone_{commitment['type']}", activity,
                        location, "phone-network", now_iso(),
                    ),
                )
                emit(connection, season["id"], tick, "communication", {
                    "resident": row["slug"], "activity": activity, "location": location,
                })
                continue
            current_decision = int(row["current_decision_id"] or 0)
            if row["decision_state"] == "pondering" and current_decision:
                decision = connection.execute(
                    "SELECT * FROM decision_history WHERE id=?", (current_decision,)
                ).fetchone()
                action = str(decision["chosen_action"])
                activity, location, duration = _v2_action_plan(row, action, hour)
                _set_destination(
                    connection, int(season["id"]), int(row["id"]),
                    float(row["x"]), float(row["y"]), location,
                )
                connection.execute(
                    """
                    UPDATE resident_state SET activity=?,public_thought=?,intention=?,mood=?,
                      needs_json=?,action_until_tick=?,updated_tick=?
                    WHERE season_id=? AND resident_id=?
                    """,
                    (
                        activity, decision["public_thought"], activity.capitalize(), mood["label"],
                        dumps(needs), tick + duration, tick, season["id"], row["id"],
                    ),
                )
                connection.execute(
                    "UPDATE decision_history SET phase='committed',committed_tick=? WHERE id=?",
                    (tick, current_decision),
                )
                connection.execute(
                    """
                    UPDATE resident_season_state SET decision_state='committed',mood_label=?,
                      mood_valence=?,stress=?,health_score=?,updated_tick=?
                    WHERE season_id=? AND resident_id=?
                    """,
                    (
                        mood["label"], int(round(mood["valence"])), int(round(mood["stress"])),
                        int(round(needs["health"])), tick, season["id"], row["id"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO activities(season_id,tick,resident_id,kind,summary,location,source,created_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (season["id"], tick, row["id"], action, activity, location, "utility-v2", now_iso()),
                )
                emit(connection, season["id"], tick, "activity", {
                    "resident": row["slug"], "activity": activity, "location": location,
                    "mood": mood["label"], "decisionId": current_decision,
                })
                progress = 4 if action in {"pursue_purpose", "improve_finances"} else 1
                connection.execute(
                    """
                    UPDATE goals SET progress=MIN(100,progress+?),
                      status=CASE WHEN progress+?>=100 THEN 'complete' ELSE status END,
                      completed_tick=CASE WHEN progress+?>=100 THEN ? ELSE completed_tick END
                    WHERE season_id=? AND resident_id=? AND status='active'
                    """,
                    (progress, progress, progress, tick, season["id"], row["id"]),
                )
            else:
                if current_decision:
                    connection.execute(
                        """
                        UPDATE decision_history SET phase='completed',resolved_tick=?,mood_after=?
                        WHERE id=? AND phase='committed'
                        """,
                        (tick, mood["label"], current_decision),
                    )
                wants = generate_short_term_wants({"needs": needs, "limit": 3})["wants"]
                finances = resident_finances(connection, int(row["id"]))
                decision_result = score_candidate_actions(
                    {
                        "needs": needs,
                        "wants": wants,
                        "hour": hour,
                        "weather": weather,
                        "nearbyResidents": max(0, location_counts[str(row["location"])] - 1),
                        "crowding": max(0, location_counts[str(row["location"])] - 1) * 8,
                        "finances": {"debt": finances["debtCents"]},
                        "lifeStage": row["life_stage"],
                        "event": {"salience": 65} if event else {},
                        "currentAction": row["activity"],
                    }
                )
                selected = decision_result["choices"][0]
                action = str(selected["action"])
                _, location, _ = _v2_action_plan(row, action, hour)
                thought = str(selected["thought"])
                decision_id = int(connection.execute(
                    """
                    INSERT INTO decision_history(
                      season_id,resident_id,tick,phase,chosen_action,chosen_destination,
                      public_thought,confidence,utility_score,mood_before,created_at
                    ) VALUES(?,?,?,'pondering',?,?,?,?,?,?,?) RETURNING id
                    """,
                    (
                        season["id"], row["id"], tick, action, location, thought,
                        float(selected["confidence"]) / 100.0, float(selected["score"]),
                        mood["label"], now_iso(),
                    ),
                ).fetchone()[0])
                for choice in decision_result["choices"]:
                    _, option_location, _ = _v2_action_plan(row, str(choice["action"]), hour)
                    connection.execute(
                        """
                        INSERT INTO decision_options(
                          decision_id,option_rank,action,destination,utility_score,selected
                        ) VALUES(?,?,?,?,?,?)
                        """,
                        (
                            decision_id, choice["rank"], choice["action"], option_location,
                            choice["score"], int(choice["rank"] == 1),
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO decision_factors(
                          decision_id,option_rank,factor_kind,factor_key,weight,explanation
                        ) VALUES(?,?,'need',?,?,?)
                        """,
                        (
                            decision_id, choice["rank"], choice["primaryNeed"],
                            100 - float(choice["needValue"]), "Current need satisfaction shaped this option.",
                        ),
                    )
                connection.execute(
                    "DELETE FROM resident_wants WHERE season_id=? AND resident_id=? AND kind='short_term'",
                    (season["id"], row["id"]),
                )
                connection.executemany(
                    """
                    INSERT INTO resident_wants(
                      season_id,resident_id,kind,description,status,priority,progress,created_tick
                    ) VALUES(?,?,'short_term',?,'active',?,0,?)
                    """,
                    [
                        (
                            season["id"], row["id"], want["label"],
                            int(round(max(0, min(100, want["priority"])))), tick,
                        )
                        for want in wants
                    ],
                )
                connection.execute(
                    """
                    UPDATE resident_state SET public_thought=?,mood=?,needs_json=?,
                      action_until_tick=?,updated_tick=? WHERE season_id=? AND resident_id=?
                    """,
                    (thought, mood["label"], dumps(needs), tick + 1, tick, season["id"], row["id"]),
                )
                connection.execute(
                    """
                    UPDATE resident_season_state SET decision_state='pondering',current_decision_id=?,
                      mood_label=?,mood_valence=?,stress=?,health_score=?,updated_tick=?
                    WHERE season_id=? AND resident_id=?
                    """,
                    (
                        decision_id, mood["label"], int(round(mood["valence"])),
                        int(round(mood["stress"])), int(round(needs["health"])), tick,
                        season["id"], row["id"],
                    ),
                )
                emit(connection, season["id"], tick, "decision", {
                    "resident": row["slug"], "phase": "pondering", "thought": thought,
                    "options": [choice["label"] for choice in decision_result["choices"]],
                })
        else:
            connection.execute(
                "UPDATE resident_state SET needs_json=?,mood=?,updated_tick=? WHERE season_id=? AND resident_id=?",
                (dumps(needs), mood["label"], tick, season["id"], row["id"]),
            )
            connection.execute(
                """
                UPDATE resident_season_state SET mood_label=?,mood_valence=?,stress=?,
                  health_score=?,updated_tick=? WHERE season_id=? AND resident_id=?
                """,
                (
                    mood["label"], int(round(mood["valence"])), int(round(mood["stress"])),
                    int(round(needs["health"])), tick, season["id"], row["id"],
                ),
            )


def _create_poll(connection: sqlite3.Connection, season: sqlite3.Row, day: int) -> None:
    if connection.execute(
        "SELECT 1 FROM polls WHERE season_id=? AND day=?", (season["id"], day)
    ).fetchone():
        return
    recent = {
        row[0]
        for row in connection.execute(
            "SELECT event_slug FROM poll_options ORDER BY id DESC LIMIT 15"
        )
    }
    rng = _rng(season["seed_hex"], "poll", day)
    categories = ["social", "civic", "environment", "economy", "relationship", "strange"]
    choices = []
    for category in categories:
        candidates = [
            event for event in MAJOR_EVENTS
            if event.category == category and event.slug not in recent
        ]
        choices.append(rng.choice(candidates or [event for event in MAJOR_EVENTS if event.category == category]))
    cursor = connection.execute(
        """
        INSERT INTO polls(season_id,day,opens_tick,closes_tick,status,created_at)
        VALUES(?,?,?,?,?,?)
        """,
        (
            season["id"],
            day,
            day * TICKS_PER_DAY + POLL_OPEN_TICK,
            day * TICKS_PER_DAY + POLL_CLOSE_TICK,
            "open",
            now_iso(),
        ),
    )
    poll_id = int(cursor.lastrowid)
    for index, choice in enumerate(choices):
        connection.execute(
            """
            INSERT INTO poll_options(poll_id,choice_id,event_slug,title,category,preview)
            VALUES(?,?,?,?,?,?)
            """,
            (poll_id, chr(ord("A") + index), choice.slug, choice.title, choice.category, choice.summary),
        )
    emit(
        connection,
        season["id"],
        day * TICKS_PER_DAY + POLL_OPEN_TICK,
        "poll",
        {"status": "open", "pollId": poll_id, "day": day},
    )


def _close_poll(connection: sqlite3.Connection, season: sqlite3.Row, day: int) -> None:
    poll = connection.execute(
        "SELECT * FROM polls WHERE season_id=? AND day=? AND status='open'",
        (season["id"], day),
    ).fetchone()
    if not poll:
        return
    options = list(
        connection.execute(
            "SELECT * FROM poll_options WHERE poll_id=? ORDER BY votes DESC,choice_id",
            (poll["id"],),
        )
    )
    top_votes = int(options[0]["votes"]) if options else 0
    tied = [option for option in options if int(option["votes"]) == top_votes]
    winner = _rng(season["seed_hex"], "poll-winner", day).choice(tied or options)
    connection.execute(
        "UPDATE polls SET status='closed',winner_option_id=? WHERE id=?",
        (winner["id"], poll["id"]),
    )
    connection.execute(
        "UPDATE seasons SET next_catalyst_slug=? WHERE id=?",
        (winner["event_slug"], season["id"]),
    )
    emit(
        connection,
        season["id"],
        day * TICKS_PER_DAY + POLL_CLOSE_TICK,
        "poll",
        {"status": "closed", "pollId": poll["id"], "winner": winner["choice_id"], "title": winner["title"]},
    )


def _schedule_daily_jobs(connection: sqlite3.Connection, season: sqlite3.Row, day: int, tick: int) -> None:
    day_tick = tick % TICKS_PER_DAY
    event = connection.execute(
        "SELECT title,summary FROM town_events WHERE season_id=? AND day=? ORDER BY id DESC LIMIT 1",
        (season["id"], day),
    ).fetchone()
    residents = []
    for row in resident_rows(connection, season["id"]):
        memories = retrieve_memories(
            connection,
            int(season["id"]),
            int(row["id"]),
            f"{row['role']} {row['activity']} {event['title'] if event else ''}",
            tags=("reflection", "town"),
            limit=3,
        )
        residents.append(
            {
                "slug": row["slug"],
                "name": row["name"],
                "role": row["role"],
                "routine": row["routine"],
                "intention": row["intention"],
                "memories": [memory["content"] for memory in memories],
            }
        )
    if day_tick == 72:
        for group in range(3):
            _queue_job(
                connection,
                season["id"],
                day,
                tick,
                "resident_intent",
                1,
                {"day": day, "group": group, "residents": residents[group * 4:(group + 1) * 4]},
            )
    if day_tick == 252:
        for group in range(3):
            _queue_job(
                connection,
                season["id"],
                day,
                tick,
                "resident_reflection",
                2,
                {"day": day, "group": group, "residents": residents[group * 4:(group + 1) * 4]},
            )
    if day_tick == 258:
        _queue_job(
            connection,
            season["id"],
            day,
            tick,
            "chronicle",
            1,
            {"day": day, "activities": _day_activity_count(connection, season["id"], day)},
        )
    if day_tick == 144:
        start = day * TICKS_PER_DAY
        activities = _day_activity_count(connection, int(season["id"]), day)
        conversations = int(connection.execute(
            "SELECT COUNT(*) FROM conversations WHERE season_id=? AND tick>=? AND tick<=?",
            (season["id"], start, tick),
        ).fetchone()[0])
        meaningful = int(connection.execute(
            "SELECT COUNT(*) FROM life_events WHERE season_id=? AND tick>=? AND tick<=?",
            (season["id"], start, tick),
        ).fetchone()[0])
        distinct = int(connection.execute(
            "SELECT COUNT(DISTINCT summary) FROM activities WHERE season_id=? AND tick>=? AND tick<=?",
            (season["id"], start, tick),
        ).fetchone()[0])
        boredom = boredom_score({
            "minutesSinceMeaningfulEvent": 720 if meaningful == 0 else 60,
            "routineRepetition": 1 - min(1, distinct / max(1, activities)),
            "meaningfulEvents": meaningful,
            "activityChanges": activities,
            "conversations": conversations,
            "conflicts": int(connection.execute(
                "SELECT COUNT(*) FROM life_events WHERE season_id=? AND tick>=? AND event_type IN ('argument','betrayal','breakup')",
                (season["id"], start),
            ).fetchone()[0]),
        })
        if boredom["shouldDirect"]:
            _queue_job(
                connection, int(season["id"]), day, tick, "daily_director", 0,
                {"day": day, "event": event["title"] if event else "quiet day", "weather": loads(season["weather_json"], {}), "boredom": boredom},
            )


def _day_activity_count(connection: sqlite3.Connection, season_id: int, day: int) -> int:
    start = day * TICKS_PER_DAY
    end = start + TICKS_PER_DAY
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM activities WHERE season_id=? AND tick>=? AND tick<?",
            (season_id, start, end),
        ).fetchone()[0]
    )


def _micro_event(connection: sqlite3.Connection, season: sqlite3.Row, day: int, tick: int) -> None:
    if connection.execute(
        "SELECT 1 FROM activities WHERE season_id=? AND tick=? AND kind='micro_event'",
        (season["id"], tick),
    ).fetchone():
        return
    event = _rng(season["seed_hex"], "micro", day).choice(MICRO_EVENTS)
    place = _rng(season["seed_hex"], "micro-place", day).choice(list(LOCATION_POINTS))
    summary = event.summary.format(place=place)
    connection.execute(
        """
        INSERT INTO activities(season_id,tick,kind,summary,location,source,created_at)
        VALUES(?,?,?,?,?,?,?)
        """,
        (season["id"], tick, "micro_event", summary, place, "local", now_iso()),
    )
    emit(
        connection,
        season["id"],
        tick,
        "micro_event",
        {"title": event.title, "category": event.category, "summary": summary, "location": place},
    )


def _dramatic_life_event(connection: sqlite3.Connection, season: sqlite3.Row, day: int, tick: int) -> None:
    if connection.execute(
        "SELECT 1 FROM life_events WHERE season_id=? AND tick=?", (season["id"], tick)
    ).fetchone():
        return
    residents = list(connection.execute(
        """
        SELECT r.id,r.slug,r.name,l.current_stage FROM residents r
        JOIN resident_lifecycle l ON l.resident_id=r.id
        WHERE l.alive=1 ORDER BY r.id
        """
    ))
    adults = [row for row in residents if row["current_stage"] in {"adult", "senior"}]
    if not adults:
        return
    rng = _rng(str(season["seed_hex"]), "drama", day)
    subject = rng.choice(adults)
    others = [row for row in adults if row["id"] != subject["id"]]
    related = rng.choice(others) if others else None
    event_type = rng.choice((
        "argument", "romance", "gossip", "financial_trouble", "career_change",
        "illness", "betrayal", "reconciliation", "accident", "friendship",
    ))
    templates = {
        "argument": ("An argument spills into the open", f"{subject['name']} and {related['name'] if related else 'a neighbour'} clash over a promise that was not kept.", 66, -6, -2, 14),
        "romance": ("A new spark becomes obvious", f"{subject['name']} shares an unexpectedly tender moment with {related['name'] if related else 'someone new'}.", 62, 10, 7, -3),
        "gossip": ("A private detail starts travelling", f"A half-true story about {subject['name']} reaches the market before the facts do.", 58, -3, -6, 9),
        "financial_trouble": ("Money trouble reaches home", f"{subject['name']} discovers that this month's numbers no longer add up.", 72, -2, -3, 7),
        "career_change": ("A difficult offer arrives", f"{subject['name']} receives an opportunity that could improve work and disrupt home life.", 55, 2, 1, 2),
        "illness": ("A health scare changes the day", f"{subject['name']} has to slow down and accept help from the community.", 70, 4, 5, -2),
        "betrayal": ("Trust is broken", f"{subject['name']} learns that {related['name'] if related else 'a trusted neighbour'} kept back something important.", 82, -12, -16, 20),
        "reconciliation": ("An old feud softens", f"{subject['name']} and {related['name'] if related else 'an old friend'} finally speak honestly about what happened.", 68, 12, 14, -12),
        "accident": ("A non-serious accident rattles the town", f"{subject['name']} is shaken but safe after a mishap near the docks.", 64, 3, 4, 1),
        "friendship": ("A friendship deepens", f"{subject['name']} shows up when {related['name'] if related else 'a neighbour'} genuinely needs support.", 60, 10, 10, -4),
    }
    title, summary, severity, affinity, trust, tension = templates[event_type]
    life_event_id = int(connection.execute(
        """
        INSERT INTO life_events(
          season_id,tick,event_type,subject_resident_id,related_resident_id,title,
          summary,outcome,severity,permanent,created_at
        ) VALUES(?,?,?,?,?,?,?, '',?,0,?) RETURNING id
        """,
        (season["id"], tick, event_type, subject["id"], related["id"] if related else None, title, summary, severity, now_iso()),
    ).fetchone()[0])
    for participant in [subject, related]:
        if participant:
            connection.execute(
                "INSERT INTO life_event_participants(life_event_id,resident_id,role) VALUES(?,?,'participant')",
                (life_event_id, participant["id"]),
            )
            connection.execute(
                """
                INSERT INTO memories(
                  season_id,resident_id,kind,content,tags,valence,salience,
                  participants_json,location,created_tick,durable
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    season["id"], participant["id"], "life_event", summary,
                    f"{event_type} drama", -1 if tension > 5 else 1, min(10, severity // 10),
                    dumps([item["slug"] for item in [subject, related] if item]), "Town Square", tick, int(severity >= 70),
                ),
            )
    if related:
        low, high = sorted((int(subject["id"]), int(related["id"])))
        connection.execute(
            """
            UPDATE relationships SET affinity=MAX(-100,MIN(100,affinity+?)),
              trust=MAX(-100,MIN(100,trust+?)),tension=MAX(0,MIN(100,tension+?)),
              affection=MAX(-100,MIN(100,affection+?)),
              attraction=MAX(-100,MIN(100,attraction+?)),
              resentment=MAX(0,MIN(100,resentment+?)),
              familiarity=MIN(100,familiarity+4),interactions=interactions+1,last_interaction_tick=?
            WHERE season_id=? AND resident_a=? AND resident_b=?
            """,
            (
                affinity, trust, tension, affinity, 5 if event_type == "romance" else 0,
                max(0, tension // 2), tick, season["id"], low, high,
            ),
        )
    fact_id = int(connection.execute(
        """
        INSERT INTO facts(season_id,canonical_key,category,statement,truth_value,occurred_tick,created_at)
        VALUES(?,?,?,?, 'true',?,?) RETURNING id
        """,
        (season["id"], f"drama:{day}:{event_type}", event_type, summary, tick, now_iso()),
    ).fetchone()[0])
    if event_type in {"gossip", "romance", "betrayal", "financial_trouble"}:
        connection.execute(
            """
            INSERT INTO secrets(fact_id,owner_resident_id,sensitivity,status,created_tick)
            VALUES(?,?,?,'partially_revealed',?)
            """,
            (fact_id, subject["id"], min(95, severity), tick),
        )
        connection.execute(
            """
            INSERT INTO resident_beliefs(
              resident_id,fact_id,stance,confidence,acquired_season_id,acquired_tick,updated_tick,private
            ) VALUES(?,?,'knows',100,?,?,?,1)
            """,
            (subject["id"], fact_id, season["id"], tick, tick),
        )
        if related:
            connection.execute(
                """
                INSERT INTO resident_beliefs(
                  resident_id,fact_id,stance,confidence,source_resident_id,
                  acquired_season_id,acquired_tick,updated_tick,private
                ) VALUES(?,?,'suspects',55,?,?,?,?,1)
                """,
                (related["id"], fact_id, subject["id"], season["id"], tick, tick),
            )
    connection.execute(
        """
        INSERT INTO story_ledger(
          season_id,tick,day,entry_type,headline,summary,significance,visibility,life_event_id,created_at
        ) VALUES(?,?,?,?,?,?,?,'omniscient',?,?)
        """,
        (season["id"], tick, day, event_type, title, summary, severity, life_event_id, now_iso()),
    )
    emit(connection, season["id"], tick, "life_event", {
        "type": event_type, "title": title, "summary": summary,
        "residents": [item["slug"] for item in [subject, related] if item], "severity": severity,
    })


def _local_chronicle(connection: sqlite3.Connection, season: sqlite3.Row, day: int) -> None:
    if connection.execute(
        "SELECT 1 FROM daily_chronicles WHERE season_id=? AND day=?", (season["id"], day)
    ).fetchone():
        return
    event = connection.execute(
        "SELECT * FROM town_events WHERE season_id=? AND day=? ORDER BY id DESC LIMIT 1",
        (season["id"], day),
    ).fetchone()
    activity_count = _day_activity_count(connection, season["id"], day)
    conversation_count = int(
        connection.execute(
            "SELECT COUNT(*) FROM conversations WHERE season_id=? AND tick>=? AND tick<?",
            (season["id"], day * TICKS_PER_DAY, (day + 1) * TICKS_PER_DAY),
        ).fetchone()[0]
    )
    weather = loads(season["weather_json"], {})
    title = f"Day {day + 1}: {event['title'] if event else 'A quiet Lagoon day'}"
    narrative = (
        f"Krabville woke to {weather.get('condition', 'calm')} weather. "
        f"{event['summary'] if event else 'Residents followed their routines around the Lagoon.'} "
        f"The town recorded {activity_count} meaningful activity changes and "
        f"{conversation_count} conversations before nightfall."
    )
    connection.execute(
        """
        INSERT INTO daily_chronicles(season_id,day,title,narrative,statistics_json,created_at)
        VALUES(?,?,?,?,?,?)
        """,
        (
            season["id"],
            day,
            title,
            narrative,
            dumps({"activities": activity_count, "conversations": conversation_count}),
            now_iso(),
        ),
    )
    connection.execute(
        """
        UPDATE goals SET status=CASE WHEN progress>=10 THEN 'complete' ELSE 'deferred' END,
          completed_tick=CASE WHEN progress>=10 THEN ? ELSE completed_tick END
        WHERE season_id=? AND scope='daily' AND created_tick>=? AND created_tick<?
          AND status='active'
        """,
        (
            (day + 1) * TICKS_PER_DAY - 1,
            season["id"],
            day * TICKS_PER_DAY,
            (day + 1) * TICKS_PER_DAY,
        ),
    )
    emit(connection, season["id"], (day + 1) * TICKS_PER_DAY - 1, "chronicle", {"day": day, "title": title})


def _new_day(connection: sqlite3.Connection, season: sqlite3.Row, day: int) -> None:
    catalyst = str(season["next_catalyst_slug"] or "") or None
    weather = _weather(season["seed_hex"], day, int(season["number"]))
    connection.execute(
        "UPDATE seasons SET current_day=?,world_minutes=0,next_catalyst_slug=NULL,weather_json=? WHERE id=?",
        (day, dumps(weather), season["id"]),
    )
    refreshed = connection.execute("SELECT * FROM seasons WHERE id=?", (season["id"],)).fetchone()
    event = _day_event(connection, refreshed, day, catalyst)
    for resident in connection.execute(
        """
        SELECT r.id FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        WHERE l.alive=1 ORDER BY r.id
        """
    ):
        connection.execute(
            """
            INSERT INTO goals(season_id,resident_id,scope,description,created_tick)
            VALUES(?,?,?,?,?)
            """,
            (
                season["id"],
                resident["id"],
                "daily",
                f"Make one useful contribution while {event.title.lower()} shapes the town.",
                day * TICKS_PER_DAY,
            ),
        )


def _complete_season(
    connection: sqlite3.Connection,
    season: sqlite3.Row,
    *,
    final_tick: int,
    reason: str,
) -> None:
    connection.execute(
        "UPDATE seasons SET status='closing',model_locked=1 WHERE id=?", (season["id"],)
    )
    connection.execute(
        """
        UPDATE model_jobs SET status='cancelled',error_code='season_complete',updated_at=?
        WHERE season_id=? AND status IN ('queued','leased')
        """,
        (now_iso(), season["id"]),
    )
    last_day = min(DAYS_PER_SEASON - 1, max(0, (max(1, final_tick) - 1) // TICKS_PER_DAY))
    for day in range(last_day + 1):
        _local_chronicle(connection, season, day)
    completed = now_iso()
    natural = final_tick >= TARGET_TICKS
    shown_tick = TARGET_TICKS if natural else max(0, final_tick)
    shown_day = DAYS_PER_SEASON - 1 if natural else min(DAYS_PER_SEASON - 1, shown_tick // TICKS_PER_DAY)
    shown_minutes = 1435 if natural else (shown_tick % TICKS_PER_DAY) * 5
    lifecycle = []
    growth: dict[str, Any] = {}
    if natural:
        lifecycle = apply_lifecycle_boundary(connection, int(season["id"]), shown_tick)
        growth = grow_population(
            connection,
            int(season["id"]),
            shown_tick,
            str(season["seed_hex"]),
        )
    connection.execute(
        """
        UPDATE seasons SET status='complete',completed_at=?,seed_revealed=1,
          current_tick=?,current_day=?,world_minutes=?,target_ticks=?,model_locked=1,
          completion_reason=?
        WHERE id=?
        """,
        (completed, shown_tick, shown_day, shown_minutes, shown_tick, reason, season["id"]),
    )
    connection.execute("DELETE FROM votes WHERE poll_id IN (SELECT id FROM polls WHERE season_id=?)", (season["id"],))
    emit(
        connection,
        season["id"],
        shown_tick,
        "season",
        {
            "status": "complete",
            "number": season["number"],
            "seed": season["seed_hex"],
            "reason": reason,
            "lifecycle": lifecycle,
            "births": growth.get("births", []),
            "arrivals": growth.get("arrivals", []),
            "population": {
                "living": growth.get("living"), "target": growth.get("target")
            },
            "guardianRepairs": growth.get("guardianRepairs", []),
        },
    )


def _save_snapshot(connection: sqlite3.Connection, season: sqlite3.Row, tick: int) -> None:
    residents = [
        {
            "slug": row["slug"],
            "x": float(row["x"]),
            "y": float(row["y"]),
            "location": row["location"],
            "activity": row["activity"],
            "mood": row["mood"],
            "needs": loads(row["needs_json"], {}),
        }
        for row in resident_rows(connection, int(season["id"]))
    ]
    connection.execute(
        """
        INSERT OR REPLACE INTO snapshots(season_id,tick,state_json,created_at)
        VALUES(?,?,?,?)
        """,
        (
            season["id"],
            tick,
            dumps({"weather": loads(season["weather_json"], {}), "residents": residents}),
            now_iso(),
        ),
    )


def advance_tick(connection: sqlite3.Connection) -> dict[str, Any]:
    with transaction(connection, immediate=True):
        season = _season_row(connection)
        if not season or season["status"] != "running":
            return {"advanced": False, "status": season["status"] if season else "draft"}
        tick = int(season["current_tick"])
        if tick >= TARGET_TICKS:
            _complete_season(connection, season, final_tick=TARGET_TICKS, reason="natural")
            return {"advanced": False, "status": "complete"}
        day = tick // TICKS_PER_DAY
        day_tick = tick % TICKS_PER_DAY
        _apply_completed_jobs(connection, season)
        _update_residents(connection, season, tick)
        _schedule_daily_jobs(connection, season, day, tick)
        if day_tick == 48:
            economy = settle_daily_economy(connection, int(season["id"]), day, tick)
            economy.update(run_daily_commerce(connection, int(season["id"]), day, tick))
            emit(connection, int(season["id"]), tick, "economy", economy)
        if day_tick in {108, 180, 240}:
            phone = run_phone_window(connection, season, tick)
            if phone["calls"]:
                emit(connection, int(season["id"]), tick, "communication", phone)
        if day_tick == POLL_OPEN_TICK:
            _create_poll(connection, season, day)
        if day_tick == POLL_CLOSE_TICK:
            _close_poll(connection, season, day)
        if day_tick == 180:
            _micro_event(connection, season, day, tick)
        if day_tick == 228:
            _dramatic_life_event(connection, season, day, tick)
        next_tick = tick + 1
        connection.execute(
            "UPDATE seasons SET current_tick=?,current_day=?,world_minutes=? WHERE id=?",
            (next_tick, day, day_tick * 5, season["id"]),
        )
        if next_tick % TICKS_PER_DAY == 0:
            _local_chronicle(connection, season, day)
            if day + 1 >= DAYS_PER_SEASON or (
                season["stop_after_day"] is not None and day + 1 >= int(season["stop_after_day"])
            ):
                refreshed = connection.execute("SELECT * FROM seasons WHERE id=?", (season["id"],)).fetchone()
                reason = "natural" if day + 1 >= DAYS_PER_SEASON else "operator_day_stop"
                _complete_season(connection, refreshed, final_tick=next_tick, reason=reason)
                return {"advanced": True, "status": "complete", "tick": next_tick}
            refreshed = connection.execute("SELECT * FROM seasons WHERE id=?", (season["id"],)).fetchone()
            _new_day(connection, refreshed, day + 1)
        if next_tick % 12 == 0:
            refreshed = connection.execute("SELECT * FROM seasons WHERE id=?", (season["id"],)).fetchone()
            _save_snapshot(connection, refreshed, next_tick)
            emit(
                connection,
                season["id"],
                next_tick,
                "tick",
                {"tick": next_tick, "day": next_tick // TICKS_PER_DAY, "worldMinutes": (next_tick % TICKS_PER_DAY) * 5},
            )
        return {"advanced": True, "status": "running", "tick": next_tick, "day": day}


def _apply_completed_jobs(connection: sqlite3.Connection, season: sqlite3.Row) -> None:
    jobs = list(
        connection.execute(
            """
            SELECT * FROM model_jobs WHERE season_id=? AND status='complete'
              AND result_json IS NOT NULL AND error_code IS NULL
            ORDER BY id LIMIT 20
            """,
            (season["id"],),
        )
    )
    resident_ids = {
        row["slug"]: int(row["id"])
        for row in connection.execute("SELECT id,slug FROM residents")
    }
    for job in jobs:
        result = loads(job["result_json"], {})
        kind = str(job["kind"])
        if kind in {"resident_intent", "resident_reflection"}:
            for item in result.get("items", []):
                resident_id = resident_ids.get(str(item.get("slug")))
                if not resident_id:
                    continue
                if kind == "resident_intent":
                    connection.execute(
                        """
                        UPDATE resident_state SET intention=?,public_thought=?
                        WHERE season_id=? AND resident_id=?
                        """,
                        (
                            str(item.get("intention", ""))[:240],
                            str(item.get("publicThought", ""))[:280],
                            season["id"],
                            resident_id,
                        ),
                    )
                else:
                    reflection = str(item.get("reflection", ""))[:360]
                    public_thought = str(item.get("publicThought", reflection))[:280]
                    connection.execute(
                        """
                        UPDATE resident_state SET reflection=?,public_thought=?
                        WHERE season_id=? AND resident_id=?
                        """,
                        (reflection, public_thought, season["id"], resident_id),
                    )
                    if reflection:
                        connection.execute(
                            """
                            INSERT INTO memories(
                              season_id,resident_id,kind,content,tags,valence,salience,
                              created_tick,durable
                            ) VALUES(?,?,?,?,?,?,?,?,?)
                            """,
                            (season["id"], resident_id, "reflection", reflection, "reflection town", 1, 6, job["tick"], 0),
                        )
        elif kind == "conversation":
            context = loads(job["context_json"], {})
            slugs = context.get("residents", [])
            if len(slugs) == 2 and all(slug in resident_ids for slug in slugs):
                a, b = resident_ids[slugs[0]], resident_ids[slugs[1]]
                dialogue = result.get("dialogue", [])[:8]
                summary = str(result.get("summary", "A brief conversation changed the tone of the day."))[:320]
                connection.execute(
                    """
                    INSERT INTO conversations(
                      season_id,tick,resident_a,resident_b,location,dialogue_json,summary,source
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (season["id"], job["tick"], a, b, context.get("location", "Town Square"), dumps(dialogue), summary, "model"),
                )
                low, high = sorted((a, b))
                connection.execute(
                    """
                    UPDATE relationships SET affinity=MIN(100,affinity+2),trust=MIN(100,trust+1),
                      familiarity=MIN(100,familiarity+2),interactions=interactions+1,
                      last_interaction_tick=?
                    WHERE season_id=? AND resident_a=? AND resident_b=?
                    """,
                    (job["tick"], season["id"], low, high),
                )
                emit(connection, season["id"], job["tick"], "conversation", {"residents": slugs, "summary": summary, "dialogue": dialogue})
        elif kind == "chronicle":
            day = int(job["day"])
            title = str(result.get("title", f"Day {day + 1}"))[:160]
            narrative = str(result.get("narrative", ""))[:1200]
            if narrative:
                connection.execute(
                    """
                    INSERT INTO daily_chronicles(season_id,day,title,narrative,statistics_json,created_at)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(season_id,day) DO UPDATE SET title=excluded.title,narrative=excluded.narrative
                    """,
                    (season["id"], day, title, narrative, dumps(result.get("statistics", {})), now_iso()),
                )
        connection.execute(
            "UPDATE model_jobs SET error_code='applied',updated_at=? WHERE id=?",
            (now_iso(), job["id"]),
        )


def queue_conversation_if_needed(connection: sqlite3.Connection) -> int:
    with transaction(connection, immediate=True):
        season = _season_row(connection)
        if not season or season["status"] != "running" or season["model_locked"]:
            return 0
        day = int(season["current_tick"]) // TICKS_PER_DAY
        count = int(
            connection.execute(
                "SELECT COUNT(*) FROM model_jobs WHERE season_id=? AND day=? AND kind='conversation'",
                (season["id"], day),
            ).fetchone()[0]
        )
        if count >= 4:
            return 0
        grouped: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for row in resident_rows(connection, season["id"]):
            if "sleeping" not in str(row["activity"]):
                grouped[str(row["location"])].append(row)
        candidates = [(location, rows) for location, rows in grouped.items() if len(rows) >= 2]
        if not candidates:
            return 0
        rng = _rng(season["seed_hex"], "conversation", season["current_tick"])
        location, rows = rng.choice(candidates)
        pair = rng.sample(rows, 2)
        context = {
            "location": location,
            "residents": [pair[0]["slug"], pair[1]["slug"]],
            "names": [pair[0]["name"], pair[1]["name"]],
            "activities": [pair[0]["activity"], pair[1]["activity"]],
        }
        return int(
            _queue_job(
                connection,
                season["id"],
                day,
                int(season["current_tick"]),
                "conversation",
                2,
                context,
            )
            or 0
        )


def pause(connection: sqlite3.Connection) -> None:
    with transaction(connection, immediate=True):
        season = _season_row(connection)
        if not season or season["status"] != "running":
            raise RuntimeError("no running season")
        connection.execute("UPDATE seasons SET status='paused' WHERE id=?", (season["id"],))
        emit(connection, season["id"], season["current_tick"], "season", {"status": "paused"})


def resume(connection: sqlite3.Connection) -> None:
    with transaction(connection, immediate=True):
        season = _season_row(connection)
        if not season or season["status"] != "paused":
            raise RuntimeError("no paused season")
        connection.execute("UPDATE seasons SET status='running' WHERE id=?", (season["id"],))
        emit(connection, season["id"], season["current_tick"], "season", {"status": "running"})


def stop_now(connection: sqlite3.Connection) -> None:
    with transaction(connection, immediate=True):
        season = _season_row(connection)
        if not season or season["status"] not in {"running", "paused"}:
            raise RuntimeError("no active season")
        _complete_season(
            connection,
            season,
            final_tick=int(season["current_tick"]),
            reason="operator_stop",
        )


def stop_after_day(connection: sqlite3.Connection) -> None:
    with transaction(connection, immediate=True):
        season = _season_row(connection)
        if not season or season["status"] not in {"running", "paused"}:
            raise RuntimeError("no active season")
        connection.execute(
            "UPDATE seasons SET stop_after_day=? WHERE id=?",
            (int(season["current_day"]) + 1, season["id"]),
        )


def diagnose(connection: sqlite3.Connection) -> dict[str, Any]:
    quick = str(connection.execute("PRAGMA quick_check").fetchone()[0])
    season = _season_row(connection)
    jobs = (
        {
            row["status"]: int(row["count"])
            for row in connection.execute(
                "SELECT status,COUNT(*) count FROM model_jobs WHERE season_id=? GROUP BY status",
                (season["id"],),
            )
        }
        if season
        else {}
    )
    season_status = (
        {
            "id": int(season["id"]),
            "number": int(season["number"]),
            "status": season["status"],
            "currentTick": int(season["current_tick"]),
            "currentDay": int(season["current_day"]),
            "worldMinutes": int(season["world_minutes"]),
            "targetTicks": int(season["target_ticks"]),
            "modelLocked": bool(season["model_locked"]),
            "modelDegraded": bool(season["model_degraded"]),
            "seedCommitment": season["seed_commitment"],
            "completionReason": season["completion_reason"],
        }
        if season
        else None
    )
    return {
        "ok": quick == "ok",
        "database": quick,
        "season": season_status,
        "jobs": jobs,
        "residents": int(
            connection.execute("SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1").fetchone()[0]
        ),
        "majorEvents": len(MAJOR_EVENTS),
        "microEvents": len(MICRO_EVENTS),
    }
