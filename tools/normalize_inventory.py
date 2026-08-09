from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "art" / "kvsim" / "inventory-alpha-v1.png"
TARGET = ROOT / "frontend" / "public" / "assets" / "inventory-items-v1.png"
GRID = 14
FRAME = 64
CONTENT = 54
ROW_BOUNDS = (0, 62, 124, 189, 251, 314, 379, 440, 502, 565, 625, 682, 738, 789, 832)


def main() -> None:
    source = Image.open(SOURCE).convert("RGBA")
    atlas = Image.new("RGBA", (GRID * FRAME, GRID * FRAME), (0, 0, 0, 0))
    for row in range(GRID):
        for column in range(GRID):
            frame = source.crop(
                (
                    round(column * source.width / GRID),
                    ROW_BOUNDS[row],
                    round((column + 1) * source.width / GRID),
                    ROW_BOUNDS[row + 1],
                )
            )
            box = frame.getbbox()
            if not box:
                raise RuntimeError(f"empty inventory frame {row}:{column}")
            frame = frame.crop(box)
            scale = min(CONTENT / frame.width, CONTENT / frame.height)
            frame = frame.resize(
                (max(1, round(frame.width * scale)), max(1, round(frame.height * scale))),
                Image.Resampling.NEAREST,
            )
            cell = Image.new("RGBA", (FRAME, FRAME), (0, 0, 0, 0))
            cell.alpha_composite(frame, ((FRAME - frame.width) // 2, (FRAME - frame.height) // 2))
            atlas.alpha_composite(cell, (column * FRAME, row * FRAME))
    atlas.save(TARGET, "PNG", optimize=True)


if __name__ == "__main__":
    main()
