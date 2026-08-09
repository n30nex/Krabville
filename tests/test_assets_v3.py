from __future__ import annotations

from pathlib import Path

from PIL import Image

from krabville.commerce_v2 import INTERIOR_VARIANTS
from krabville.db import initialize
from krabville.world import start_season


def test_interior_atlas_has_25_populated_fixed_frames() -> None:
    path = Path(__file__).resolve().parents[1] / "frontend" / "public" / "assets" / "interiors-v3.png"
    with Image.open(path) as image:
        assert image.mode == "RGBA"
        assert image.size == (1280, 1280)
        assert image.getpixel((0, 0))[3] == 0
        for row in range(5):
            for column in range(5):
                frame = image.crop((column * 256, row * 256, (column + 1) * 256, (row + 1) * 256))
                alpha = frame.getchannel("A")
                assert alpha.getbbox(), f"empty interior frame {row}:{column}"
        assert sum(alpha.histogram()[221:]) > 20_000


def test_every_current_property_has_its_named_interior(settings_factory) -> None:
    connection = initialize(settings_factory())
    start_season(connection, seed_hex="98" * 32)
    actual = {
        str(row["name"]): int(row["interior_variant"])
        for row in connection.execute(
            "SELECT name,interior_variant FROM properties WHERE name IN (%s)"
            % ",".join("?" for _ in INTERIOR_VARIANTS),
            tuple(INTERIOR_VARIANTS),
        )
    }
    assert len(actual) >= 22
    assert all(INTERIOR_VARIANTS[name] == variant for name, variant in actual.items())
    assert len(set(actual.values())) == len(actual)
    assert set(INTERIOR_VARIANTS.values()) == set(range(25))
    assert connection.execute("SELECT 1 FROM schema_migrations WHERE version=9").fetchone()
    connection.close()


def test_weather_and_inventory_atlases_have_fixed_populated_frames() -> None:
    assets = Path(__file__).resolve().parents[1] / "frontend" / "public" / "assets"
    for name, size, columns, rows in (
        ("weather-seasons-v1.png", (1024, 1024), 8, 8),
        ("inventory-items-v1.png", (896, 832), 14, 13),
    ):
        with Image.open(assets / name) as image:
            assert image.mode == "RGBA"
            assert image.size == size
            assert image.getpixel((0, 0))[3] == 0
            frame_width = image.width // columns
            frame_height = image.height // rows
            for row in range(rows):
                for column in range(columns):
                    frame = image.crop((column * frame_width, row * frame_height, (column + 1) * frame_width, (row + 1) * frame_height))
                    assert frame.getchannel("A").getbbox(), f"empty {name} frame {row}:{column}"
