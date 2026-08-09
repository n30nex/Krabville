from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from krabville.commerce_v2 import CATALOG, INTERIOR_VARIANTS, ITEM_ASSET_INDEX
from krabville.db import initialize
from krabville.world import start_season


def test_interior_atlas_has_41_populated_fixed_frames() -> None:
    path = Path(__file__).resolve().parents[1] / "frontend" / "public" / "assets" / "interiors-v4.png"
    with Image.open(path) as image:
        assert image.mode == "RGBA"
        assert image.size == (1792, 1536)
        assert image.getpixel((0, 0))[3] == 0
        for index in range(41):
            column, row = index % 7, index // 7
            frame = image.crop((column * 256, row * 256, (column + 1) * 256, (row + 1) * 256))
            assert frame.getchannel("A").getbbox(), f"empty interior frame {index}"


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
    assert connection.execute("SELECT 1 FROM schema_migrations WHERE version=11").fetchone()
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
    assert len(catalog_skus) >= 518
    assert catalog_skus == set(ITEM_ASSET_INDEX)
    assert all(0 <= index < 452 for index in ITEM_ASSET_INDEX.values())
    with Image.open(assets / "inventory-items-v2.png") as image:
        assert image.mode == "RGBA"
        assert image.size == (1536, 1216)
        assert image.getpixel((0, 0))[3] == 0
        for index in set(ITEM_ASSET_INDEX.values()):
            column, row = index % 24, index // 24
            frame = image.crop((column * 64, row * 64, (column + 1) * 64, (row + 1) * 64))
            assert frame.getchannel("A").getbbox(), f"empty inventory frame {index}"


def test_v21_seasonal_maps_and_event_animations_are_complete() -> None:
    assets = Path(__file__).resolve().parents[1] / "frontend" / "public" / "assets"
    fingerprints = set()
    for season in ("spring", "summer", "fall", "winter"):
        with Image.open(assets / f"kvsim-town-v21-{season}.webp") as image:
            assert image.mode == "RGB"
            assert image.size == (4608, 3072)
            fingerprints.add(image.resize((64, 40)).tobytes())
    assert len(fingerprints) == 4

    with Image.open(assets / "event-props-v21.png") as image:
        assert image.mode == "RGBA"
        assert image.size == (1024, 2048)
        for index in range(128):
            column, row = index % 8, index // 8
            frame = image.crop((column * 128, row * 128, (column + 1) * 128, (row + 1) * 128))
            assert frame.getchannel("A").getbbox(), f"empty event frame {index}"


def test_asset_manifest_matches_every_shipped_asset() -> None:
    assets = Path(__file__).resolve().parents[1] / "frontend" / "public" / "assets"
    manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
    entries = {entry["name"]: entry for entry in manifest["files"]}
    assert manifest["schemaVersion"] == 2
    assert set(entries) == {path.name for path in assets.iterdir() if path.name != "manifest.json"}
    for name, entry in entries.items():
        payload = (assets / name).read_bytes()
        assert entry["bytes"] == len(payload)
        assert entry["sha256"] == hashlib.sha256(payload).hexdigest()
