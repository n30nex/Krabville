from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .config import Settings
from .db import dumps, loads, now_iso


WIDTH = 1920
HEIGHT = 1080
STAGE_ORDER = ("unborn", "baby", "child", "teen", "adult", "senior", "deceased", "departed")


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _wrapped(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int
) -> list[str]:
    words = " ".join(str(text).split()).split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int
) -> str:
    value = " ".join(str(text).split())
    if draw.textlength(value, font=font) <= width:
        return value
    while value and draw.textlength(f"{value}...", font=font) > width:
        value = value[:-1]
    return f"{value.rstrip()}..." if value else ""


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _scalar(
    connection: sqlite3.Connection,
    query: str,
    parameters: tuple[Any, ...] = (),
) -> int:
    row = connection.execute(query, parameters).fetchone()
    return int((row[0] if row else 0) or 0)


def _relationships(connection: sqlite3.Connection, season_id: int) -> dict[str, Any]:
    extra = {
        name
        for name in ("attraction", "affection", "respect", "commitment", "resentment")
        if name in _columns(connection, "relationships")
    }
    rows = list(
        connection.execute(
            """
            SELECT ra.name a,rb.name b,r.*
            FROM relationships r
            JOIN residents ra ON ra.id=r.resident_a
            JOIN residents rb ON rb.id=r.resident_b
            WHERE r.season_id=?
            """,
            (season_id,),
        )
    )
    if not rows:
        return {
            "strongestBond": None,
            "highestTension": None,
            "averageAffinity": 0,
            "averageTrust": 0,
            "averageTension": 0,
        }

    def item(row: sqlite3.Row) -> dict[str, Any]:
        result = {
            "a": str(row["a"]),
            "b": str(row["b"]),
            "affinity": int(row["affinity"]),
            "trust": int(row["trust"]),
            "tension": int(row["tension"]),
            "interactions": int(row["interactions"]),
        }
        result.update({name: int(row[name]) for name in extra})
        return result

    items = [item(row) for row in rows]

    def bond_score(value: dict[str, Any]) -> int:
        return (
            value["affinity"]
            + value["trust"]
            + value.get("affection", 0)
            + value.get("respect", 0)
            + value.get("commitment", 0)
            - value["tension"]
            - value.get("resentment", 0)
        )

    def conflict_score(value: dict[str, Any]) -> int:
        return value["tension"] + value.get("resentment", 0) - value["trust"] // 2

    return {
        "strongestBond": max(items, key=lambda value: (bond_score(value), value["interactions"])),
        "highestTension": max(items, key=lambda value: (conflict_score(value), value["interactions"])),
        "averageAffinity": round(sum(value["affinity"] for value in items) / len(items)),
        "averageTrust": round(sum(value["trust"] for value in items) / len(items)),
        "averageTension": round(sum(value["tension"] for value in items) / len(items)),
    }


def _voting(connection: sqlite3.Connection, season_id: int) -> dict[str, Any]:
    winners = [
        {
            "day": int(row["day"]) + 1,
            "title": str(row["title"]),
            "category": str(row["category"]),
            "votes": int(row["votes"]),
        }
        for row in connection.execute(
            """
            SELECT p.day,o.title,o.category,o.votes
            FROM polls p JOIN poll_options o ON o.id=p.winner_option_id
            WHERE p.season_id=? ORDER BY p.day
            """,
            (season_id,),
        )
    ]
    option_votes = _scalar(
        connection,
        """
        SELECT COALESCE(SUM(o.votes),0) FROM poll_options o
        JOIN polls p ON p.id=o.poll_id WHERE p.season_id=?
        """,
        (season_id,),
    )
    cast_votes = _scalar(
        connection,
        "SELECT COUNT(*) FROM votes v JOIN polls p ON p.id=v.poll_id WHERE p.season_id=?",
        (season_id,),
    )
    return {
        "polls": _scalar(connection, "SELECT COUNT(*) FROM polls WHERE season_id=?", (season_id,)),
        "votes": max(option_votes, cast_votes),
        "winners": winners,
    }


