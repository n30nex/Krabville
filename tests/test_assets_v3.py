from __future__ import annotations

from pathlib import Path

from PIL import Image

from krabville.commerce_v2 import CATALOG, INTERIOR_VARIANTS, ITEM_ASSET_INDEX
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
    with Image.open(assets / "weather-seasons-v1.png") as image:
        assert image.mode == "RGBA"
        assert image.size == (1024, 1024)
        assert image.getpixel((0, 0))[3] == 0
        for row in range(8):
            for column in range(8):
                frame = image.crop((column * 128, row * 128, (column + 1) * 128, (row + 1) * 128))
                assert frame.getchannel("A").getbbox(), f"empty weather frame {row}:{column}"

    catalog_skus = {str(item[0]) for item in CATALOG}
    assert len(catalog_skus) >= 380
    assert catalog_skus == set(ITEM_ASSET_INDEX)
    assert all(0 <= index < 196 for index in ITEM_ASSET_INDEX.values())
    with Image.open(assets / "inventory-items-v1.png") as image:
        assert image.mode == "RGBA"
        assert image.size == (896, 896)
        assert image.getpixel((0, 0))[3] == 0
        for index in set(ITEM_ASSET_INDEX.values()):
            column, row = index % 14, index // 14
            frame = image.crop((column * 64, row * 64, (column + 1) * 64, (row + 1) * 64))
            assert frame.getchannel("A").getbbox(), f"empty inventory frame {index}"
