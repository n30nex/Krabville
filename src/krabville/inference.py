from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import tempfile
import time
import datetime as dt
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .db import connect, dumps, initialize, loads, now_iso, transaction
from .security import validate_public_text


class Provider(Protocol):
    def complete(self, job: sqlite3.Row, model: str, reasoning: str) -> tuple[dict[str, Any], dict[str, int]]: ...


class BudgetExhausted(RuntimeError):
    pass


class SeasonLocked(RuntimeError):
    pass


class ProviderProcessError(RuntimeError):
    pass


def _public(value: Any, maximum: int) -> str:
    return validate_public_text(value, maximum)


def _assert_no_tool_events(path: Path) -> None:
    allowed_items = {"agent_message", "reasoning"}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        event_type = str(event.get("type", ""))
        if event_type.startswith(("tool.", "command.", "mcp.")):
            raise RuntimeError("provider attempted disallowed tool activity")
        if event_type not in {"item.started", "item.updated", "item.completed"}:
            continue
        item = event.get("item")
        item_type = str(item.get("type", "")) if isinstance(item, dict) else ""
        if item_type and item_type not in allowed_items:
            raise RuntimeError("provider attempted disallowed tool activity")


def _validate(kind: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("provider result must be an object")
    if kind in {"resident_intent", "resident_reflection"}:
        items = value.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 4:
            raise ValueError("resident batch requires one to four items")
        clean = []
        for item in items:
            if not isinstance(item, dict) or not item.get("slug"):
                continue
            clean.append(
                {
                    "slug": _public(item["slug"], 80),
                    "intention": _public(item.get("intention", ""), 240),
                    "reflection": _public(item.get("reflection", ""), 360),
                    "publicThought": _public(item.get("publicThought", ""), 280),
                }
            )
        if not clean:
            raise ValueError("resident batch contained no valid items")
        return {"items": clean}
    if kind == "conversation":
        dialogue = value.get("dialogue")
        if not isinstance(dialogue, list) or not 2 <= len(dialogue) <= 8:
            raise ValueError("conversation requires two to eight lines")
        clean_lines = []
        for line in dialogue:
            if isinstance(line, dict) and line.get("speaker") and line.get("text"):
                clean_lines.append({"speaker": _public(line["speaker"], 80), "text": _public(line["text"], 320)})
        if len(clean_lines) < 2:
            raise ValueError("conversation contained too few valid lines")
        return {"dialogue": clean_lines, "summary": _public(value.get("summary", ""), 320)}
    if kind == "chronicle":
        statistics = {
            str(key)[:40]: number
            for key, number in value.get("statistics", {}).items()
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", str(key))
            and isinstance(number, (int, float))
            and not isinstance(number, bool)
        } if isinstance(value.get("statistics"), dict) else {}
        return {
            "title": _public(value.get("title", "A day around the Lagoon"), 160),
            "narrative": _public(value.get("narrative", "Krabville carried on."), 1200),
            "statistics": statistics,
        }
    if kind in {"season_opener", "daily_director"}:
        return {
            "headline": _public(value.get("headline", "A new chapter begins"), 180),
            "publicNote": _public(value.get("publicNote", "The town is settling into the day."), 360),
        }
    raise ValueError(f"unsupported job kind: {kind}")


class FakeProvider:
    def complete(self, job: sqlite3.Row, model: str, reasoning: str) -> tuple[dict[str, Any], dict[str, int]]:
        context = loads(job["context_json"], {})
        kind = str(job["kind"])
        if kind in {"resident_intent", "resident_reflection"}:
            items = []
            for resident in context.get("residents", []):
                slug = str(resident.get("slug", "resident"))
                name = str(resident.get("name", slug.replace("-", " ").title()))
                items.append(
                    {
                        "slug": slug,
                        "intention": f"{name} will finish one useful task and notice who needs company.",
                        "reflection": f"{name} learned that ordinary routines can still change a relationship.",
                        "publicThought": "I should pay attention to the small choices that shape this place.",
                    }
                )
            result = {"items": items}
        elif kind == "conversation":
            names = context.get("names", ["Resident One", "Resident Two"])
            result = {
                "dialogue": [
                    {"speaker": names[0], "text": "The town feels different today. Did you notice it too?"},
                    {"speaker": names[1], "text": "I did. I think we should compare what we saw before deciding what it means."},
                ],
                "summary": f"{names[0]} and {names[1]} compared their view of the day's events.",
            }
        elif kind == "chronicle":
            day = int(context.get("day", 0)) + 1
            result = {
                "title": f"Day {day}: Small choices around the Lagoon",
                "narrative": "Residents balanced their routines with the day's catalyst, and several quiet choices changed how neighbours understood one another.",
                "statistics": {"activities": int(context.get("activities", 0))},
            }
        else:
            result = {
                "headline": "The Lagoon opens another chapter",
                "publicNote": "A familiar morning is beginning to bend around an unfamiliar event.",
            }
        return _validate(kind, result), {
            "input_tokens": 240,
            "cached_input_tokens": 0,
            "output_tokens": 90,
            "reasoning_tokens": 20,
            "total_tokens": 330,
        }


class CodexProvider:
    def __init__(self, settings: Settings, database_path: Path):
        self.settings = settings
        self.database_path = database_path
        self.binary = os.environ.get("KRABVILLE_CODEX_BIN", "/usr/local/bin/codex")
        self.schema_dir = Path(__file__).with_name("schemas")

    def _prompt(self, job: sqlite3.Row) -> str:
        context = loads(job["context_json"], {})
        serialized = json.dumps(context, ensure_ascii=True, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > 12 * 1024:
            raise ValueError("job context exceeds 12 KiB")
        return (
            "Act only as a bounded fiction writer for the Krabville social simulation. "
            "Do not use tools, files, shell commands, network access, or hidden reasoning. "
            "Return only the JSON object required by the supplied schema. Keep the fiction "
            "concise and grounded only in this context. Use a TV-14 tone with realistic "
            "disagreements, jealousy, rivalry, romance, mistakes, and consequences. Never "
            "include explicit sexual content, sexual violence, graphic violence, hate content, "
            "or sexualized minors. Context:\n" + serialized
        )

    def _locked(self, season_id: int) -> bool:
        connection = connect(self.database_path, readonly=True)
        try:
            row = connection.execute("SELECT status,model_locked FROM seasons WHERE id=?", (season_id,)).fetchone()
            return not row or bool(row["model_locked"]) or row["status"] != "running"
        finally:
            connection.close()

    def complete(self, job: sqlite3.Row, model: str, reasoning: str) -> tuple[dict[str, Any], dict[str, int]]:
        prompt = self._prompt(job)
        schema = self.schema_dir / f"{job['kind']}.json"
        if not schema.exists():
            schema = self.schema_dir / "narrative.json"
        with tempfile.TemporaryDirectory(prefix="krabville-") as directory:
            root = Path(directory)
            output_path = root / "result.json"
            stdout_path = root / "events.jsonl"
            stderr_path = root / "stderr.txt"
            command = [
                self.binary,
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--json",
                "--model",
                model,
                "-c",
                f'model_reasoning_effort="{reasoning}"',
                "--output-schema",
                str(schema),
                "-C",
                "/tmp",
                "--output-last-message",
                str(output_path),
                "-",
            ]
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr)
                assert process.stdin is not None
                process.stdin.write(prompt.encode("utf-8"))
                process.stdin.close()
                deadline = time.monotonic() + self.settings.inference_timeout
                while process.poll() is None:
                    if self._locked(int(job["season_id"])):
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        raise RuntimeError("season locked while inference was active")
                    if time.monotonic() >= deadline:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        raise TimeoutError("Codex inference timed out")
                    time.sleep(0.5)
            _assert_no_tool_events(stdout_path)
            if process.returncode:
                raise ProviderProcessError(f"Codex exited with status {process.returncode}")
            value = json.loads(output_path.read_text(encoding="utf-8"))
            usage = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0, "total_tokens": 0}
            for line in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
                    raw = event["usage"]
                    usage = {
                        "input_tokens": int(raw.get("input_tokens", 0)),
                        "cached_input_tokens": int(raw.get("cached_input_tokens", 0)),
                        "output_tokens": int(raw.get("output_tokens", 0)),
                        "reasoning_tokens": int(raw.get("reasoning_output_tokens", 0)),
                        "total_tokens": int(raw.get("input_tokens", 0)) + int(raw.get("output_tokens", 0)),
                    }
            return _validate(str(job["kind"]), value), usage