def _lifecycle(connection: sqlite3.Connection, season_id: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "stages": {},
        "living": 0,
        "births": 0,
        "deaths": 0,
        "activeCare": 0,
        "uncoveredCare": 0,
        "averageStress": 0,
        "criticalNeeds": [],
    }
    if not _table_exists(connection, "resident_lifecycle"):
        return result
    result["available"] = True
    if _table_exists(connection, "resident_season_state"):
        stage_rows = list(
            connection.execute(
                """
                SELECT life_stage,COUNT(*) count FROM resident_season_state
                WHERE season_id=? GROUP BY life_stage
                """,
                (season_id,),
            )
        )
        if stage_rows:
            result["stages"] = {str(row["life_stage"]): int(row["count"]) for row in stage_rows}
            result["averageStress"] = round(
                connection.execute(
                    "SELECT COALESCE(AVG(stress),0) FROM resident_season_state WHERE season_id=?",
                    (season_id,),
                ).fetchone()[0]
                or 0
            )
            result["uncoveredCare"] = _scalar(
                connection,
                """
                SELECT COUNT(*) FROM resident_season_state
                WHERE season_id=? AND care_state='uncovered'
                """,
                (season_id,),
            )
    if not result["stages"]:
        result["stages"] = {
            str(row["current_stage"]): int(row["count"])
            for row in connection.execute(
                """
                SELECT current_stage,COUNT(*) count FROM resident_lifecycle
                GROUP BY current_stage
                """
            )
        }
    result["living"] = sum(
        count
        for stage, count in result["stages"].items()
        if stage not in {"deceased", "departed", "unborn"}
    )
    result["births"] = _scalar(
        connection,
        "SELECT COUNT(*) FROM resident_lifecycle WHERE birth_season_id=?",
        (season_id,),
    )
    result["deaths"] = _scalar(
        connection,
        "SELECT COUNT(*) FROM resident_lifecycle WHERE death_season_id=?",
        (season_id,),
    )
    if _table_exists(connection, "childcare_arrangements"):
        result["activeCare"] = _scalar(
            connection,
            """
            SELECT COUNT(*) FROM childcare_arrangements
            WHERE status='active' AND (started_season_id IS NULL OR started_season_id<=?)
              AND (ended_season_id IS NULL OR ended_season_id>?)
            """,
            (season_id, season_id),
        )
    if _table_exists(connection, "resident_needs"):
        result["criticalNeeds"] = [
            {"need": str(row["need_key"]), "average": round(float(row["average"]), 1)}
            for row in connection.execute(
                """
                SELECT need_key,AVG(satisfaction) average FROM resident_needs
                WHERE season_id=? GROUP BY need_key ORDER BY average ASC,need_key LIMIT 3
                """,
                (season_id,),
            )
        ]
    return result


def _economy(connection: sqlite3.Connection, season_id: int, season_number: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "available": False,
        "accountBalanceCents": 0,
        "assetsCents": 0,
        "investmentsCents": 0,
        "debtCents": 0,
        "postedTransactions": 0,
        "moneyMovedCents": 0,
        "topCategory": None,
    }
    required = {"financial_accounts", "financial_transactions", "transaction_entries"}
    if not all(_table_exists(connection, table) for table in required):
        return result
    result["available"] = True
    result["accountBalanceCents"] = _scalar(
        connection,
        """
        SELECT COALESCE(SUM(
          a.opening_balance_cents + COALESCE((
            SELECT SUM(e.amount_cents) FROM transaction_entries e
            JOIN financial_transactions t ON t.id=e.transaction_id
            JOIN seasons ts ON ts.id=t.season_id
            WHERE e.account_id=a.id AND t.status='posted' AND ts.number<=?
          ),0)
        ),0)
        FROM financial_accounts a
        LEFT JOIN seasons opened ON opened.id=a.opened_season_id
        WHERE opened.number IS NULL OR opened.number<=?
        """,
        (season_number, season_number),
    )
    result["postedTransactions"] = _scalar(
        connection,
        "SELECT COUNT(*) FROM financial_transactions WHERE season_id=? AND status='posted'",
        (season_id,),
    )
    result["moneyMovedCents"] = round(
        _scalar(
            connection,
            """
            SELECT COALESCE(SUM(ABS(e.amount_cents)),0) FROM transaction_entries e
            JOIN financial_transactions t ON t.id=e.transaction_id
            WHERE t.season_id=? AND t.status='posted'
            """,
            (season_id,),
        )
        / 2
    )
    category = connection.execute(
        """
        SELECT category,COUNT(*) count FROM financial_transactions
        WHERE season_id=? AND status='posted'
        GROUP BY category ORDER BY count DESC,category LIMIT 1
        """,
        (season_id,),
    ).fetchone()
    result["topCategory"] = str(category["category"]) if category else None
    if _table_exists(connection, "assets"):
        result["assetsCents"] = _scalar(
            connection,
            """
            SELECT COALESCE(SUM(a.value_cents),0) FROM assets a
            LEFT JOIN seasons acquired ON acquired.id=a.acquired_season_id
            LEFT JOIN seasons disposed ON disposed.id=a.disposed_season_id
            WHERE (acquired.number IS NULL OR acquired.number<=?)
              AND (disposed.number IS NULL OR disposed.number>?)
            """,
            (season_number, season_number),
        )
    if _table_exists(connection, "investments"):
        result["investmentsCents"] = _scalar(
            connection,
            """
            SELECT COALESCE(SUM(i.market_value_cents),0) FROM investments i
            LEFT JOIN seasons acquired ON acquired.id=i.acquired_season_id
            WHERE acquired.number IS NULL OR acquired.number<=?
            """,
            (season_number,),
        )
    if _table_exists(connection, "debts"):
        result["debtCents"] = _scalar(
            connection,
            """
            SELECT COALESCE(SUM(d.outstanding_cents),0) FROM debts d
            LEFT JOIN seasons opened ON opened.id=d.opened_season_id
            WHERE d.status IN ('current','late','defaulted')
              AND (opened.number IS NULL OR opened.number<=?)
            """,
            (season_number,),
        )
    return result


