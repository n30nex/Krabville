from __future__ import annotations

from PIL import Image

import json
from pathlib import Path
import pytest
import krabville.engine as engine_module

from krabville.content import MAJOR_EVENTS, MICRO_EVENTS, PATH_EDGES, PATH_NODES
from krabville.db import initialize, loads, now_iso, retrieve_memories
from krabville.engine import Engine
from krabville.legacy import import_week_one
from krabville.reporter import generate_report
from krabville.world import TARGET_TICKS, advance_tick, diagnose, start_season, stop_now


def test_curated_content_counts() -> None:
    assert len(MAJOR_EVENTS) == 72
    assert len(MICRO_EVENTS) == 72
    assert {event.category for event in MAJOR_EVENTS} == {
        "social",
        "civic",
        "environment",
        "economy",
        "relationship",
        "strange",
    }


def test_campaign_continues_only_natural_seasons_and_stops_at_limit(settings_factory) -> None:
    settings = settings_factory(intermission_seconds=0, season_limit=2)
    engine = Engine(settings)
    try:
        first = start_season(engine.connection, seed_hex="10" * 32)
        engine.connection.execute(
            """
            UPDATE seasons SET status='complete',model_locked=1,completion_reason='operator_stop',completed_at=?
            WHERE id=?
            """,
            (now_iso(), first["seasonId"]),
        )
        assert engine._continue_if_due(engine.connection) is None
        engine.connection.execute(
            "UPDATE seasons SET completion_reason='natural' WHERE id=?",
            (first["seasonId"],),
        )
        second = engine._continue_if_due(engine.connection)
        assert second and second["number"] == 2
        engine.connection.execute(
            """
            UPDATE seasons SET status='complete',model_locked=1,completion_reason='natural',completed_at=?
            WHERE id=?
            """,
            (now_iso(), second["seasonId"]),
        )
        assert engine._continue_if_due(engine.connection) is None
    finally:
        engine.close()


def test_tick_failure_retries_same_tick_and_resolves(monkeypatch, settings_factory) -> None:
    engine = Engine(settings_factory())
    try:
        season_id = start_season(engine.connection, seed_hex="11" * 32)["seasonId"]
        real_advance = engine_module.advance_tick
        failures = 0

        def flaky(connection):
            nonlocal failures
            if failures < 2:
                failures += 1
                raise RuntimeError("injected tick failure")
            return real_advance(connection)

        monkeypatch.setattr(engine_module, "advance_tick", flaky)
        assert engine._advance_once()["status"] == "retrying"
        assert engine._advance_once()["status"] == "retrying"
        assert engine.connection.execute(
            "SELECT current_tick FROM seasons WHERE id=?", (season_id,)
        ).fetchone()[0] == 0
        assert engine._advance_once()["advanced"] is True
        assert engine.connection.execute(
            "SELECT current_tick FROM seasons WHERE id=?", (season_id,)
        ).fetchone()[0] == 1
        incident = engine.connection.execute(
            "SELECT status,attempts,error_class FROM runtime_incidents"
        ).fetchone()
        assert dict(incident) == {
            "status": "resolved",
            "attempts": 2,
            "error_class": "RuntimeError",
        }
    finally:
        engine.close()


def test_three_tick_failures_pause_without_skipping(monkeypatch, settings_factory) -> None:
    engine = Engine(settings_factory())
    try:
        season_id = start_season(engine.connection, seed_hex="12" * 32)["seasonId"]

        def always_fail(connection):
            raise ValueError("injected persistent failure")

        monkeypatch.setattr(engine_module, "advance_tick", always_fail)
        results = [engine._advance_once() for _ in range(3)]
        assert [result["status"] for result in results] == [
            "retrying",
            "retrying",
            "paused",
        ]
        season = engine.connection.execute(
            "SELECT status,current_tick FROM seasons WHERE id=?", (season_id,)
        ).fetchone()
        assert dict(season) == {"status": "paused", "current_tick": 0}
        snapshot = engine._diagnose(engine.connection)
        assert snapshot["ok"] is False
        assert snapshot["runtime"]["incidents"]["open"] == 1
        assert snapshot["runtime"]["incidents"]["recent"][0]["attempts"] == 3
    finally:
        engine.close()


