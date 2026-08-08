from __future__ import annotations

from krabville.db import initialize
from pathlib import Path

import pytest

from krabville.inference import FakeProvider, _assert_no_tool_events, _validate, process_one, run_worker
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


def test_spark_failure_falls_back_once_to_luna(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="61" * 32)
    provider = FallbackProvider()
    assert process_one(connection, settings, provider)
    assert provider.calls == [
        ("gpt-5.3-codex-spark", "low"),
        ("gpt-5.6-luna", "high"),
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
