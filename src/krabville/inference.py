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
from .observability import configure_logging, log_event
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


def _validate(
    kind: str,
    value: Any,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
    if not isinstance(value, dict):
        raise ValueError("provider result must be an object")
    if kind in {"resident_intent", "resident_reflection"}:
        items = value.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 24:
            raise ValueError("resident batch requires one to twenty-four items")
        allowed_slugs = {
            str(resident.get("slug"))
            for resident in context.get("residents", [])
            if isinstance(resident, dict) and resident.get("slug")
        }
        clean = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict) or not item.get("slug"):
                continue
            slug = str(item["slug"])
            if allowed_slugs and slug not in allowed_slugs:
                raise ValueError("resident batch referenced an unknown resident")
            if slug in seen:
                raise ValueError("resident batch repeated a resident")
            seen.add(slug)
            clean_item = {
                    "slug": _public(slug, 80),
                    "intention": _public(item.get("intention", ""), 240),
                    "reflection": _public(item.get("reflection", ""), 360),
                    "publicThought": _public(item.get("publicThought", ""), 280),
                }
            if kind == "resident_intent":
                allowed_actions = {
                    "restore_energy", "eat_meal", "wash_up", "seek_healthcare",
                    "get_comfortable", "seek_safety", "have_fun", "socialize",
                    "join_community", "get_privacy", "pursue_purpose",
                    "reclaim_autonomy", "improve_finances", "secure_childcare",
                }
                action = str(item.get("preferredAction", "")).strip()
                tags = item.get("preferenceTags", [])
                clean_item["preferredAction"] = action if action in allowed_actions else ""
                clean_item["preferenceTags"] = [
                    _public(tag, 32).casefold()
                    for tag in tags[:4]
                    if isinstance(tag, str) and tag.strip()
                ] if isinstance(tags, list) else []
            clean.append(clean_item)
        if not clean:
            raise ValueError("resident batch contained no valid items")
        return {"items": clean}
    if kind == "conversation":
        dialogue = value.get("dialogue")
        if not isinstance(dialogue, list) or not 2 <= len(dialogue) <= 8:
            raise ValueError("conversation requires two to eight lines")
        allowed_speakers = {str(name) for name in context.get("names", [])}
        clean_lines = []
        for line in dialogue:
            if isinstance(line, dict) and line.get("speaker") and line.get("text"):
                if allowed_speakers and str(line["speaker"]) not in allowed_speakers:
                    raise ValueError("conversation used an invalid speaker")
                clean_lines.append({"speaker": _public(line["speaker"], 80), "text": _public(line["text"], 320)})
        if len(clean_lines) < 2:
            raise ValueError("conversation contained too few valid lines")
        return {"dialogue": clean_lines, "summary": _public(value.get("summary", ""), 320)}
    if kind == "chronicle":
        allowed_ledger_ids = {
            int(item["id"])
            for item in context.get("ledger", [])
            if isinstance(item, dict) and isinstance(item.get("id"), int)
        }
        allowed_slugs = {
            str(item["slug"])
            for item in context.get("residentAllowlist", [])
            if isinstance(item, dict) and item.get("slug")
        }
        ledger_ids = value.get("ledgerIds")
        resident_slugs = value.get("residentSlugs")
        if not isinstance(ledger_ids, list) or any(
            not isinstance(item, int) or item not in allowed_ledger_ids for item in ledger_ids
        ):
            raise ValueError("chronicle referenced an unknown ledger entry")
        if not isinstance(resident_slugs, list) or any(
            not isinstance(item, str) or item not in allowed_slugs for item in resident_slugs
        ):
            raise ValueError("chronicle referenced an unknown resident")
        if len(set(ledger_ids)) != len(ledger_ids) or len(set(resident_slugs)) != len(resident_slugs):
            raise ValueError("chronicle references must be unique")
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
            "ledgerIds": ledger_ids,
            "residentSlugs": resident_slugs,
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
                item = {
                        "slug": slug,
                        "intention": f"{name} will finish one useful task and notice who needs company.",
                        "reflection": f"{name} learned that ordinary routines can still change a relationship.",
                        "publicThought": "I should pay attention to the small choices that shape this place.",
                    }
                if kind == "resident_intent":
                    item.update({"preferredAction": "pursue_purpose", "preferenceTags": ["useful work"]})
                items.append(item)
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
            ledger_ids = [int(item["id"]) for item in context.get("ledger", [])[:5]]
            resident_slugs = sorted(
                {
                    str(slug)
                    for item in context.get("ledger", [])[:5]
                    for slug in item.get("residents", [])
                }
            )
            result = {
                "title": f"Day {day}: Small choices around the Lagoon",
                "narrative": "Residents balanced their routines with the day's catalyst, and several quiet choices changed how neighbours understood one another.",
                "statistics": {"activities": int(context.get("activities", 0))},
                "ledgerIds": ledger_ids,
                "residentSlugs": resident_slugs,
            }
        else:
            result = {
                "headline": "The Lagoon opens another chapter",
                "publicNote": "A familiar morning is beginning to bend around an unfamiliar event.",
            }
        return _validate(kind, result, context), {
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
            "or sexualized minors. For chronicles, use only supplied resident slugs and ledger "
            "IDs; unsupported names, speakers, facts, and statistics are invalid. Context:\n" + serialized
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
            return _validate(str(job["kind"]), value, loads(job["context_json"], {})), usage


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
        recorded_attempt = int(
            connection.execute(
                "SELECT COALESCE(MAX(attempt_number),0) FROM model_usage WHERE job_id=?",
                (job["id"],),
            ).fetchone()[0]
        )
        attempt = max(int(current_job["attempts"]), recorded_attempt) + 1
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


def _finish_usage(
    connection: sqlite3.Connection,
    usage_id: int,
    status: str,
    usage: dict[str, int] | None = None,
    *,
    error_class: str | None = None,
    duration_ms: int | None = None,
) -> None:
    if usage is None:
        connection.execute(
            """
            UPDATE model_usage SET status=?,error_class=?,duration_ms=?,completed_at=?
            WHERE id=?
            """,
            (status, error_class, duration_ms, now_iso(), usage_id),
        )
        return
    connection.execute(
        """
        UPDATE model_usage SET status=?,input_tokens=?,cached_input_tokens=?,
          output_tokens=?,reasoning_tokens=?,total_tokens=?,error_class=NULL,
          duration_ms=?,completed_at=? WHERE id=?
        """,
        (
            status,
            int(usage.get("input_tokens", 0)),
            int(usage.get("cached_input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
            int(usage.get("reasoning_tokens", 0)),
            int(usage.get("total_tokens", 0)),
            duration_ms,
            now_iso(),
            usage_id,
        ),
    )


def _error_class(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ProviderProcessError):
        return "provider_process"
    if isinstance(error, SeasonLocked):
        return "season_locked"
    if isinstance(error, (ValueError, json.JSONDecodeError)):
        return "schema_validation"
    if isinstance(error, RuntimeError) and "tool" in str(error).lower():
        return "tool_violation"
    return "provider_error"


def _circuit_open(
    connection: sqlite3.Connection,
    job: sqlite3.Row,
    model: str,
) -> bool:
    row = connection.execute(
        """
        SELECT status FROM model_circuits
        WHERE season_id=? AND day=? AND job_kind=? AND model=?
        """,
        (job["season_id"], job["day"], job["kind"], model),
    ).fetchone()
    return bool(row and row["status"] == "open")


def _record_circuit_result(
    connection: sqlite3.Connection,
    job: sqlite3.Row,
    model: str,
    *,
    failed: bool,
) -> None:
    row = connection.execute(
        """
        SELECT consecutive_failures FROM model_circuits
        WHERE season_id=? AND day=? AND job_kind=? AND model=?
        """,
        (job["season_id"], job["day"], job["kind"], model),
    ).fetchone()
    failures = int(row["consecutive_failures"]) if row else 0
    failures = failures + 1 if failed else 0
    status = "open" if failures >= 2 else "closed"
    connection.execute(
        """
        INSERT INTO model_circuits(
          season_id,day,job_kind,model,status,consecutive_failures,opened_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(season_id,day,job_kind,model) DO UPDATE SET
          status=excluded.status,consecutive_failures=excluded.consecutive_failures,
          opened_at=CASE WHEN excluded.status='open'
            THEN COALESCE(model_circuits.opened_at,excluded.opened_at) ELSE NULL END,
          updated_at=excluded.updated_at
        """,
        (
            job["season_id"], job["day"], job["kind"], model, status, failures,
            now_iso() if status == "open" else None, now_iso(),
        ),
    )


def process_one(connection: sqlite3.Connection, settings: Settings, provider: Provider) -> bool:
    job = _lease_job(connection)
    if not job:
        return False
    all_attempts = (
        (settings.primary_model, settings.primary_reasoning),
        (settings.fallback_model, settings.fallback_reasoning),
    )
    recorded_attempts = int(
        connection.execute(
            "SELECT COALESCE(MAX(attempt_number),0) FROM model_usage WHERE job_id=?",
            (job["id"],),
        ).fetchone()[0]
    )
    used_attempts = max(int(job["attempts"]), recorded_attempts)
    if used_attempts == 0 and _circuit_open(connection, job, settings.primary_model):
        attempts = (all_attempts[1],)
    else:
        attempts = all_attempts[min(used_attempts, len(all_attempts)):]
    last_error = "provider_failed"
    context = loads(job["context_json"], {})
    residents = context.get("residents") if isinstance(context, dict) else None
    resident = (
        residents[0].get("slug")
        if isinstance(residents, list) and residents and isinstance(residents[0], dict)
        else context.get("residentSlug") if isinstance(context, dict) else None
    )
    correlation = {
        "season": int(job["season_id"]),
        "tick": int(job["tick"]),
        "job": int(job["id"]),
        "resident": resident,
        "kind": str(job["kind"]),
    }
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
        started = time.monotonic()
        try:
            result, usage = provider.complete(job, model, reasoning)
        except Exception as error:
            duration_ms = max(0, round((time.monotonic() - started) * 1000))
            error_class = _error_class(error)
            _finish_usage(
                connection,
                usage_id,
                "failed",
                error_class=error_class,
                duration_ms=duration_ms,
            )
            if model == settings.primary_model:
                _record_circuit_result(connection, job, model, failed=True)
            log_event(
                "inference",
                "model_attempt",
                **correlation,
                model=model,
                status="failed",
                errorClass=error_class,
                elapsedMs=duration_ms,
            )
            last_error = error_class
            continue
        duration_ms = max(0, round((time.monotonic() - started) * 1000))
        _finish_usage(connection, usage_id, "complete", usage, duration_ms=duration_ms)
        if model == settings.primary_model:
            _record_circuit_result(connection, job, model, failed=False)
        connection.execute(
            """
            UPDATE model_jobs SET status='complete',result_json=?,lease_until=NULL,
              error_code=NULL,updated_at=? WHERE id=?
            """,
            (dumps(result), now_iso(), job["id"]),
        )
        connection.commit()
        log_event(
            "inference",
            "model_attempt",
            **correlation,
            model=model,
            status="complete",
            elapsedMs=duration_ms,
        )
        return True
    connection.execute(
        "UPDATE model_jobs SET status='failed',lease_until=NULL,error_code=?,updated_at=? WHERE id=?",
        (last_error, now_iso(), job["id"]),
    )
    connection.execute(
        "UPDATE seasons SET model_degraded=1 WHERE id=?", (job["season_id"],)
    )
    connection.commit()
    log_event(
        "inference",
        "model_job_failed",
        **correlation,
        status="failed",
        errorClass=last_error,
    )
    return True


def run_worker(settings: Settings | None = None, *, once: bool = False) -> int:
    configure_logging()
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
