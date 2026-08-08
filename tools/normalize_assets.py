from __future__ import annotations

import argparse
import hashlib
import json
from collections import deque
from pathlib import Path

from PIL import Image


def remove_edge_background(image: Image.Image, threshold: int = 42) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    width, height = rgba.size
    reference = pixels[0, 0][:3]
    queue = deque()
    seen: set[tuple[int, int]] = set()
    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))
    while queue:
        x, y = queue.popleft()
        if (x, y) in seen:
            continue
        seen.add((x, y))
        red, green, blue, alpha = pixels[x, y]
        distance = abs(red - reference[0]) + abs(green - reference[1]) + abs(blue - reference[2])
        if alpha == 0 or distance <= threshold:
            pixels[x, y] = (red, green, blue, 0)
            if x:
                queue.append((x - 1, y))
            if x + 1 < width:
                queue.append((x + 1, y))
            if y:
                queue.append((x, y - 1))
            if y + 1 < height:
                queue.append((x, y + 1))
    return rgba


def normalize_atlas(source: Path, target: Path) -> None:
    image = Image.open(source).convert("RGBA")
    frame_size = 192
    output = Image.new("RGBA", (frame_size * 4, frame_size * 6), (0, 0, 0, 0))
    row_bounds = (
        (0, 212, 412, 595, 782, 990, image.height)
        if source.stem.endswith("v2")
        else (0, 208, 405, 610, 815, 1020, image.height)
    )
    for row in range(6):
        top = row_bounds[row]
        bottom = row_bounds[row + 1]
        for column in range(4):
            left = round(column * image.width / 4)
            right = round((column + 1) * image.width / 4)
            frame = remove_edge_background(image.crop((left, top, right, bottom)))
            box = frame.getbbox()
            if not box:
                raise RuntimeError(f"empty frame {row}:{column} in {source}")
            frame = frame.crop(box)
            scale = min(166 / frame.width, 166 / frame.height)
            resized = frame.resize(
                (max(1, round(frame.width * scale)), max(1, round(frame.height * scale))),
                Image.Resampling.NEAREST,
            )
            cell = Image.new("RGBA", (frame_size, frame_size), (0, 0, 0, 0))
            cell.alpha_composite(
                resized,
                ((frame_size - resized.width) // 2, frame_size - resized.height - 7),
            )
            normalized_box = cell.getbbox()
            if not normalized_box or normalized_box[0] <= 1 or normalized_box[1] <= 1 or normalized_box[2] >= frame_size - 1:
                raise RuntimeError(f"malformed normalized frame {row}:{column} in {source}")
            output.alpha_composite(cell, (column * frame_size, row * frame_size))
    target.parent.mkdir(parents=True, exist_ok=True)
    output.save(target, "PNG", optimize=True)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    world = args.source / "krabville-world-v3.png"
    atlas_a = args.source / "krabville-residents-v2.png"
    atlas_b = args.source / "krabville-residents-v3b.png"
    poster = args.source / "krabville-week-one-report.png"
    with Image.open(world) as image:
        image.convert("RGB").save(
            args.output / "krabville-map.webp",
            "WEBP",
            quality=90,
            method=6,
        )
    normalize_atlas(atlas_a, args.output / "residents-a.png")
    normalize_atlas(atlas_b, args.output / "residents-b.png")
    with Image.open(poster) as image:
        image.convert("RGB").save(
            args.output / "season-001.png",
            "PNG",
            optimize=True,
        )
    files = ["krabville-map.webp", "residents-a.png", "residents-b.png", "season-001.png"]
    manifest = {
        "schemaVersion": 1,
        "files": [
            {
                "name": name,
                "bytes": (args.output / name).stat().st_size,
                "sha256": digest(args.output / name),
            }
            for name in files
        ],
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