def test_seed_replay_is_deterministic(settings_factory) -> None:
    snapshots = []
    seed = "17" * 32
    for name in ("a", "b"):
        settings = settings_factory(name=name)
        connection = initialize(settings)
        start_season(connection, seed_hex=seed)
        for _ in range(40):
            advance_tick(connection)
        snapshots.append(
            (
                [
                    tuple(row)
                    for row in connection.execute(
                        "SELECT slug,title,category,participants_json FROM town_events ORDER BY id"
                    )
                ],
                [
                    tuple(row)
                    for row in connection.execute(
                        """
                        SELECT r.slug,s.x,s.y,s.location,s.activity,s.needs_json
                        FROM resident_state s JOIN residents r ON r.id=s.resident_id
                        ORDER BY r.id
                        """
                    )
                ],
            )
        )
        connection.close()
    assert snapshots[0] == snapshots[1]


def test_residents_follow_the_walkway_graph(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="19" * 32)
    for _ in range(73):
        advance_tick(connection)
    valid_points = {tuple(point) for point in PATH_NODES.values()}
    paths = [loads(row[0], []) for row in connection.execute("SELECT path_json FROM resident_state")]
    assert any(len(path) >= 2 for path in paths)
    assert all(tuple(point) in valid_points for path in paths for point in path)
    node_for_point = {point: name for name, point in PATH_NODES.items()}
    edges = {frozenset(edge) for edge in PATH_EDGES}
    for path in paths:
        names = [node_for_point[tuple(point)] for point in path]
        assert all(frozenset(pair) in edges for pair in zip(names, names[1:]))
    connection.close()


def test_diagnostics_are_current_season_only_and_do_not_reveal_seed(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="63" * 32)
    snapshot = diagnose(connection)
    assert snapshot["season"]["seedCommitment"]
    assert "seed_hex" not in json.dumps(snapshot)
    assert snapshot["jobs"]
    assert snapshot["runtime"]["eventSequence"] > 0
    assert snapshot["runtime"]["queue"]["staleLeases"] == 0
    assert snapshot["runtime"]["tickFreshness"]["stale"] is False
    connection.close()