def _lease_job(connection: sqlite3.Connection) -> sqlite3.Row | None:
    with transaction(connection, immediate=True):
        season = connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
        if not season or season["status"] != "running" or season["model_locked"]:
            return None
        connection.execute(
            """
            UPDATE model_jobs SET status='queued',lease_until=NULL,error_code='lease_expired',updated_at=?
            WHERE season_id=? AND status='leased' AND lease_until<?
            """,
            (now_iso(), season["id"], now_iso()),
        )
        job = connection.execute(
            """
            SELECT * FROM model_jobs WHERE season_id=? AND status='queued'
            ORDER BY priority,id LIMIT 1
            """,
            (season["id"],),
        ).fetchone()
        if not job:
            return None
        lease_iso = (
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5)
        ).isoformat(timespec="seconds")
        connection.execute(
            "UPDATE model_jobs SET status='leased',lease_until=?,updated_at=? WHERE id=?",
            (lease_iso, now_iso(), job["id"]),
        )
        return connection.execute("SELECT * FROM model_jobs WHERE id=?", (job["id"],)).fetchone()


def _reserve_attempt(
    connection: sqlite3.Connection,
    settings: Settings,
    job: sqlite3.Row,
    model: str,
) -> int:
    with transaction(connection, immediate=True):
        season = connection.execute("SELECT * FROM seasons WHERE id=?", (job["season_id"],)).fetchone()
        if not season or season["status"] != "running" or season["model_locked"]:
            raise SeasonLocked("season is locked")
        current_job = connection.execute(
            "SELECT status,attempts FROM model_jobs WHERE id=?", (job["id"],)
        ).fetchone()
        if not current_job or current_job["status"] != "leased":
            raise SeasonLocked("job lease is no longer active")
        calls, tokens = connection.execute(
            "SELECT COUNT(*),COALESCE(SUM(total_tokens),0) FROM model_usage WHERE season_id=?",
            (job["season_id"],),
        ).fetchone()
        if int(calls) >= settings.call_limit:
            raise BudgetExhausted("season call budget exhausted")
        if int(tokens) + 8000 > settings.token_guard:
            raise BudgetExhausted("season token guard reached")
        attempt = int(current_job["attempts"]) + 1
        cursor = connection.execute(
            """
            INSERT INTO model_usage(
              season_id,job_id,attempt_number,model,status,total_tokens,reserved_at
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (job["season_id"], job["id"], attempt, model, "reserved", 8000, now_iso()),
        )
        connection.execute(
            "UPDATE model_jobs SET attempts=?,updated_at=? WHERE id=?",
            (attempt, now_iso(), job["id"]),
        )
        return int(cursor.lastrowid)


def _finish_usage(connection: sqlite3.Connection, usage_id: int, status: str, usage: dict[str, int] | None = None) -> None:
    if usage is None:
        connection.execute(
            "UPDATE model_usage SET status=?,completed_at=? WHERE id=?",
            (status, now_iso(), usage_id),
        )
        return
    connection.execute(
        """
        UPDATE model_usage SET status=?,input_tokens=?,cached_input_tokens=?,
          output_tokens=?,reasoning_tokens=?,total_tokens=?,completed_at=? WHERE id=?
        """,
        (
            status,
            int(usage.get("input_tokens", 0)),
            int(usage.get("cached_input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
            int(usage.get("reasoning_tokens", 0)),
            int(usage.get("total_tokens", 0)),
            now_iso(),
            usage_id,
        ),
    )


def process_one(connection: sqlite3.Connection, settings: Settings, provider: Provider) -> bool:
    job = _lease_job(connection)
    if not job:
        return False
    all_attempts = ((settings.primary_model, "low"), (settings.fallback_model, "high"))
    attempts = all_attempts[min(int(job["attempts"]), len(all_attempts)):]
    last_error = "provider_failed"
    for model, reasoning in attempts:
        try:
            usage_id = _reserve_attempt(connection, settings, job, model)
        except BudgetExhausted:
            last_error = "budget_exhausted"
            connection.execute(
                """
                UPDATE model_jobs SET status='cancelled',error_code='budget_exhausted',updated_at=?
                WHERE season_id=? AND status='queued'
                """,
                (now_iso(), job["season_id"]),
            )
            break
        except SeasonLocked:
            last_error = "season_locked"
            break
        try:
            result, usage = provider.complete(job, model, reasoning)
        except Exception as error:
            _finish_usage(connection, usage_id, "failed")
            last_error = type(error).__name__[:80]
            continue
        _finish_usage(connection, usage_id, "complete", usage)
        connection.execute(
            """
            UPDATE model_jobs SET status='complete',result_json=?,lease_until=NULL,
              error_code=NULL,updated_at=? WHERE id=?
            """,
            (dumps(result), now_iso(), job["id"]),
        )
        connection.commit()
        return True
    connection.execute(
        "UPDATE model_jobs SET status='failed',lease_until=NULL,error_code=?,updated_at=? WHERE id=?",
        (last_error, now_iso(), job["id"]),
    )
    connection.execute(
        "UPDATE seasons SET model_degraded=1 WHERE id=?", (job["season_id"],)
    )
    connection.commit()
    return True


def run_worker(settings: Settings | None = None, *, once: bool = False) -> int:
    settings = settings or Settings.from_env()
    connection = initialize(settings)
    provider: Provider = FakeProvider() if settings.fake_provider else CodexProvider(settings, settings.database_path)
    try:
        while True:
            season = connection.execute("SELECT status,model_locked FROM seasons ORDER BY number DESC LIMIT 1").fetchone()
            if season and season["status"] == "complete" and season["model_locked"]:
                if once:
                    return 0
                number = int(
                    connection.execute(
                        "SELECT number FROM seasons ORDER BY number DESC LIMIT 1"
                    ).fetchone()[0]
                )
                if not settings.auto_continue or number >= settings.season_limit:
                    return 0
                time.sleep(0.75)
                continue
            worked = process_one(connection, settings, provider)
            if once:
                return 0 if worked else 2
            if not worked:
                time.sleep(0.75)
    finally:
        connection.close()


def main() -> None:
    raise SystemExit(run_worker())


if __name__ == "__main__":
    main()
