from __future__ import annotations

import datetime as dt
import signal
import threading
import time
from typing import Any

from .config import Settings
from .control import ControlServer
from .db import connect, emit, initialize, now_iso
from .observability import configure_logging, log_event
from .reporter import generate_report
from .world import (
    advance_tick,
    diagnose,
    pause,
    queue_conversation_if_needed,
    resume,
    start_season,
    stop_after_day,
    stop_now,
)


class Engine:
    max_tick_failures = 3

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        self.connection = initialize(self.settings)
        self.stop_event = threading.Event()
        self.control = ControlServer(
            self.settings.control_socket,
            {
                "status": lambda params: self._control(self._diagnose),
                "start_season": lambda params: self._control(
                    lambda connection: start_season(
                        connection, opening_slug=params.get("openingSlug")
                    )
                ),
                "pause": lambda params: self._control_operation(pause),
                "resume": lambda params: self._control_operation(resume),
                "stop_after_day": lambda params: self._control_operation(stop_after_day),
                "stop_now": lambda params: self._control_operation(stop_now),
                "diagnose": lambda params: self._control(self._diagnose),
                "rebuild_report": self._rebuild_report,
            },
        )

    def _ensure_report(self, connection) -> None:
        season = connection.execute(
            "SELECT id,status FROM seasons ORDER BY number DESC LIMIT 1"
        ).fetchone()
        if not season or season["status"] != "complete":
            return
        exists = connection.execute(
            "SELECT 1 FROM reports WHERE season_id=?", (season["id"],)
        ).fetchone()
        if not exists:
            generate_report(connection, int(season["id"]), self.settings)
            connection.commit()

    def _continue_if_due(self, connection) -> dict[str, Any] | None:
        season = connection.execute(
            "SELECT number,status,completed_at,completion_reason FROM seasons ORDER BY number DESC LIMIT 1"
        ).fetchone()
        if (
            not season
            or season["status"] != "complete"
            or season["completion_reason"] != "natural"
            or not self.settings.auto_continue
            or int(season["number"]) >= self.settings.season_limit
        ):
            return None
        completed_at = dt.datetime.fromisoformat(str(season["completed_at"]))
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=dt.timezone.utc)
        elapsed = (dt.datetime.now(dt.timezone.utc) - completed_at).total_seconds()
        if elapsed < self.settings.intermission_seconds:
            return None
        return start_season(connection)

    def _control(self, callback):
        connection = connect(self.settings.database_path)
        try:
            result = callback(connection)
            self._ensure_report(connection)
            return result
        finally:
            connection.close()

    def _control_operation(self, operation):
        def invoke(connection):
            operation(connection)
            return self._diagnose(connection)

        return self._control(invoke)

    def _diagnose(self, connection):
        return diagnose(
            connection,
            tick_seconds=self.settings.tick_seconds,
            tick_stale_seconds=self.settings.tick_stale_seconds,
        )

    def _rebuild_report(self, params: dict[str, Any]) -> dict[str, Any]:
        season_id = int(params.get("seasonId") or 0)
        def rebuild(connection):
            selected_id = season_id
            if not selected_id:
                row = connection.execute("SELECT id FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
                if not row:
                    raise RuntimeError("no season")
                selected_id = int(row["id"])
            path = generate_report(connection, selected_id, self.settings)
            connection.commit()
            return {"seasonId": selected_id, "poster": path.name}

        return self._control(rebuild)

    def _record_tick_failure(self, error: Exception, elapsed_ms: int) -> dict[str, Any]:
        season = self.connection.execute(
            "SELECT id,number,status,current_tick FROM seasons ORDER BY number DESC LIMIT 1"
        ).fetchone()
        if not season:
            raise error
        timestamp = now_iso()
        self.connection.execute(
            """
            INSERT INTO runtime_incidents(
              season_id,tick,component,incident_key,error_class,status,
              attempts,first_at,last_at
            ) VALUES(?,?, 'engine','advance_tick',?,'open',1,?,?)
            ON CONFLICT(season_id,tick,component,incident_key) DO UPDATE SET
              error_class=excluded.error_class,status='open',
              attempts=runtime_incidents.attempts+1,last_at=excluded.last_at,resolved_at=NULL
            """,
            (
                int(season["id"]),
                int(season["current_tick"]),
                type(error).__name__[:80],
                timestamp,
                timestamp,
            ),
        )
        incident = self.connection.execute(
            """
            SELECT id,attempts,error_class FROM runtime_incidents
            WHERE season_id=? AND tick=? AND component='engine' AND incident_key='advance_tick'
            """,
            (season["id"], season["current_tick"]),
        ).fetchone()
        attempts = int(incident["attempts"])
        if attempts >= self.max_tick_failures:
            self.connection.execute(
                "UPDATE seasons SET status='paused' WHERE id=?",
                (season["id"],),
            )
        emit(
            self.connection,
            int(season["id"]),
            int(season["current_tick"]),
            "runtime_incident",
            {
                "component": "engine",
                "status": "paused" if attempts >= self.max_tick_failures else "retrying",
                "attempts": attempts,
            },
        )
        self.connection.commit()
        log_event(
            "engine",
            "tick_failed",
            season=int(season["number"]),
            tick=int(season["current_tick"]),
            status="paused" if attempts >= self.max_tick_failures else "retrying",
            errorClass=incident["error_class"],
            attempt=attempts,
            elapsedMs=elapsed_ms,
        )
        return {
            "advanced": False,
            "status": "paused" if attempts >= self.max_tick_failures else "retrying",
            "tick": int(season["current_tick"]),
            "incidentId": int(incident["id"]),
            "attempts": attempts,
        }

    def _resolve_tick_incident(self, attempted_tick: int) -> None:
        timestamp = now_iso()
        changed = self.connection.execute(
            """
            UPDATE runtime_incidents SET status='resolved',resolved_at=?,last_at=?
            WHERE status='open' AND component='engine' AND incident_key='advance_tick'
              AND season_id=(SELECT id FROM seasons ORDER BY number DESC LIMIT 1)
              AND tick=?
            """,
            (timestamp, timestamp, attempted_tick),
        ).rowcount
        if changed:
            self.connection.commit()
            log_event("engine", "tick_recovered", tick=attempted_tick, status="resolved")

    def _advance_once(self) -> dict[str, Any]:
        row = self.connection.execute(
            "SELECT current_tick FROM seasons ORDER BY number DESC LIMIT 1"
        ).fetchone()
        attempted_tick = int(row["current_tick"]) if row else 0
        started = time.monotonic()
        try:
            result = advance_tick(self.connection)
        except Exception as error:
            return self._record_tick_failure(
                error,
                max(0, round((time.monotonic() - started) * 1000)),
            )
        if result.get("advanced"):
            self._resolve_tick_incident(attempted_tick)
        result["elapsedMs"] = max(0, round((time.monotonic() - started) * 1000))
        return result

    def run(self) -> None:
        self.control.start()
        deadline = time.monotonic()
        snapshot = self._diagnose(self.connection)
        season = snapshot.get("season") or {}
        log_event(
            "engine",
            "engine_started",
            season=season.get("number"),
            tick=season.get("currentTick"),
            sequence=snapshot["runtime"]["eventSequence"],
        )
        while not self.stop_event.is_set():
            result = self._advance_once()
            if result.get("advanced") and int(result.get("tick", 0)) % 36 == 0:
                queue_conversation_if_needed(self.connection)
            if result.get("status") == "complete":
                self._ensure_report(self.connection)
                continued = self._continue_if_due(self.connection)
                if continued:
                    result = {"advanced": False, "status": "running", **continued}
            tick = int(result.get("tick", 0))
            if result.get("advanced") and tick % 12 == 0:
                row = self.connection.execute(
                    "SELECT number FROM seasons ORDER BY number DESC LIMIT 1"
                ).fetchone()
                sequence = int(self.connection.execute(
                    "SELECT COALESCE(MAX(seq),0) FROM event_stream"
                ).fetchone()[0])
                log_event(
                    "engine",
                    "tick_advanced",
                    season=int(row["number"]) if row else None,
                    tick=tick,
                    sequence=sequence,
                    elapsedMs=result.get("elapsedMs"),
                )
            deadline += self.settings.tick_seconds
            wait = deadline - time.monotonic()
            if not result.get("advanced"):
                wait = min(1.0, self.settings.tick_seconds)
                deadline = time.monotonic() + wait
            self.stop_event.wait(max(0.01, wait))

    def close(self) -> None:
        self.stop_event.set()
        self.control.close()
        self.connection.close()


def main() -> None:
    configure_logging()
    engine = Engine()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: engine.stop_event.set())
    try:
        engine.run()
    finally:
        log_event("engine", "engine_stopped")
        engine.close()


if __name__ == "__main__":
    main()
