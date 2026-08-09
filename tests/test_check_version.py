from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient

from krabville.api import create_app
from krabville.db import initialize
from tools import check_version as version_check
from tools.check_version import check_repository


ROOT = Path(__file__).parents[1]


def test_check_version_command_accepts_repository() -> None:
    metadata, errors = check_repository(ROOT)
    assert errors == []
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "check_version.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        f"OK version={metadata['version']} schema={metadata['schema']}"
    )


def test_check_version_reports_package_compose_and_migration_drift(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    for relative in (
        "frontend/package.json",
        "frontend/package-lock.json",
        "src/krabville/__init__.py",
        "pyproject.toml",
        "compose.yaml",
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    shutil.copytree(
        ROOT / "src" / "krabville" / "migrations",
        root / "src" / "krabville" / "migrations",
    )

    package_path = root / "frontend" / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["version"] = "9.9.9"
    package_path.write_text(json.dumps(package), encoding="utf-8")
    compose_path = root / "compose.yaml"
    compose_path.write_text(
        compose_path.read_text(encoding="utf-8").replace(
            "KRABVILLE_RELEASE_COMMIT: ${KRABVILLE_RELEASE_COMMIT:-unknown}",
            "KRABVILLE_RELEASE_COMMIT: unknown",
        ),
        encoding="utf-8",
    )
    (root / "src" / "krabville" / "migrations" / "007_everyday_economy.sql").unlink()

    _, errors = check_repository(root)
    assert any("frontend package version '9.9.9'" in error for error in errors)
    assert "compose.yaml does not pass through KRABVILLE_RELEASE_COMMIT" in errors
    assert any("migration versions are not contiguous" in error for error in errors)


def test_release_inputs_match_runtime_health_and_schema(
    settings_factory, monkeypatch
) -> None:
    metadata, static_errors = check_repository(ROOT)
    assert static_errors == []
    release_commit = "a" * 40
    release_tag = f"v{metadata['version']}"
    monkeypatch.setattr(
        version_check, "_git_tag_commit", lambda _root, _tag: release_commit
    )
    settings = settings_factory(release_commit=release_commit)
    connection = initialize(settings)
    connection.close()

    with TestClient(create_app(settings), base_url="http://testserver") as client:
        health = client.get("/healthz").json()

    assert health["schema"] == {
        "version": metadata["schema"],
        "required": metadata["schema"],
        "current": True,
    }
    _, errors = check_repository(
        ROOT,
        release_tag=release_tag,
        release_commit=release_commit,
        release_schema=metadata["schema"],
        health=health,
        head_commit=release_commit,
    )
    assert errors == []

    _, errors = check_repository(ROOT, release_tag=release_tag)
    assert (
        "release checks require --release-tag, --release-commit, and --schema-version"
        in errors
    )

    _, errors = check_repository(
        ROOT,
        release_tag="v0.0.0",
        release_commit=release_commit,
        release_schema=metadata["schema"] + 1,
        head_commit="b" * 40,
    )
    assert any("release tag" in error and "must be" in error for error in errors)
    assert any("does not match HEAD" in error for error in errors)
    assert any("does not match latest migration" in error for error in errors)

    drifted = deepcopy(health)
    drifted["release"]["commit"] = "0" * 40
    drifted["schema"]["version"] = 12
    _, errors = check_repository(
        ROOT,
        release_tag=release_tag,
        release_commit=release_commit,
        release_schema=metadata["schema"],
        health=drifted,
        head_commit=release_commit,
    )
    assert "runtime commit does not match release commit" in errors
    assert "runtime schema does not match the latest migration" in errors