def _drama_and_ledger(connection: sqlite3.Connection, season_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    drama: dict[str, Any] = {
        "available": False,
        "lifeEvents": 0,
        "permanentEvents": 0,
        "highSeverityEvents": 0,
        "secrets": 0,
        "revealedSecrets": 0,
        "highlights": [],
    }
    ledger: dict[str, Any] = {
        "available": False,
        "entries": 0,
        "omniscientEntries": 0,
        "highlights": [],
    }
    if _table_exists(connection, "life_events"):
        drama["available"] = True
        drama["lifeEvents"] = _scalar(
            connection, "SELECT COUNT(*) FROM life_events WHERE season_id=?", (season_id,)
        )
        drama["permanentEvents"] = _scalar(
            connection,
            "SELECT COUNT(*) FROM life_events WHERE season_id=? AND permanent=1",
            (season_id,),
        )
        drama["highSeverityEvents"] = _scalar(
            connection,
            "SELECT COUNT(*) FROM life_events WHERE season_id=? AND severity>=70",
            (season_id,),
        )
        drama["highlights"] = [
            {
                "title": str(row["title"]),
                "summary": str(row["summary"]),
                "severity": int(row["severity"]),
                "permanent": bool(row["permanent"]),
                "type": str(row["event_type"]),
            }
            for row in connection.execute(
                """
                SELECT title,summary,severity,permanent,event_type FROM life_events
                WHERE season_id=? ORDER BY severity DESC,permanent DESC,tick DESC LIMIT 4
                """,
                (season_id,),
            )
        ]
    if _table_exists(connection, "secrets") and _table_exists(connection, "facts"):
        drama["secrets"] = _scalar(
            connection,
            """
            SELECT COUNT(*) FROM secrets s JOIN facts f ON f.id=s.fact_id
            WHERE f.season_id=?
            """,
            (season_id,),
        )
        drama["revealedSecrets"] = _scalar(
            connection,
            """
            SELECT COUNT(*) FROM secrets s JOIN facts f ON f.id=s.fact_id
            WHERE f.season_id=? AND s.status IN ('partially_revealed','public')
            """,
            (season_id,),
        )
    if _table_exists(connection, "story_ledger"):
        ledger["available"] = True
        ledger["entries"] = _scalar(
            connection, "SELECT COUNT(*) FROM story_ledger WHERE season_id=?", (season_id,)
        )
        ledger["omniscientEntries"] = _scalar(
            connection,
            "SELECT COUNT(*) FROM story_ledger WHERE season_id=? AND visibility='omniscient'",
            (season_id,),
        )
        ledger["highlights"] = [
            {
                "day": int(row["day"]) + 1,
                "headline": str(row["headline"]),
                "summary": str(row["summary"]),
                "significance": int(row["significance"]),
                "type": str(row["entry_type"]),
            }
            for row in connection.execute(
                """
                SELECT day,headline,summary,significance,entry_type FROM story_ledger
                WHERE season_id=? ORDER BY significance DESC,tick DESC LIMIT 5
                """,
                (season_id,),
            )
        ]
    return drama, ledger


def _stats(connection: sqlite3.Connection, season_id: int) -> dict[str, Any]:
    season_number = _scalar(connection, "SELECT number FROM seasons WHERE id=?", (season_id,))
    residents = _scalar(
        connection,
        "SELECT COUNT(DISTINCT resident_id) FROM resident_state WHERE season_id=?",
        (season_id,),
    ) or _scalar(connection, "SELECT COUNT(*) FROM residents")
    relationships = _relationships(connection, season_id)
    drama, ledger = _drama_and_ledger(connection, season_id)
    return {
        "residents": residents,
        "activities": _scalar(connection, "SELECT COUNT(*) FROM activities WHERE season_id=?", (season_id,)),
        "conversations": _scalar(
            connection, "SELECT COUNT(*) FROM conversations WHERE season_id=?", (season_id,)
        ),
        "strangeDays": _scalar(
            connection,
            "SELECT COUNT(*) FROM town_events WHERE season_id=? AND strange=1",
            (season_id,),
        ),
        "modelAttempts": _scalar(
            connection, "SELECT COUNT(*) FROM model_usage WHERE season_id=?", (season_id,)
        ),
        "modelTokens": _scalar(
            connection,
            "SELECT COALESCE(SUM(total_tokens),0) FROM model_usage WHERE season_id=?",
            (season_id,),
        ),
        "strongestBond": relationships["strongestBond"],
        "lifecycle": _lifecycle(connection, season_id),
        "economy": _economy(connection, season_id, season_number),
        "drama": drama,
        "relationships": relationships,
        "voting": _voting(connection, season_id),
        "ledger": ledger,
    }


def _money(cents: int) -> str:
    dollars = cents / 100
    sign = "-" if dollars < 0 else ""
    value = abs(dollars)
    if value >= 1_000_000:
        return f"{sign}${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{sign}${value / 1_000:.1f}K"
    return f"{sign}${value:,.0f}"


def _panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    title: str,
    subtitle: str = "",
) -> tuple[int, int, int]:
    left, top, right, bottom = box
    draw.rounded_rectangle(
        box,
        radius=18,
        fill=(10, 34, 49, 238),
        outline=(101, 202, 215, 58),
        width=2,
    )
    draw.text((left + 22, top + 17), title.upper(), font=_font(18, bold=True), fill="#69d7e5")
    if subtitle:
        draw.text(
            (right - 22, top + 18),
            subtitle,
            font=_font(16),
            fill="#8ea8b7",
            anchor="ra",
        )
    return left + 22, top + 52, right - left - 44


