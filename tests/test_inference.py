from __future__ import annotations

import json

from krabville.db import initialize
from pathlib import Path

import pytest

from krabville.inference import (
    CodexProvider,
    FakeProvider,
    _assert_no_tool_events,
    _validate,
    process_one,
    run_worker,
)
from krabville.world import _queue_job, start_season, stop_now


class FallbackProvider:
    def __init__(self):
        self.calls = []

    def complete(self, job, model, reasoning):
        self.calls.append((model, reasoning))
        if len(self.calls) == 1:
            raise TimeoutError("simulated primary timeout")
        return FakeProvider().complete(job, model, reasoning)


class AlwaysFailProvider:
    def complete(self, job, model, reasoning):
        raise RuntimeError("simulated interrupted request")


class PrimaryFailProvider:
    def __init__(self, primary: str):
        self.primary = primary
        self.calls = []

    def complete(self, job, model, reasoning):
        self.calls.append(model)
        if model == self.primary:
            raise ValueError("synthetic schema mismatch")
        return FakeProvider().complete(job, model, reasoning)


def test_codex_prompt_uses_the_tv14_story_boundary(settings_factory) -> None:
    settings = settings_factory()
    prompt = CodexProvider(settings, settings.database_path)._prompt(
        {"context_json": json.dumps({"event": "A friendship is under strain."})}
    )
    assert "TV-14" in prompt
    assert "realistic disagreements" in prompt
    assert "sexualized minors" in prompt
    assert "family-friendly" not in prompt


def test_all_provider_schemas_are_strict_objects() -> None:
    schema_dir = Path(__file__).parents[1] / "src" / "krabville" / "schemas"

    def assert_strict(node: object, path: Path) -> None:
        if isinstance(node, list):
            for child in node:
                assert_strict(child, path)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            properties = node.get("properties")
            assert isinstance(properties, dict), path
            assert node.get("additionalProperties") is False, path
            assert set(node.get("required", [])) == set(properties), path
        for child in node.values():
            assert_strict(child, path)

    for path in sorted(schema_dir.glob("*.json")):
        assert_strict(json.loads(path.read_text(encoding="utf-8")), path)


def test_spark_failure_falls_back_once_to_luna(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="61" * 32)
    provider = FallbackProvider()
    assert process_one(connection, settings, provider)
    assert provider.calls == [
        ("gpt-5.3-codex-spark", "low"),
        ("gpt-5.6-luna", "low"),
    ]
    usage = list(connection.execute("SELECT model,status,attempt_number FROM model_usage ORDER BY id"))
    assert [tuple(row) for row in usage] == [
        ("gpt-5.3-codex-spark", "failed", 1),
        ("gpt-5.6-luna", "complete", 2),
    ]
    connection.close()


def test_interrupted_attempt_is_reserved_and_counted(settings_factory) -> None:
    settings = settings_factory(call_limit=1)
    connection = initialize(settings)
    start_season(connection, seed_hex="62" * 32)
    assert process_one(connection, settings, AlwaysFailProvider())
    row = connection.execute("SELECT * FROM model_usage").fetchone()
    assert row["status"] == "failed"
    assert row["total_tokens"] == 8000
    assert connection.execute("SELECT COUNT(*) FROM model_usage").fetchone()[0] == 1
    connection.close()


