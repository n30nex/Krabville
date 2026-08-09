from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from krabville.public_events import (
    PUBLIC_EVENT_KINDS,
    PUBLIC_EVENT_SCHEMA,
    PUBLIC_EVENT_VERSION,
    PublicEventEnvelope,
    is_public_event_kind,
    serialize_public_event,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "contracts"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_public_event_envelope_matches_golden_fixture() -> None:
    expected = _fixture("public-event-v1.json")
    row = {
        "seq": expected["seq"],
        "season_id": expected["seasonId"],
        "tick": expected["tick"],
        "event_type": expected["type"],
        "payload_json": json.dumps(expected["payload"]),
        "created_at": expected["createdAt"],
    }

    assert serialize_public_event(row) == expected
    assert PublicEventEnvelope.model_validate(expected).model_dump() == expected
    assert PublicEventEnvelope.model_json_schema()["additionalProperties"] is False


def test_public_event_registry_matches_golden_and_emitters() -> None:
    expected = _fixture("public-event-registry-v1.json")
    assert expected == {
        "schema": PUBLIC_EVENT_SCHEMA,
        "version": PUBLIC_EVENT_VERSION,
        "eventKinds": list(PUBLIC_EVENT_KINDS),
    }

    emitted: set[str] = set()
    for path in (ROOT / "src" / "krabville").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "emit"
                and len(node.args) >= 4
                and isinstance(node.args[3], ast.Constant)
                and isinstance(node.args[3].value, str)
            ):
                emitted.add(node.args[3].value)

    assert emitted <= set(PUBLIC_EVENT_KINDS)
    assert {"snapshot", "relationship", "budget"} <= set(PUBLIC_EVENT_KINDS)


def test_unknown_event_is_serializable_but_not_registered() -> None:
    event = _fixture("public-event-v1.json") | {"type": "future_event"}
    validated = PublicEventEnvelope.model_validate(event)

    assert validated.type == "future_event"
    assert not is_public_event_kind(validated.type)


def test_invalid_public_event_schema_is_rejected() -> None:
    event = _fixture("public-event-v1.json")
    with pytest.raises(ValidationError):
        PublicEventEnvelope.model_validate(event | {"createdAt": "2026-08-09T15:00:00"})
    with pytest.raises(ValueError, match="JSON object"):
        serialize_public_event(
            {
                "seq": 1,
                "season_id": 1,
                "tick": 0,
                "event_type": "tick",
                "payload_json": "[]",
                "created_at": "2026-08-09T15:00:00+00:00",
            }
        )
