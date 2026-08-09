import json
import tomllib
from pathlib import Path

from krabville import __version__


ROOT = Path(__file__).parents[1]


def _service_block(compose: str, service: str) -> str:
    marker = f"  {service}:\n"
    block = compose.split(marker, 1)[1]
    next_service = next(
        (
            index
            for index, line in enumerate(block.splitlines(keepends=True))
            if line.startswith("  ") and not line.startswith("    ")
        ),
        None,
    )
    if next_service is None:
        return block
    return "".join(block.splitlines(keepends=True)[:next_service])


def test_systemd_health_gates_and_supervises_inference() -> None:
    compose_unit = (ROOT / "deploy" / "krabville-compose.service").read_text(encoding="utf-8")
    inference_unit = (ROOT / "deploy" / "krabville-inference.service").read_text(encoding="utf-8")
    supervisor = (ROOT / "deploy" / "run-inference-service.sh").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "Before=krabville-inference.service" in compose_unit
    assert "up -d web engine" in compose_unit
    assert "up -d web engine inference" not in compose_unit
    assert "Requires=krabville-compose.service" in inference_unit
    assert "After=krabville-compose.service" in inference_unit
    assert "Restart=on-failure" in inference_unit
    assert "docker wait" in supervisor
    assert 'restart: "no"' in compose


def test_release_versions_match() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert pyproject["project"]["version"] == __version__
    assert package["version"] == lock["version"] == lock["packages"][""]["version"] == __version__
    assert f"image: krabville:{__version__}" in compose


def test_compose_gates_every_runtime_on_one_bootstrap_owner() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    migrate = _service_block(compose, "migrate")

    assert compose.count("command: [krabville-manage, bootstrap]") == 1
    assert 'restart: "no"' in migrate
    for service in ("web", "engine", "inference"):
        block = _service_block(compose, service)
        assert "migrate:\n        condition: service_completed_successfully" in block
