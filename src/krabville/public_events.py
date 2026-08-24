from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PUBLIC_EVENT_SCHEMA = "krabville.public-event"
PUBLIC_EVENT_VERSION = 1

# Includes currently emitted kinds and names retained for existing SSE clients.
PUBLIC_EVENT_KINDS = (
    "snapshot",
    "tick",
    "activity",
    "decision",
    "conversation",
    "communication",
    "relationship",
    "relationship_change",
    "town_event",
    "micro_event",
    "life_event",
    "economy",
    "purchase",
    "housing",
    "health",
    "care_handoff",
    "goal_change",
    "poll",
    "model_job",
    "budget",
    "chronicle",
    "verified_chronicle",
    "season",
    "runtime_incident",
)
PUBLIC_EVENT_KIND_SET = frozenset(PUBLIC_EVENT_KINDS)


class PublicEventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    eventVersion: Literal[1] = PUBLIC_EVENT_VERSION
    seq: int = Field(gt=0)
    seasonId: int | None = Field(default=None, gt=0)
    tick: int = Field(ge=0)
    type: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    payload: dict[str, Any]
    createdAt: str

    @field_validator("createdAt")
    @classmethod
    def created_at_is_utc(cls, value: str) -> str:
        try:
            timestamp = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("createdAt must be an ISO-8601 timestamp") from error
        if timestamp.utcoffset() != dt.timedelta(0):
            raise ValueError("createdAt must include a UTC offset")
        return value


def is_public_event_kind(value: object) -> bool:
    return isinstance(value, str) and value in PUBLIC_EVENT_KIND_SET


def serialize_public_event(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError) as error:
        raise ValueError("public event payload must be valid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("public event payload must be a JSON object")

    envelope = PublicEventEnvelope(
        seq=int(row["seq"]),
        seasonId=int(row["season_id"]) if row["season_id"] is not None else None,
        tick=int(row["tick"]),
        type=str(row["event_type"]),
        payload=payload,
        createdAt=str(row["created_at"]),
    )
    return envelope.model_dump()