def _metric(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    value: str,
    label: str,
    width: int,
    *,
    color: str = "#ffffff",
) -> None:
    draw.text((x, y), _fit(draw, value, _font(28, bold=True), width), font=_font(28, bold=True), fill=color)
    draw.text((x, y + 38), label.upper(), font=_font(14, bold=True), fill="#8ea8b7")


def _headline(season: sqlite3.Row, statistics: dict[str, Any], events: list[sqlite3.Row]) -> str:
    prefix = f"Season {season['number']} in focus: "
    ledger = statistics["ledger"]["highlights"]
    if ledger:
        return prefix + str(ledger[0]["headline"]).strip().rstrip(".!?")
    drama = statistics["drama"]["highlights"]
    if drama:
        return prefix + str(drama[0]["title"]).strip().rstrip(".!?")
    strange = [str(event["title"]) for event in events if event["strange"]]
    if strange:
        return prefix + strange[0].strip().rstrip(".!?")
    return "Seven days of work, weather, choices, and unexpected company"


def _recorded_weather(
    connection: sqlite3.Connection,
    season_id: int,
    day: int,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT state_json FROM snapshots
        WHERE season_id=? AND tick>=? AND tick<?
        ORDER BY tick LIMIT 1
        """,
        (season_id, day * 288, (day + 1) * 288),
    ).fetchone()
    state = loads(row["state_json"], {}) if row else {}
    weather = state.get("weather") if isinstance(state, dict) else None
    return weather if isinstance(weather, dict) else fallback


def rebuild_verified_chronicles(
    connection: sqlite3.Connection,
    season_id: int,
) -> dict[str, Any]:
    season = connection.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
    if not season or season["status"] != "complete":
        raise RuntimeError("only completed seasons can be rebuilt")
    fallback_weather = loads(season["weather_json"], {})
    connection.execute("DELETE FROM daily_chronicles WHERE season_id=?", (season_id,))
    rebuilt = []
    for day in range(7):
        start, end = day * 288, (day + 1) * 288
        event = connection.execute(
            """
            SELECT title,summary FROM town_events
            WHERE season_id=? AND day=? ORDER BY id DESC LIMIT 1
            """,
            (season_id, day),
        ).fetchone()
        ledger = list(
            connection.execute(
                """
                SELECT id,headline,summary,significance,phase FROM story_ledger
                WHERE season_id=? AND ((tick>=? AND tick<?) OR (day=? AND phase='epilogue'))
                ORDER BY significance DESC,tick,id LIMIT 8
                """,
                (season_id, start, end, day),
            )
        )
        activity_count = _scalar(
            connection,
            "SELECT COUNT(*) FROM activities WHERE season_id=? AND tick>=? AND tick<?",
            (season_id, start, end),
        )
        conversation_count = _scalar(
            connection,
            "SELECT COUNT(*) FROM conversations WHERE season_id=? AND tick>=? AND tick<?",
            (season_id, start, end),
        )
        transaction_count = _scalar(
            connection,
            """
            SELECT COUNT(*) FROM financial_transactions
            WHERE season_id=? AND tick>=? AND tick<? AND status='posted'
            """,
            (season_id, start, end),
        )
        weather = _recorded_weather(connection, season_id, day, fallback_weather)
        facts = [str(row["summary"]).strip() for row in ledger if str(row["summary"]).strip()]
        if not facts and event:
            facts.append(str(event["summary"]).strip())
        if not facts:
            facts.append("Residents followed their recorded routines around the Lagoon.")
        narrative = (
            f"Krabville recorded {weather.get('condition', 'calm')} weather. "
            + " ".join(facts[:5])
            + f" The ledger closed with {activity_count} activity changes, "
              f"{conversation_count} conversations, and {transaction_count} posted transactions."
        )
        title = f"Day {day + 1}: {event['title'] if event else (ledger[0]['headline'] if ledger else 'Around the Lagoon')}"
        ledger_ids = [int(row["id"]) for row in ledger]
        statistics = {
            "activities": activity_count,
            "conversations": conversation_count,
            "transactions": transaction_count,
            "ledgerEntries": len(ledger),
            "weather": weather,
        }
        connection.execute(
            """
            INSERT INTO daily_chronicles(
              season_id,day,title,narrative,statistics_json,created_at,
              source,verified,ledger_ids_json
            ) VALUES(?,?,?,?,?,?,'ledger_local',1,?)
            """,
            (season_id, day, title[:160], narrative[:1200], dumps(statistics), now_iso(), dumps(ledger_ids)),
        )
        rebuilt.append({"day": day, "ledgerIds": ledger_ids})
    return {"seasonId": season_id, "chronicles": rebuilt}


def verify_archive(connection: sqlite3.Connection, season_id: int) -> dict[str, Any]:
    rows = list(
        connection.execute(
            """
            SELECT day,verified,source,ledger_ids_json FROM daily_chronicles
            WHERE season_id=? ORDER BY day
            """,
            (season_id,),
        )
    )
    invalid_ledger_ids: list[int] = []
    for row in rows:
        for ledger_id in loads(row["ledger_ids_json"], []):
            if not connection.execute(
                "SELECT 1 FROM story_ledger WHERE id=? AND season_id=?",
                (ledger_id, season_id),
            ).fetchone():
                invalid_ledger_ids.append(int(ledger_id))
    return {
        "seasonId": season_id,
        "days": len(rows),
        "verified": len(rows) == 7 and all(bool(row["verified"]) for row in rows),
        "sources": sorted({str(row["source"]) for row in rows}),
        "invalidLedgerIds": invalid_ledger_ids,
    }


def generate_report(
    connection: sqlite3.Connection,
    season_id: int,
    settings: Settings | None = None,
) -> Path:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    season = connection.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
    if not season:
        raise RuntimeError("season not found")
    chronicles = list(
        connection.execute(
            "SELECT * FROM daily_chronicles WHERE season_id=? ORDER BY day", (season_id,)
        )
    )
    events = list(
        connection.execute("SELECT * FROM town_events WHERE season_id=? ORDER BY day", (season_id,))
    )
    statistics = _stats(connection, season_id)
    headline = _headline(season, statistics, events)
    narrative = " ".join(str(row["narrative"]) for row in chronicles)[:5000]
    if not narrative:
        narrative = " ".join(item["summary"] for item in statistics["ledger"]["highlights"])[:5000]

    exterior_season = ("spring", "summer", "fall", "winter")[
        min(3, max(0, (int(season["number"]) - 1) // 5))
    ]
    map_path = settings.asset_dir / f"kvsim-town-v21-{exterior_season}.webp"
    if not map_path.exists():
        map_path = settings.asset_dir / "kvsim-town-v21-spring.webp"
    if map_path.exists():
        with Image.open(map_path) as source:
            background = source.convert("RGB").resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    else:
        background = Image.new("RGB", (WIDTH, HEIGHT), "#0b3042")
    canvas = background.convert("RGBA")
    canvas.alpha_composite(Image.new("RGBA", (WIDTH, HEIGHT), (3, 15, 25, 202)))
    draw = ImageDraw.Draw(canvas)
    title_font = _font(58, bold=True)
    headline_font = _font(30, bold=True)
    body_font = _font(19)
    small_font = _font(16)
    label_font = _font(16, bold=True)

    draw.rounded_rectangle(
        (42, 32, 1878, 1048),
        radius=28,
        fill=(6, 23, 35, 230),
        outline=(89, 210, 224, 120),
        width=2,
    )
    draw.text((78, 61), f"KRABVILLE  /  SEASON {season['number']}", font=label_font, fill="#69d7e5")
    draw.text((74, 91), "SEVEN DAYS AROUND THE LAGOON", font=title_font, fill="#f6fbff")
    for index, line in enumerate(_wrapped(draw, headline, headline_font, 1710)[:2]):
        draw.text((78, 165 + index * 37), line, font=headline_font, fill="#ffcf6b")

    ledger_count = statistics["ledger"]["entries"] or statistics["drama"]["lifeEvents"]
    kpis = (
        (str(statistics["residents"]), "RESIDENTS"),
        (str(statistics["activities"]), "ACTIVITY CHANGES"),
        (str(statistics["conversations"]), "CONVERSATIONS"),
        (str(ledger_count), "STORY BEATS"),
        (str(statistics["voting"]["votes"]), "PUBLIC VOTES"),
        (f"{statistics['modelTokens']:,}", "MODEL TOKENS"),
    )
    for index, (value, label) in enumerate(kpis):
        left = 78 + index * 291
        draw.rounded_rectangle(
            (left, 240, left + 272, 325),
            radius=14,
            fill=(18, 50, 67, 225),
            outline=(255, 255, 255, 30),
        )
        draw.text((left + 17, 249), _fit(draw, value, _font(28, bold=True), 238), font=_font(28, bold=True), fill="#ffffff")
        draw.text((left + 17, 292), label, font=_font(13, bold=True), fill="#9db9c8")

    # Lifecycle
    x, y, width = _panel(draw, (78, 348, 604, 608), "People & lifecycle")
    lifecycle = statistics["lifecycle"]
    if lifecycle["available"]:
        stage_text = "  ".join(
            f"{stage.title()} {lifecycle['stages'][stage]}"
            for stage in STAGE_ORDER
            if lifecycle["stages"].get(stage)
        )
        draw.text((x, y), _fit(draw, stage_text or "No living residents", body_font, width), font=body_font, fill="#ffffff")
        _metric(draw, x, y + 39, str(lifecycle["births"]), "Births", 100, color="#9be39f")
        _metric(draw, x + 112, y + 39, str(lifecycle["deaths"]), "Deaths", 100, color="#ff9c9c")
        _metric(draw, x + 224, y + 39, str(lifecycle["activeCare"]), "Care plans", 110)
        _metric(draw, x + 350, y + 39, str(lifecycle["averageStress"]), "Avg stress", 105)
        need_text = ", ".join(
            f"{item['need'].replace('_', ' ')} {item['average']:.0f}%"
            for item in lifecycle["criticalNeeds"]
        )
        draw.text((x, y + 122), "LOWEST NEEDS", font=_font(14, bold=True), fill="#8ea8b7")
        draw.text((x, y + 147), _fit(draw, need_text or "No need samples recorded", body_font, width), font=body_font, fill="#bfd0da")
        care_line = f"Care gaps {lifecycle['uncoveredCare']}  /  Living population {lifecycle['living']}"
        draw.text((x, y + 184), care_line, font=small_font, fill="#8ea8b7")
    else:
        draw.text((x, y), "Legacy season: lifecycle ledger was not yet available.", font=body_font, fill="#bfd0da")

    # Economy
    x, y, width = _panel(draw, (78, 628, 604, 958), "Town economy")
    economy = statistics["economy"]
    if economy["available"]:
        _metric(draw, x, y, _money(economy["accountBalanceCents"]), "Account balance", 210, color="#9be39f")
        _metric(draw, x + 250, y, _money(economy["debtCents"]), "Outstanding debt", 210, color="#ffb183")
        _metric(draw, x, y + 78, _money(economy["assetsCents"]), "Owned assets", 210)
        _metric(draw, x + 250, y + 78, _money(economy["investmentsCents"]), "Investments", 210)
        _metric(draw, x, y + 156, str(economy["postedTransactions"]), "Posted transactions", 210)
        _metric(draw, x + 250, y + 156, _money(economy["moneyMovedCents"]), "Money moved", 210)
        draw.text((x, y + 225), "BUSIEST CATEGORY", font=_font(14, bold=True), fill="#8ea8b7")
        draw.text((x, y + 247), str(economy["topCategory"] or "No posted activity").title(), font=body_font, fill="#bfd0da")
    else:
        draw.text((x, y), "Legacy season: no economy ledger was recorded.", font=body_font, fill="#bfd0da")

    # Story ledger and drama
    x, y, width = _panel(
        draw,
        (624, 348, 1248, 710),
        "Season ledger",
        f"{statistics['drama']['highSeverityEvents']} high-severity",
    )
    highlights = statistics["ledger"]["highlights"]
    if not highlights:
        highlights = [
            {"day": 0, "headline": item["title"], "summary": item["summary"], "significance": item["severity"]}
            for item in statistics["drama"]["highlights"]
        ]
    if not highlights:
        highlights = [
            {"day": int(row["day"]) + 1, "headline": str(row["title"]), "summary": str(row["summary"]), "significance": 0}
            for row in events[:4]
        ]
    for index, item in enumerate(highlights[:4]):
        top = y + index * 72
        day = f"D{item['day']}" if item.get("day") else "EVENT"
        draw.rounded_rectangle((x, top + 2, x + 58, top + 28), radius=7, fill=(31, 78, 91, 255))
        draw.text((x + 29, top + 7), day, font=_font(12, bold=True), fill="#9ce7ef", anchor="ma")
        draw.text((x + 70, top), _fit(draw, str(item["headline"]), _font(19, bold=True), width - 70), font=_font(19, bold=True), fill="#ffffff")
        summary = _fit(draw, str(item["summary"]), small_font, width - 70)
        draw.text((x + 70, top + 28), summary, font=small_font, fill="#aebfca")
        significance = int(item.get("significance", 0))
        if significance:
            draw.rectangle((x + 70, top + 53, x + 70 + round((width - 70) * significance / 100), top + 56), fill="#ffcf6b")
    drama = statistics["drama"]
    footer = (
        f"Life events {drama['lifeEvents']}  /  Permanent {drama['permanentEvents']}  /  "
        f"Secrets {drama['secrets']}  /  Revealed {drama['revealedSecrets']}"
    )
    draw.text((x, 676), _fit(draw, footer, small_font, width), font=small_font, fill="#8ea8b7")

    # Seven daily chronicles
    x, y, width = _panel(draw, (624, 730, 1248, 958), "The week in seven days")
    day_rows = chronicles[:7]
    if day_rows:
        for index, chronicle in enumerate(day_rows):
            top = y + index * 22
            title = str(chronicle["title"]).split(":", 1)[-1].strip()
            line = f"DAY {int(chronicle['day']) + 1}  {title} — {chronicle['narrative']}"
            draw.text((x, top), _fit(draw, line, small_font, width), font=small_font, fill="#c5d4dc")
    else:
        draw.text((x, y), "No daily chronicles were recorded for this season.", font=body_font, fill="#bfd0da")

    # Relationships
    x, y, width = _panel(draw, (1268, 348, 1842, 596), "Relationships")
    relationships = statistics["relationships"]
    bond = relationships["strongestBond"]
    conflict = relationships["highestTension"]
    if bond:
        draw.text((x, y), "STRONGEST BOND", font=_font(13, bold=True), fill="#8ea8b7")
        draw.text((x, y + 24), _fit(draw, f"{bond['a']} + {bond['b']}", _font(22, bold=True), width), font=_font(22, bold=True), fill="#9be39f")
        draw.text((x, y + 56), f"Affinity {bond['affinity']}  Trust {bond['trust']}  Interactions {bond['interactions']}", font=small_font, fill="#bfd0da")
        draw.text((x, y + 92), "MOST TENSION", font=_font(13, bold=True), fill="#8ea8b7")
        draw.text((x, y + 116), _fit(draw, f"{conflict['a']} + {conflict['b']}", _font(21, bold=True), width), font=_font(21, bold=True), fill="#ffad9e")
        draw.text((x, y + 148), f"Tension {conflict['tension']}  Resentment {conflict.get('resentment', 0)}", font=small_font, fill="#bfd0da")
        draw.text((x, y + 174), f"Town averages  affinity {relationships['averageAffinity']}  trust {relationships['averageTrust']}  tension {relationships['averageTension']}", font=small_font, fill="#8ea8b7")
    else:
        draw.text((x, y), "No relationship changes were recorded.", font=body_font, fill="#bfd0da")

    # Public vote
    x, y, width = _panel(draw, (1268, 616, 1842, 810), "Public choice", f"{statistics['voting']['votes']} votes")
    winners = statistics["voting"]["winners"]
    if winners:
        for index, winner in enumerate(winners[:4]):
            line = f"DAY {winner['day']}  {winner['title']}  ({winner['category']}, {winner['votes']})"
            draw.text((x, y + index * 29), _fit(draw, line, small_font, width), font=small_font, fill="#d4e2e8")
    else:
        draw.text((x, y), "No completed public poll this season.", font=body_font, fill="#bfd0da")
    draw.text((x, 777), f"Polls held {statistics['voting']['polls']}", font=small_font, fill="#8ea8b7")

    # Provenance / model ledger
    x, y, width = _panel(draw, (1268, 830, 1842, 958), "Local provenance")
    draw.text((x, y), f"Model attempts {statistics['modelAttempts']}  /  Tokens {statistics['modelTokens']:,}", font=body_font, fill="#d4e2e8")
    draw.text((x, y + 31), f"Strange days {statistics['strangeDays']}  /  Omniscient entries {statistics['ledger']['omniscientEntries']}", font=small_font, fill="#aebfca")
    draw.text((x, y + 50), _fit(draw, f"Commitment {season['seed_commitment']}", small_font, width), font=small_font, fill="#8ea8b7")

    draw.text((78, 992), "Rendered locally from the season ledger · no image-model call", font=small_font, fill="#8ea8b7")
    draw.text((1818, 992), "CANADAVERSE.ORG", font=label_font, fill="#69d7e5", anchor="ra")

    output = settings.report_dir / f"season-{int(season['number']):03d}.png"
    canvas.convert("RGB").save(output, "PNG", optimize=True)
    connection.execute(
        """
        INSERT INTO reports(season_id,headline,narrative,poster_path,statistics_json,created_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(season_id) DO UPDATE SET headline=excluded.headline,
          narrative=excluded.narrative,poster_path=excluded.poster_path,
          statistics_json=excluded.statistics_json,created_at=excluded.created_at
        """,
        (season_id, headline, narrative, str(output), dumps(statistics), now_iso()),
    )
    return output