def test_call_150_can_start_but_151_cannot(settings_factory) -> None:
    settings = settings_factory(call_limit=150, token_guard=2_000_000)
    connection = initialize(settings)
    season_id = start_season(connection, seed_hex="63" * 32)["seasonId"]
    for attempt in range(1, 150):
        connection.execute(
            """
            INSERT INTO model_usage(
              season_id,attempt_number,model,status,total_tokens,reserved_at,completed_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (season_id, attempt, "fixture", "complete", 1, "now", "now"),
        )
    assert process_one(connection, settings, FakeProvider())
    assert connection.execute("SELECT COUNT(*) FROM model_usage").fetchone()[0] == 150
    _queue_job(
        connection,
        season_id,
        0,
        1,
        "season_opener",
        0,
        {"budgetProof": "attempt-151"},
    )
    assert process_one(connection, settings, FakeProvider())
    assert connection.execute("SELECT COUNT(*) FROM model_usage").fetchone()[0] == 150
    assert connection.execute("SELECT model_degraded FROM seasons WHERE id=?", (season_id,)).fetchone()[0] == 1
    connection.close()


def test_one_point_five_million_token_guard_is_hard(settings_factory) -> None:
    settings = settings_factory(token_guard=1_500_000)
    connection = initialize(settings)
    season_id = start_season(connection, seed_hex="68" * 32)["seasonId"]
    connection.execute(
        """
        INSERT INTO model_usage(
          season_id,attempt_number,model,status,total_tokens,reserved_at,completed_at
        ) VALUES(?,1,'fixture','complete',1492001,'now','now')
        """,
        (season_id,),
    )
    assert process_one(connection, settings, FakeProvider())
    assert connection.execute(
        "SELECT COUNT(*) FROM model_usage WHERE season_id=?", (season_id,)
    ).fetchone()[0] == 1
    job = connection.execute(
        "SELECT status,error_code FROM model_jobs WHERE season_id=? ORDER BY id LIMIT 1",
        (season_id,),
    ).fetchone()
    assert tuple(job) == ("failed", "budget_exhausted")
    connection.close()


def test_completed_worker_restart_makes_no_calls(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    season_id = start_season(connection, seed_hex="64" * 32)["seasonId"]
    stop_now(connection)
    before = connection.execute("SELECT COUNT(*) FROM model_usage WHERE season_id=?", (season_id,)).fetchone()[0]
    connection.close()
    assert run_worker(settings, once=True) == 0
    connection = initialize(settings)
    after = connection.execute("SELECT COUNT(*) FROM model_usage WHERE season_id=?", (season_id,)).fetchone()[0]
    assert after == before == 0
    connection.close()


def test_expired_lease_is_recovered(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="65" * 32)
    connection.execute(
        "UPDATE model_jobs SET status='leased',lease_until='2000-01-01T00:00:00+00:00' WHERE id=(SELECT MIN(id) FROM model_jobs)"
    )
    assert process_one(connection, settings, FakeProvider())
    row = connection.execute("SELECT status,error_code FROM model_jobs ORDER BY id LIMIT 1").fetchone()
    assert row["status"] == "complete"
    assert row["error_code"] is None
    connection.close()


def test_requeued_job_recovers_from_a_stale_attempt_counter(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    season_id = start_season(connection, seed_hex="66" * 32)["seasonId"]
    job_id = connection.execute("SELECT MIN(id) FROM model_jobs WHERE season_id=?", (season_id,)).fetchone()[0]
    connection.execute(
        """
        INSERT INTO model_usage(
          season_id,job_id,attempt_number,model,status,total_tokens,reserved_at,completed_at
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (season_id, job_id, 1, settings.primary_model, "failed", 8000, "now", "now"),
    )
    connection.execute("UPDATE model_jobs SET attempts=0,status='queued' WHERE id=?", (job_id,))
    connection.commit()

    assert process_one(connection, settings, FakeProvider())
    attempts = connection.execute(
        "SELECT attempt_number,model,status FROM model_usage WHERE job_id=? ORDER BY attempt_number",
        (job_id,),
    ).fetchall()
    assert [tuple(row) for row in attempts] == [
        (1, settings.primary_model, "failed"),
        (2, settings.fallback_model, "complete"),
    ]
    assert connection.execute("SELECT attempts FROM model_jobs WHERE id=?", (job_id,)).fetchone()[0] == 2
    connection.close()


def test_provider_tool_events_fail_closed(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(
        '{"type":"item.completed","item":{"type":"agent_message"}}\n'
        '{"type":"item.started","item":{"type":"command_execution"}}\n',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="disallowed tool"):
        _assert_no_tool_events(events)


@pytest.mark.parametrize(
    "unsafe",
    [
        "Visit https://example.invalid now",
        "The password is synthetic-test-only",
        "Read /home/neonx/private.txt",
        "Contact @operator about 192.0.2.44",
        "Run sudo docker exec service sh",
    ],
)
def test_provider_rejects_operational_text(unsafe: str) -> None:
    with pytest.raises(ValueError, match="operational data"):
        _validate("season_opener", {"headline": "A safe title", "publicNote": unsafe})


def test_chronicle_references_must_match_the_authoritative_context() -> None:
    context = {
        "ledger": [{"id": 41, "residents": ["hana-sato"]}],
        "residentAllowlist": [{"slug": "hana-sato", "name": "Hana Sato"}],
    }
    valid = {
        "title": "A factual day",
        "narrative": "Hana reviewed the recorded event.",
        "ledgerIds": [41],
        "residentSlugs": ["hana-sato"],
    }
    assert _validate("chronicle", valid, context)["ledgerIds"] == [41]
    with pytest.raises(ValueError, match="unknown ledger"):
        _validate("chronicle", {**valid, "ledgerIds": [99]}, context)
    with pytest.raises(ValueError, match="unknown resident"):
        _validate("chronicle", {**valid, "residentSlugs": ["mara"]}, context)


def test_resident_batches_cover_the_full_population_cap() -> None:
    residents = [{"slug": f"resident-{index}"} for index in range(24)]
    items = [
        {
            "slug": resident["slug"],
            "intention": "Complete a useful task.",
            "reflection": "The day changed one practical choice.",
            "publicThought": "I know what to do next.",
        }
        for resident in residents
    ]
    assert len(_validate("resident_intent", {"items": items}, {"residents": residents})["items"]) == 24
    with pytest.raises(ValueError, match="one to twenty-four"):
        _validate(
            "resident_reflection",
            {"items": items + [{**items[0], "slug": "resident-24"}]},
            {"residents": residents + [{"slug": "resident-24"}]},
        )


def test_intent_preferences_are_allowlisted_and_bounded() -> None:
    context = {"residents": [{"slug": "hana-sato"}]}
    base = {
        "slug": "hana-sato",
        "intention": "Finish useful work.",
        "reflection": "The plan is practical.",
        "publicThought": "I will focus for a while.",
        "preferenceTags": ["Useful Work", "community"],
    }
    valid = _validate(
        "resident_intent", {"items": [{**base, "preferredAction": "pursue_purpose"}]}, context,
    )["items"][0]
    rejected = _validate(
        "resident_intent", {"items": [{**base, "preferredAction": "run_shell"}]}, context,
    )["items"][0]
    assert valid["preferredAction"] == "pursue_purpose"
    assert valid["preferenceTags"] == ["useful work", "community"]
    assert rejected["preferredAction"] == ""


def test_two_primary_schema_failures_open_a_same_day_kind_circuit(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    season_id = start_season(connection, seed_hex="67" * 32)["seasonId"]
    _queue_job(connection, season_id, 0, 1, "season_opener", 0, {"fixture": 2})
    _queue_job(connection, season_id, 0, 2, "season_opener", 0, {"fixture": 3})
    provider = PrimaryFailProvider(settings.primary_model)

    assert process_one(connection, settings, provider)
    assert process_one(connection, settings, provider)
    assert process_one(connection, settings, provider)

    assert provider.calls == [
        settings.primary_model,
        settings.fallback_model,
        settings.primary_model,
        settings.fallback_model,
        settings.fallback_model,
    ]
    circuit = connection.execute(
        """
        SELECT status,consecutive_failures FROM model_circuits
        WHERE season_id=? AND day=0 AND job_kind='season_opener' AND model=?
        """,
        (season_id, settings.primary_model),
    ).fetchone()
    assert tuple(circuit) == ("open", 2)
    failures = list(
        connection.execute(
            """
            SELECT error_class,duration_ms FROM model_usage
            WHERE season_id=? AND model=? AND status='failed'
            """,
            (season_id, settings.primary_model),
        )
    )
    assert len(failures) == 2
    assert all(row["error_class"] == "schema_validation" for row in failures)
    assert all(int(row["duration_ms"]) >= 0 for row in failures)
    connection.close()
