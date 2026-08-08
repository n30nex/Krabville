from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .config import Settings
from .db import dumps, now_iso


WIDTH = 1920
HEIGHT = 1080


def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _wrapped(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    words = text.split()
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


def _stats(connection: sqlite3.Connection, season_id: int) -> dict[str, Any]:
    activities = int(
        connection.execute("SELECT COUNT(*) FROM activities WHERE season_id=?", (season_id,)).fetchone()[0]
    )
    conversations = int(
        connection.execute("SELECT COUNT(*) FROM conversations WHERE season_id=?", (season_id,)).fetchone()[0]
    )
    strange = int(
        connection.execute("SELECT COUNT(*) FROM town_events WHERE season_id=? AND strange=1", (season_id,)).fetchone()[0]
    )
    attempts = int(
        connection.execute("SELECT COUNT(*) FROM model_usage WHERE season_id=?", (season_id,)).fetchone()[0]
    )
    tokens = int(
        connection.execute("SELECT COALESCE(SUM(total_tokens),0) FROM model_usage WHERE season_id=?", (season_id,)).fetchone()[0]
    )
    strongest = connection.execute(
        """
        SELECT ra.name a,rb.name b,r.affinity,r.trust,r.tension,r.interactions
        FROM relationships r JOIN residents ra ON ra.id=r.resident_a
        JOIN residents rb ON rb.id=r.resident_b WHERE r.season_id=?
        ORDER BY (r.affinity+r.trust-r.tension) DESC,r.interactions DESC LIMIT 1
        """,
        (season_id,),
    ).fetchone()
    return {
        "activities": activities,
        "conversations": conversations,
        "strangeDays": strange,
        "modelAttempts": attempts,
        "modelTokens": tokens,
        "strongestBond": dict(strongest) if strongest else None,
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
    headline = "A week shaped by the Lagoon and the people who call it home"
    if events:
        notable = [event["title"] for event in events if event["strange"]]
        if notable:
            headline = f"{notable[0]} changed the course of Week {season['number']}"
        else:
            headline = f"Seven days of work, weather, and unexpected company"
    narrative = " ".join(str(row["narrative"]) for row in chronicles)[:5000]

    map_path = settings.asset_dir / "krabville-map.webp"
    if map_path.exists():
        background = Image.open(map_path).convert("RGB").resize((WIDTH, HEIGHT), Image.Resampling.LANCZOS)
    else:
        background = Image.new("RGB", (WIDTH, HEIGHT), "#0b3042")
    veil = Image.new("RGBA", (WIDTH, HEIGHT), (3, 15, 25, 185))
    canvas = background.convert("RGBA")
    canvas.alpha_composite(veil)
    draw = ImageDraw.Draw(canvas)
    title_font = _font(74, bold=True)
    headline_font = _font(37, bold=True)
    body_font = _font(24)
    small_font = _font(20)
    label_font = _font(18, bold=True)

    draw.rounded_rectangle((56, 48, 1864, 1032), radius=26, fill=(7, 25, 38, 222), outline=(89, 210, 224, 120), width=2)
    draw.text((96, 82), f"KRABVILLE · SEASON {season['number']}", font=label_font, fill="#69d7e5")
    draw.text((92, 116), "SEVEN DAYS AROUND THE LAGOON", font=title_font, fill="#f6fbff")
    for index, line in enumerate(_wrapped(draw, headline, headline_font, 1660)[:2]):
        draw.text((96, 214 + index * 48), line, font=headline_font, fill="#ffcf6b")

    stats = (
        ("12", "RESIDENTS"),
        (str(statistics["activities"]), "ACTIVITY CHANGES"),
        (str(statistics["conversations"]), "CONVERSATIONS"),
        (str(statistics["strangeDays"]), "STRANGE DAYS"),
        (str(statistics["modelAttempts"]), "MODEL ATTEMPTS"),
    )
    box_width = 326
    for index, (value, label) in enumerate(stats):
        left = 96 + index * 344
        draw.rounded_rectangle((left, 325, left + box_width, 420), radius=16, fill=(18, 50, 67, 225), outline=(255, 255, 255, 35))
        draw.text((left + 18, 338), value, font=_font(34, bold=True), fill="#ffffff")
        draw.text((left + 18, 386), label, font=label_font, fill="#9db9c8")

    card_width = 410
    card_height = 176
    for index, chronicle in enumerate(chronicles[:7]):
        row = index // 4
        col = index % 4
        left = 96 + col * 428
        top = 455 + row * 194
        draw.rounded_rectangle((left, top, left + card_width, top + card_height), radius=15, fill=(12, 38, 53, 235), outline=(101, 202, 215, 45))
        draw.text((left + 17, top + 15), f"DAY {int(chronicle['day']) + 1}", font=label_font, fill="#69d7e5")
        title = str(chronicle["title"]).split(":", 1)[-1].strip()
        draw.text((left + 17, top + 44), title[:31], font=_font(24, bold=True), fill="#ffffff")
        lines = _wrapped(draw, str(chronicle["narrative"]), small_font, card_width - 34)
        for line_index, line in enumerate(lines[:4]):
            draw.text((left + 17, top + 82 + line_index * 23), line, font=small_font, fill="#bfd0da")

    bond = statistics.get("strongestBond")
    if bond:
        bond_text = f"Strongest bond: {bond['a']} + {bond['b']} · affinity {bond['affinity']} · trust {bond['trust']}"
        draw.text((96, 870), bond_text, font=body_font, fill="#9be39f")
    draw.text((96, 920), f"Randomness commitment {str(season['seed_commitment'])[:20]}…", font=small_font, fill="#8ea8b7")
    draw.text((96, 958), "Generated locally from the verified season ledger · no image-model call", font=small_font, fill="#8ea8b7")
    draw.text((1510, 958), "CANADAVERSE.ORG", font=label_font, fill="#69d7e5")

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
