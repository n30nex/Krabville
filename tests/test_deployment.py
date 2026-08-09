from pathlib import Path


def test_compose_unit_stops_profile_services() -> None:
    unit = (Path(__file__).parents[1] / "deploy" / "krabville-compose.service").read_text(encoding="utf-8")
    stop = next(line for line in unit.splitlines() if line.startswith("ExecStop="))
    assert "--profile inference stop" in stop
