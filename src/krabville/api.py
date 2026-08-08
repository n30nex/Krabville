from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Cookie, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .db import connect, dumps, initialize, loads, now_iso, transaction
from .security import VoteSecurity, new_csrf


class VoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choiceId: str = Field(min_length=1, max_length=8, pattern=r"^[A-Z0-9_-]+$")
    csrfToken: str = Field(min_length=20, max_length=128)


def _season(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()


def _usage(
    connection: sqlite3.Connection,
    season_id: int,
    settings: Settings,
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COUNT(*) calls,COALESCE(SUM(total_tokens),0) total,
          COALESCE(SUM(input_tokens),0) input,COALESCE(SUM(cached_input_tokens),0) cached,
          COALESCE(SUM(output_tokens),0) output,COALESCE(SUM(reasoning_tokens),0) reasoning
        FROM model_usage WHERE season_id=?
        """,
        (season_id,),
    ).fetchone()
    models = {
        item["model"]: {"calls": int(item["calls"]), "tokens": int(item["tokens"])}
        for item in connection.execute(
            "SELECT model,COUNT(*) calls,COALESCE(SUM(total_tokens),0) tokens FROM model_usage WHERE season_id=? GROUP BY model",
            (season_id,),
        )
    }
    return {
        "calls": int(row["calls"]),
        "callLimit": settings.call_limit,
        "totalTokens": int(row["total"]),
        "tokenGuard": settings.token_guard,
        "inputTokens": int(row["input"]),
        "cachedInputTokens": int(row["cached"]),
        "outputTokens": int(row["output"]),
        "reasoningTokens": int(row["reasoning"]),
        "models": models,
    }


def _poll_payload(connection: sqlite3.Connection, season_id: int) -> dict[str, Any] | None:
    poll = connection.execute(
        "SELECT * FROM polls WHERE season_id=? ORDER BY day DESC LIMIT 1", (season_id,)
    ).fetchone()
    if not poll:
        return None
    options = [
        {
            "choiceId": row["choice_id"],
            "title": row["title"],
            "category": row["category"],
            "preview": row["preview"],
            "votes": int(row["votes"]),
            "winner": int(row["id"]) == int(poll["winner_option_id"] or 0),
        }
        for row in connection.execute(
            "SELECT * FROM poll_options WHERE poll_id=? ORDER BY choice_id", (poll["id"],)
        )
    ]
    return {
        "id": int(poll["id"]),
        "day": int(poll["day"]),
        "status": poll["status"],
        "opensTick": int(poll["opens_tick"]),
        "closesTick": int(poll["closes_tick"]),
        "options": options,
    }


def _state(connection: sqlite3.Connection, settings: Settings) -> dict[str, Any]:
    season = _season(connection)
    if not season:
        return {
            "schemaVersion": 2,
            "ok": True,
            "season": None,
            "models": {
                "primary": settings.primary_model,
                "primaryReasoning": "low",
                "fallback": settings.fallback_model,
                "fallbackReasoning": "high",
            },
            "currentEvent": None,
            "residents": [],
            "poll": None,
            "usage": {
                "calls": 0,
                "callLimit": settings.call_limit,
                "totalTokens": 0,
                "tokenGuard": settings.token_guard,
                "inputTokens": 0,
                "cachedInputTokens": 0,
                "outputTokens": 0,
                "reasoningTokens": 0,
                "models": {},
            },
            "events": [],
            "conversations": [],
            "goals": [],
            "props": [],
            "chronicles": [],
            "report": None,
            "updatedAt": now_iso(),
        }
    season_id = int(season["id"])
    residents = []
    for row in connection.execute(
        """
        SELECT r.*,s.x,s.y,s.destination_x,s.destination_y,s.location,s.activity,
          s.public_thought,s.intention,s.reflection,s.mood,s.needs_json,s.path_json,s.updated_tick
        FROM residents r JOIN resident_state s ON s.resident_id=r.id
        WHERE s.season_id=? ORDER BY r.id
        """,
        (season_id,),
    ):
        residents.append(
            {
                "slug": row["slug"],
                "name": row["name"],
                "role": row["role"],
                "routine": row["routine"],
                "about": row["about"],
                "home": row["home"],
                "workplace": row["workplace"],
                "color": row["color"],
                "traits": loads(row["traits_json"], {}),
                "possessions": loads(row["possessions_json"], []),
                "x": float(row["x"]),
                "y": float(row["y"]),
                "destinationX": float(row["destination_x"]),
                "destinationY": float(row["destination_y"]),
                "location": row["location"],
                "activity": row["activity"],
                "publicThought": row["public_thought"],
                "intention": row["intention"],
                "reflection": row["reflection"],
                "mood": row["mood"],
                "needs": loads(row["needs_json"], {}),
                "path": loads(row["path_json"], []),
                "updatedTick": int(row["updated_tick"]),
            }
        )
    recent = [
        {
            "seq": int(row["seq"]),
            "tick": int(row["tick"]),
            "type": row["event_type"],
            "payload": loads(row["payload_json"], {}),
            "createdAt": row["created_at"],
        }
        for row in connection.execute(
            "SELECT * FROM event_stream WHERE season_id=? ORDER BY seq DESC LIMIT 60", (season_id,)
        )
    ][::-1]
    report = connection.execute("SELECT * FROM reports WHERE season_id=?", (season_id,)).fetchone()
    current_event = connection.execute(
        "SELECT * FROM town_events WHERE season_id=? ORDER BY day DESC,id DESC LIMIT 1", (season_id,)
    ).fetchone()
    conversations = [
        {
            "tick": int(row["tick"]),
            "residentA": row["a_slug"],
            "residentAName": row["a_name"],
            "residentB": row["b_slug"],
            "residentBName": row["b_name"],
            "location": row["location"],
            "dialogue": loads(row["dialogue_json"], []),
            "summary": row["summary"],
        }
        for row in connection.execute(
            """
            SELECT c.*,a.slug a_slug,a.name a_name,b.slug b_slug,b.name b_name
            FROM conversations c JOIN residents a ON a.id=c.resident_a
            JOIN residents b ON b.id=c.resident_b
            WHERE c.season_id=? ORDER BY c.id DESC LIMIT 12
            """,
            (season_id,),
        )
    ][::-1]
    goals = [
        {
            "resident": row["slug"],
            "residentName": row["name"],
            "scope": row["scope"],
            "description": row["description"],
            "status": row["status"],
            "progress": int(row["progress"]),
        }
        for row in connection.execute(
            """
            SELECT g.*,r.slug,r.name FROM goals g JOIN residents r ON r.id=g.resident_id
            WHERE g.season_id=? ORDER BY g.status,g.scope,g.id LIMIT 36
            """,
            (season_id,),
        )
    ]
    props = [
        {
            "location": row["location"],
            "prop": row["prop"],
            "status": row["status"],
            "createdTick": int(row["created_tick"]),
        }
        for row in connection.execute(
            "SELECT * FROM world_props WHERE season_id=? AND status='present' ORDER BY id",
            (season_id,),
        )
    ]
    chronicles = [
        {"day": int(row["day"]), "title": row["title"], "narrative": row["narrative"]}
        for row in connection.execute(
            "SELECT day,title,narrative FROM daily_chronicles WHERE season_id=? ORDER BY day",
            (season_id,),
        )
    ]
    complete = season["status"] == "complete"
    return {
        "schemaVersion": 2,
        "ok": True,
        "season": {
            "id": season_id,
            "number": int(season["number"]),
            "status": season["status"],
            "tick": int(season["current_tick"]),
            "targetTicks": int(season["target_ticks"]),
            "day": int(season["current_day"]),
            "worldMinutes": int(season["world_minutes"]),
            "progressPercent": 100.0 if complete else round(
                100 * int(season["current_tick"]) / max(1, int(season["target_ticks"])), 2
            ),
            "seedCommitment": season["seed_commitment"],
            "revealedSeed": season["seed_hex"] if season["seed_revealed"] else None,
            "modelLocked": bool(season["model_locked"]),
            "modelDegraded": bool(season["model_degraded"]),
            "weather": loads(season["weather_json"], {}),
            "startedAt": season["started_at"],
            "completedAt": season["completed_at"],
            "completionReason": season["completion_reason"],
        },
        "models": {
            "primary": settings.primary_model,
            "primaryReasoning": "low",
            "fallback": settings.fallback_model,
            "fallbackReasoning": "high",
        },
        "currentEvent": (
            {
                "day": int(current_event["day"]),
                "slug": current_event["slug"],
                "title": current_event["title"],
                "category": current_event["category"],
                "summary": current_event["summary"],
                "prop": current_event["prop"],
                "strange": bool(current_event["strange"]),
                "participants": loads(current_event["participants_json"], []),
            }
            if current_event else None
        ),
        "residents": residents,
        "poll": _poll_payload(connection, season_id),
        "usage": _usage(connection, season_id, settings),
        "events": recent,
        "conversations": conversations,
        "goals": goals,
        "props": props,
        "chronicles": chronicles,
        "report": (
            {
                "headline": report["headline"],
                "narrative": report["narrative"],
                "poster": f"/reports/season-{int(season['number']):03d}.png",
                "statistics": loads(report["statistics_json"], {}),
            }
            if report else None
        ),
        "updatedAt": now_iso(),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    bootstrap = initialize(settings)
    bootstrap.close()
    security = VoteSecurity(settings.voter_secret)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        yield

    app = FastAPI(title="Krabville Public API", version="2.0.0", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["krab.canadaverse.org", "127.0.0.1", "localhost", "testserver"],
    )

    @app.middleware("http")
    async def harden(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Robots-Tag"] = "noindex, noarchive"
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        if not security.voter_key(request.cookies.get("kv_voter")):
            response.set_cookie("kv_voter", security.new_voter_cookie(), httponly=True, secure=secure, samesite="lax", max_age=7776000)
        if not request.cookies.get("kv_csrf"):
            response.set_cookie("kv_csrf", new_csrf(), httponly=False, secure=secure, samesite="lax", max_age=86400)
        return response

    @app.get("/healthz")
    def healthz():
        connection = connect(settings.database_path, readonly=True)
        try:
            quick = connection.execute("PRAGMA quick_check").fetchone()[0]
            season = _season(connection)
            season_payload = (
                {
                    "number": int(season["number"]),
                    "status": season["status"],
                    "day": int(season["current_day"]),
                    "progressPercent": round(
                        (int(season["current_tick"]) / int(season["target_ticks"])) * 100,
                        2,
                    ),
                    "modelLocked": bool(season["model_locked"]),
                    "modelDegraded": bool(season["model_degraded"]),
                }
                if season
                else None
            )
            return {
                "ok": quick == "ok",
                "database": quick,
                "seasonStatus": season["status"] if season else "draft",
                "season": season_payload,
                "models": {
                    "primary": settings.primary_model,
                    "primaryReasoning": "low",
                    "fallback": settings.fallback_model,
                    "fallbackReasoning": "high",
                },
                "usage": _usage(connection, int(season["id"]), settings) if season else None,
                "residentCount": int(connection.execute("SELECT COUNT(*) FROM residents").fetchone()[0]),
                "updatedAt": now_iso(),
            }
        finally:
            connection.close()

    @app.get("/readyz")
    def readyz():
        return healthz()

    @app.get("/api/v2/state")
    def state():
        connection = connect(settings.database_path, readonly=True)
        try:
            return _state(connection, settings)
        finally:
            connection.close()

    @app.get("/api/krabville/state")
    def compatibility_state():
        value = state()
        season = value.get("season") or {}
        return {
            "ok": value["ok"],
            "simulation": "krabville-v2",
            "step": season.get("tick", 0),
            "run": {
                "status": season.get("status", "draft"),
                "current_step": season.get("tick", 0),
                "target_step": season.get("targetTicks", 2016),
                "run_progress_percent": season.get("progressPercent", 0),
                "day": season.get("day", 0),
                "residents": len(value.get("residents", [])),
            },
            "residents": value.get("residents", []),
            "world": {"weather": season.get("weather"), "today_event": value.get("currentEvent"), "week_report": value.get("report")},
            "tokens": value.get("usage", {}),
        }

    @app.get("/api/v2/events")
    def events(after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            if not season:
                return {"events": [], "next": after}
            rows = list(
                connection.execute(
                    "SELECT * FROM event_stream WHERE season_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (season["id"], after, limit),
                )
            )
            items = [{"seq": int(row["seq"]), "tick": int(row["tick"]), "type": row["event_type"], "payload": loads(row["payload_json"], {}), "createdAt": row["created_at"]} for row in rows]
            return {"events": items, "next": items[-1]["seq"] if items else after}
        finally:
            connection.close()

    @app.get("/api/v2/events/stream")
    async def event_stream(request: Request, last_event_id: str | None = Header(None, alias="Last-Event-ID")):
        start = int(last_event_id or request.query_params.get("after") or 0)

        async def stream():
            cursor = start
            while not await request.is_disconnected():
                connection = connect(settings.database_path, readonly=True)
                try:
                    season = _season(connection)
                    rows = list(
                        connection.execute(
                            "SELECT * FROM event_stream WHERE season_id=? AND seq>? ORDER BY seq LIMIT 100",
                            (season["id"], cursor),
                        ) if season else []
                    )
                finally:
                    connection.close()
                if rows:
                    for row in rows:
                        cursor = int(row["seq"])
                        data = json.dumps({"tick": int(row["tick"]), "payload": loads(row["payload_json"], {}), "createdAt": row["created_at"]}, separators=(",", ":"))
                        yield f"id: {cursor}\nevent: {row['event_type']}\ndata: {data}\n\n"
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.get("/api/v2/residents/{slug}")
    def resident(slug: str):
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            if not season:
                raise HTTPException(404, "season not found")
            row = connection.execute(
                """
                SELECT r.*,s.* FROM residents r JOIN resident_state s ON s.resident_id=r.id
                WHERE r.slug=? AND s.season_id=?
                """,
                (slug, season["id"]),
            ).fetchone()
            if not row:
                raise HTTPException(404, "resident not found")
            goals = [dict(item) for item in connection.execute("SELECT scope,description,status,progress FROM goals WHERE season_id=? AND resident_id=? ORDER BY id DESC LIMIT 12", (season["id"], row["resident_id"]))]
            memories = [dict(item) for item in connection.execute("SELECT kind,content,tags,valence,salience,location,created_tick FROM memories WHERE season_id=? AND resident_id=? ORDER BY created_tick DESC,id DESC LIMIT 20", (season["id"], row["resident_id"]))]
            relationships = [dict(item) for item in connection.execute("""
                SELECT CASE WHEN rel.resident_a=? THEN b.slug ELSE a.slug END otherSlug,
                  CASE WHEN rel.resident_a=? THEN b.name ELSE a.name END otherName,
                  rel.affinity,rel.trust,rel.tension,rel.familiarity,rel.interactions
                FROM relationships rel JOIN residents a ON a.id=rel.resident_a JOIN residents b ON b.id=rel.resident_b
                WHERE rel.season_id=? AND (rel.resident_a=? OR rel.resident_b=?)
                ORDER BY (rel.affinity+rel.trust-rel.tension) DESC
                """, (row["resident_id"], row["resident_id"], season["id"], row["resident_id"], row["resident_id"]))]
            return {
                "slug": row["slug"], "name": row["name"], "role": row["role"], "home": row["home"], "workplace": row["workplace"],
                "color": row["color"], "x": float(row["x"]), "y": float(row["y"]),
                "destinationX": float(row["destination_x"]), "destinationY": float(row["destination_y"]),
                "path": loads(row["path_json"], []),
                "routine": row["routine"], "about": row["about"],
                "activity": row["activity"], "location": row["location"], "publicThought": row["public_thought"], "intention": row["intention"], "reflection": row["reflection"], "mood": row["mood"],
                "needs": loads(row["needs_json"], {}), "traits": loads(row["traits_json"], {}), "possessions": loads(row["possessions_json"], []),
                "goals": goals, "memories": memories, "relationships": relationships,
            }
        finally:
            connection.close()

    @app.get("/api/v2/relationships")
    def relationships():
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            if not season:
                return {"relationships": []}
            rows = connection.execute("""
                SELECT a.slug aSlug,a.name aName,b.slug bSlug,b.name bName,
                  r.affinity,r.trust,r.tension,r.familiarity,r.interactions,r.last_interaction_tick lastInteractionTick
                FROM relationships r JOIN residents a ON a.id=r.resident_a JOIN residents b ON b.id=r.resident_b
                WHERE r.season_id=? ORDER BY (r.affinity+r.trust-r.tension) DESC
                """, (season["id"],))
            return {"relationships": [dict(row) for row in rows]}
        finally:
            connection.close()

    @app.get("/api/v2/polls/current")
    def current_poll():
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            return {"poll": _poll_payload(connection, int(season["id"])) if season else None}
        finally:
            connection.close()

    @app.post("/api/v2/polls/{poll_id}/vote")
    def vote(poll_id: int, body: VoteRequest, request: Request, kv_voter: str | None = Cookie(None), kv_csrf: str | None = Cookie(None)):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in {settings.public_origin.rstrip("/"), "http://127.0.0.1:18889", "http://127.0.0.1:18890", "http://testserver"}:
            raise HTTPException(403, "origin rejected")
        if not kv_csrf or not secrets_compare(kv_csrf, body.csrfToken):
            raise HTTPException(403, "csrf rejected")
        voter_key = security.voter_key(kv_voter)
        if not voter_key:
            raise HTTPException(401, "voter cookie required")
        address = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
        network_key = security.network_key(address)
        if not security.check_rate(network_key):
            raise HTTPException(429, "vote rate limit reached")
        connection = connect(settings.database_path)
        try:
            with transaction(connection, immediate=True):
                poll = connection.execute("SELECT * FROM polls WHERE id=?", (poll_id,)).fetchone()
                if not poll or poll["status"] != "open":
                    raise HTTPException(409, "poll is not open")
                option = connection.execute("SELECT * FROM poll_options WHERE poll_id=? AND choice_id=?", (poll_id, body.choiceId)).fetchone()
                if not option:
                    raise HTTPException(422, "invalid choice")
                connection.execute("""
                    INSERT INTO votes(poll_id,voter_key,network_key,option_id,updated_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(poll_id,voter_key) DO UPDATE SET
                      network_key=excluded.network_key,option_id=excluded.option_id,updated_at=excluded.updated_at
                    """, (poll_id, voter_key, network_key, option["id"], now_iso()))
                connection.execute("""
                    UPDATE poll_options SET votes=(SELECT COUNT(*) FROM votes WHERE votes.option_id=poll_options.id)
                    WHERE poll_id=?
                    """, (poll_id,))
            return {"ok": True, "poll": _poll_payload(connection, int(poll["season_id"]))}
        finally:
            connection.close()

    @app.get("/api/v2/seasons")
    def seasons():
        connection = connect(settings.database_path, readonly=True)
        try:
            rows = connection.execute("SELECT id,number,status,created_at,started_at,completed_at,seed_commitment,seed_hex,seed_revealed,current_tick,target_ticks FROM seasons ORDER BY number DESC LIMIT 104")
            return {"seasons": [{"id": row["id"], "number": row["number"], "status": row["status"], "createdAt": row["created_at"], "startedAt": row["started_at"], "completedAt": row["completed_at"], "seedCommitment": row["seed_commitment"], "revealedSeed": row["seed_hex"] if row["seed_revealed"] else None, "progressPercent": round(100 * row["current_tick"] / max(1, row["target_ticks"]), 2)} for row in rows]}
        finally:
            connection.close()

    @app.get("/api/v2/seasons/{season_id}")
    def season_detail(season_id: int):
        connection = connect(settings.database_path, readonly=True)
        try:
            season = connection.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
            if not season:
                raise HTTPException(404, "season not found")
            chronicles = [dict(row) for row in connection.execute("SELECT day,title,narrative,statistics_json FROM daily_chronicles WHERE season_id=? ORDER BY day", (season_id,))]
            report = connection.execute("SELECT * FROM reports WHERE season_id=?", (season_id,)).fetchone()
            public_season = {
                "id": int(season["id"]),
                "number": int(season["number"]),
                "status": season["status"],
                "createdAt": season["created_at"],
                "startedAt": season["started_at"],
                "completedAt": season["completed_at"],
                "seedCommitment": season["seed_commitment"],
                "revealedSeed": season["seed_hex"] if season["seed_revealed"] else None,
                "currentTick": int(season["current_tick"]),
                "targetTicks": int(season["target_ticks"]),
                "completionReason": season["completion_reason"],
                "weather": loads(season["weather_json"], {}),
            }
            public_chronicles = []
            for row in chronicles:
                statistics = loads(row.pop("statistics_json"), {})
                public_chronicles.append({**row, "statistics": statistics})
            public_report = None
            if report:
                public_report = {
                    "headline": report["headline"],
                    "narrative": report["narrative"],
                    "poster": f"/reports/season-{int(season['number']):03d}.png",
                    "statistics": loads(report["statistics_json"], {}),
                    "createdAt": report["created_at"],
                }
            return {
                "season": public_season,
                "chronicles": public_chronicles,
                "report": public_report,
            }
        finally:
            connection.close()

    @app.get("/reports/{filename}")
    def report_file(filename: str):
        if not re_report_name(filename):
            raise HTTPException(404, "report not found")
        path = settings.report_dir / filename
        if not path.exists():
            raise HTTPException(404, "report not found")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public,max-age=3600"})

    if settings.frontend_dir.exists():
        asset_path = settings.frontend_dir / "assets"
        if asset_path.exists():
            app.mount("/assets", StaticFiles(directory=asset_path), name="assets")

        @app.get("/{path:path}", response_class=HTMLResponse)
        def frontend(path: str):
            candidate = (settings.frontend_dir / path).resolve()
            if path and candidate.is_file() and settings.frontend_dir in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(settings.frontend_dir / "index.html")

    return app


def secrets_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a, b)


def re_report_name(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"season-\d{3}\.png", value))


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.port, workers=1, proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
