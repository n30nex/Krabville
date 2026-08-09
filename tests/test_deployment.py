import json
import tomllib
from pathlib import Path

from krabville import __version__


ROOT = Path(__file__).parents[1]


def test_compose_unit_stops_profile_services() -> None:
    unit = (ROOT / "deploy" / "krabville-compose.service").read_text(encoding="utf-8")
    stop = next(line for line in unit.splitlines() if line.startswith("ExecStop="))
    assert "--profile inference stop" in stop


def test_release_versions_match() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert pyproject["project"]["version"] == __version__
    assert package["version"] == lock["version"] == lock["packages"][""]["version"] == __version__
    assert f"image: krabville:{__version__}" in compose