def test_diagnostics_flag_stale_tick_and_expired_model_lease(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    season_id = start_season(connection, seed_hex="64" * 32)["seasonId"]
    connection.execute(
        "UPDATE seasons SET started_at='2000-01-01T00:00:00+00:00' WHERE id=?",
        (season_id,),
    )
    connection.execute(
        "UPDATE model_jobs SET status='leased',lease_until='2000-01-01T00:00:00+00:00' "
        "WHERE id=(SELECT MIN(id) FROM model_jobs WHERE season_id=?)",
        (season_id,),
    )
    snapshot = diagnose(connection, tick_seconds=0.01, tick_stale_seconds=1)
    assert snapshot["ok"] is False
    assert snapshot["status"] == "degraded"
    assert snapshot["runtime"]["tickFreshness"]["stale"] is True
    assert snapshot["runtime"]["queue"]["staleLeases"] == 1
    connection.close()


def test_memories_and_relationships_persist(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    first = start_season(connection, seed_hex="21" * 32)
    resident_ids = [row[0] for row in connection.execute("SELECT id FROM residents ORDER BY id LIMIT 2")]
    first_resident, second_resident = resident_ids
    low, high = sorted((first_resident, second_resident))
    connection.execute(
        """
        UPDATE relationships SET affinity=31,trust=27,tension=4,familiarity=52,interactions=8
        WHERE season_id=? AND resident_a=? AND resident_b=?
        """,
        (first["seasonId"], low, high),
    )
    connection.execute(
        """
        INSERT INTO memories(
          season_id,resident_id,kind,content,tags,salience,created_tick,durable
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (first["seasonId"], first_resident, "event", "The radio survived the summer storm.", "radio storm", 9, 20, 1),
    )
    found = retrieve_memories(connection, first["seasonId"], first_resident, "radio storm")
    assert found[0]["content"] == "The radio survived the summer storm."
    fallback = retrieve_memories(connection, first["seasonId"], first_resident, "unmatched constellation")
    assert fallback[0]["content"] == "The radio survived the summer storm."
    stop_now(connection)
    second = start_season(connection, seed_hex="22" * 32)
    relationship = connection.execute(
        """
        SELECT * FROM relationships WHERE season_id=? AND resident_a=? AND resident_b=?
        """,
        (second["seasonId"], low, high),
    ).fetchone()
    assert tuple(relationship[key] for key in ("affinity", "trust", "tension", "familiarity", "interactions")) == (31, 27, 4, 52, 8)
    carried = connection.execute(
        "SELECT content,durable FROM memories WHERE season_id=? AND resident_id=?",
        (second["seasonId"], first_resident),
    ).fetchone()
    assert carried["content"] == "The radio survived the summer storm."
    assert carried["durable"] == 1
    connection.close()


def test_utility_loop_keeps_needs_bounded_and_advances_goals(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="25" * 32)
    for _ in range(130):
        advance_tick(connection)
    needs = [loads(row[0], {}) for row in connection.execute("SELECT needs_json FROM resident_state")]
    assert all(0 <= value <= 100 for resident in needs for value in resident.values())
    assert connection.execute("SELECT MAX(progress) FROM goals").fetchone()[0] > 0
    assert connection.execute("SELECT COUNT(DISTINCT activity) FROM resident_state").fetchone()[0] >= 2
    connection.close()


def test_legacy_week_one_import_is_idempotent(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "legacy" / "season-one.json").read_text(encoding="utf-8"))
    first = import_week_one(
        connection,
        payload,
        poster_source=root / "legacy" / "season-001.png",
        report_dir=settings.report_dir,
    )
    second = import_week_one(connection, payload)
    assert first == second
    assert connection.execute("SELECT COUNT(*) FROM seasons").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM daily_chronicles").fetchone()[0] == 7
    assert (settings.report_dir / "season-001.png").exists()
    started = start_season(connection, seed_hex="24" * 32)
    assert started["number"] == 2
    connection.close()


def test_season_twenty_is_a_hard_boundary(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    for index in range(20):
        start_season(connection, seed_hex=f"{index + 1:064x}")
        stop_now(connection)
    with pytest.raises(RuntimeError, match="twenty-season"):
        start_season(connection, seed_hex=f"{21:064x}")
    assert connection.execute("SELECT COUNT(*) FROM seasons").fetchone()[0] == 20
    assert connection.execute("SELECT COUNT(*) FROM residents").fetchone()[0] == 12
    assert connection.execute("SELECT MAX(number) FROM seasons").fetchone()[0] == 20
    connection.close()


def test_early_stop_keeps_actual_tick(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="31" * 32)
    for _ in range(17):
        advance_tick(connection)
    stop_now(connection)
    season = connection.execute("SELECT * FROM seasons").fetchone()
    assert season["status"] == "complete"
    assert season["current_tick"] == 17
    assert season["target_ticks"] == 17
    assert season["completion_reason"] == "operator_stop"
    assert season["seed_revealed"] == 1
    connection.close()


def test_poll_winner_becomes_next_day_catalyst(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    season_id = start_season(connection, seed_hex="41" * 32)["seasonId"]
    for _ in range(25):
        advance_tick(connection)
    poll = connection.execute("SELECT * FROM polls WHERE season_id=?", (season_id,)).fetchone()
    option = connection.execute(
        "SELECT * FROM poll_options WHERE poll_id=? ORDER BY choice_id LIMIT 1 OFFSET 1",
        (poll["id"],),
    ).fetchone()
    connection.execute("UPDATE poll_options SET votes=7 WHERE id=?", (option["id"],))
    while connection.execute("SELECT current_tick FROM seasons WHERE id=?", (season_id,)).fetchone()[0] < 289:
        advance_tick(connection)
    next_event = connection.execute(
        "SELECT slug,source FROM town_events WHERE season_id=? AND day=1", (season_id,)
    ).fetchone()
    assert next_event["slug"] == option["event_slug"]
    assert next_event["source"] == "vote"
    connection.close()


def test_completed_season_report_is_local_1080p(settings_factory) -> None:
    settings = settings_factory(asset_dir=Path(__file__).resolve().parents[1] / "frontend" / "public" / "assets")
    connection = initialize(settings)
    season_id = start_season(connection, seed_hex="51" * 32)["seasonId"]
    connection.execute(
        "UPDATE seasons SET current_tick=? WHERE id=?", (TARGET_TICKS - 1, season_id)
    )
    result = advance_tick(connection)
    assert result["status"] == "complete"
    assert not connection.execute("SELECT 1 FROM reports WHERE season_id=?", (season_id,)).fetchone()
    poster = generate_report(connection, season_id, settings)
    connection.commit()
    with Image.open(poster) as image:
        assert image.size == (1920, 1080)
        assert image.mode == "RGB"
    assert connection.execute("SELECT 1 FROM reports WHERE season_id=?", (season_id,)).fetchone()
    connection.close()
