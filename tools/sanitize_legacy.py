from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def select(source: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: source[field] for field in fields if field in source}


def sanitize(payload: dict[str, Any]) -> dict[str, Any]:
    world = payload.get("world", {}) if isinstance(payload.get("world"), dict) else {}
    days = []
    for raw_day in world.get("days", [])[:7]:
        if not isinstance(raw_day, dict):
            continue
        event = raw_day.get("event", {}) if isinstance(raw_day.get("event"), dict) else {}
        days.append(
            {
                **select(raw_day, ("year", "day", "date", "weather", "narrative", "activity_changes", "conversations")),
                "event": select(
                    event,
                    ("year", "day", "date", "title", "summary", "participants", "relationship_change", "strange"),
                ),
            }
        )
    residents = [
        select(
            resident,
            ("name", "action", "mood", "thought", "role", "home", "workplace", "routine", "about"),
        )
        for resident in payload.get("residents", [])[:12]
        if isinstance(resident, dict)
    ]
    relationships_source = world.get("relationships", {})
    if isinstance(relationships_source, dict):
        relationship_values = relationships_source.values()
    elif isinstance(relationships_source, list):
        relationship_values = relationships_source
    else:
        relationship_values = []
    relationships = [
        select(value, ("a", "b", "score", "interactions", "label", "last_event"))
        for value in relationship_values
        if isinstance(value, dict)
    ]
    report = world.get("week_report", {}) if isinstance(world.get("week_report"), dict) else {}
    return {
        "schemaVersion": 1,
        "run": select(payload.get("run", {}), ("status", "day", "residents")),
        "residents": residents,
        "world": {
            "weather": world.get("weather", {}),
            "days": days,
            "relationships": relationships,
            "week_report": select(
                report,
                (
                    "status",
                    "title",
                    "days_completed",
                    "start_date",
                    "end_date",
                    "headline",
                    "narrative",
                    "strange_days",
                    "activity_changes",
                    "conversations",
                    "relationships",
                    "strongest_bond",
                    "events",
                    "weather_days",
                    "model",
                    "model_calls",
                    "model_calls_locked",
                ),
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    sanitized = sanitize(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sanitized, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
