from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

from tools import verify_release


def test_console_text_replaces_characters_missing_from_windows_code_page():
    assert verify_release.console_text("built \u2713", "cp1252") == "built ?"


def test_release_checks_are_complete_and_ordered(tmp_path: Path):
    checks = verify_release.ordered_checks(
        tmp_path / "wheel", npm="npm-test", docker="docker-test"
    )

    assert (
        tuple(check.name for check in checks)
        + (
            "Tracked-secret scan",
            "Disposable runtime seed/API health",
            "Playwright matrix",
        )
        == verify_release.RELEASE_CHECK_ORDER
    )
    assert checks[0].command == (
        sys.executable,
        "scripts/check_python_quality.py",
    )
    assert checks[2].command[:4] == (sys.executable, "-m", "pip", "wheel")
    assert checks[3].command == ("npm-test", "run", "lint")
    assert checks[4].command == ("npm-test", "run", "build")
    assert checks[5].command[:2] == ("docker-test", "compose")


def test_runtime_environment_discards_ambient_krabville_configuration(
    tmp_path: Path,
):
    ambient = {
        "PATH": "test-path",
        "PYTHONPATH": "production-source",
        "KRABVILLE_DATA_DIR": "production-data",
        "KRABVILLE_DATABASE": "production.db",
        "KRABVILLE_PRIMARY_MODEL": "production-model",
        "KRABVILLE_VOTER_SECRET_FILE": "production-secret",
    }
    data_dir = tmp_path / "disposable"

    env = verify_release.runtime_environment(data_dir, 43210, ambient)

    assert env["PATH"] == "test-path"
    assert env["PYTHONPATH"] == str(verify_release.ROOT / "src")
    assert env["KRABVILLE_DATA_DIR"] == str(data_dir)
    assert env["KRABVILLE_DATABASE"] == str(data_dir / "krabville.db")
    assert env["KRABVILLE_BIND"] == "127.0.0.1"
    assert env["KRABVILLE_PORT"] == "43210"
    assert env["KRABVILLE_E2E_URL"] == "http://127.0.0.1:43210"
    assert "KRABVILLE_PRIMARY_MODEL" not in env
    assert "KRABVILLE_VOTER_SECRET_FILE" not in env


def test_tracked_secret_match_fails_the_gate():
    finding = "tracked.txt:1:" + "sk-" + ("x" * 20) + "\n"

    def fake_run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 0, finding, "")

    with pytest.raises(verify_release.CheckFailed, match="likely committed secrets"):
        verify_release.run_secret_scan(io.StringIO(), runner=fake_run)
