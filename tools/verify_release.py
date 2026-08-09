from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
ARTIFACT_ROOT = ROOT / ".qa" / "verify-release"
LOOPBACK = "127.0.0.1"
SECRET_PATTERN = "".join(
    (
        "(ctx7",
        "sk-|sk-[A-Za-z0-9_-]{20,}|",
        "BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|",
        "password[[:space:]]*=[[:space:]]*[^$<{])",
    )
)
RELEASE_CHECK_ORDER = (
    "Python quality",
    "Python tests",
    "Python wheel",
    "Frontend lint",
    "Frontend build",
    "Compose validation",
    "Tracked-secret scan",
    "Disposable runtime seed/API health",
    "Playwright matrix",
)


class CheckFailed(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    command: tuple[str, ...]
    cwd: Path = ROOT


def ordered_checks(
    wheel_dir: Path, *, npm: str = "npm", docker: str = "docker"
) -> tuple[Check, ...]:
    return (
        Check("Python quality", (sys.executable, "scripts/check_python_quality.py")),
        Check("Python tests", (sys.executable, "-m", "pytest")),
        Check(
            "Python wheel",
            (
                sys.executable,
                "-m",
                "pip",
                "wheel",
                ".",
                "--no-deps",
                "--wheel-dir",
                str(wheel_dir),
            ),
        ),
        Check("Frontend lint", (npm, "run", "lint"), FRONTEND),
        Check("Frontend build", (npm, "run", "build"), FRONTEND),
        Check(
            "Compose validation",
            (
                docker,
                "compose",
                "-f",
                "compose.yaml",
                "-f",
                "compose.selfhost.yaml",
                "--env-file",
                "deploy/.env.example",
                "--profile",
                "inference",
                "config",
                "--quiet",
            ),
        ),
    )


def console_text(value: str, encoding: str | None) -> str:
    codec = encoding or "utf-8"
    return value.encode(codec, errors="replace").decode(codec)


def console_write(value: str) -> None:
    sys.stdout.write(console_text(value, sys.stdout.encoding))
    sys.stdout.flush()


def emit(message: str, log: TextIO) -> None:
    console_write(f"{message}\n")
    log.write(f"{message}\n")
    log.flush()


def stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_command(
    check: Check,
    log: TextIO,
    *,
    env: Mapping[str, str] | None = None,
    extra_log: TextIO | None = None,
) -> None:
    started = time.monotonic()
    emit(f"\n==> {check.name}", log)
    emit(f"$ {shlex.join(check.command)}", log)
    try:
        process = subprocess.Popen(
            check.command,
            cwd=check.cwd,
            env=None if env is None else dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise CheckFailed(f"{check.name} could not start: {exc}") from exc

    try:
        assert process.stdout is not None
        for line in process.stdout:
            console_write(line)
            log.write(line)
            log.flush()
            if extra_log is not None:
                extra_log.write(line)
                extra_log.flush()
        returncode = process.wait()
    except BaseException:
        stop_process(process)
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()

    if returncode:
        raise CheckFailed(f"{check.name} failed with exit code {returncode}")
    emit(f"PASS {check.name} ({time.monotonic() - started:.1f}s)", log)


def run_secret_scan(log: TextIO, *, git: str = "git", runner=subprocess.run) -> None:
    started = time.monotonic()
    command = (git, "grep", "-nI", "-E", "-i", SECRET_PATTERN, "--", ".")
    emit("\n==> Tracked-secret scan", log)
    emit(f"$ {shlex.join(command)}", log)
    try:
        result = runner(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise CheckFailed(f"Tracked-secret scan could not start: {exc}") from exc

    for output in (result.stdout, result.stderr):
        if output:
            console_write(output if output.endswith("\n") else f"{output}\n")
            log.write(output)
            if not output.endswith("\n"):
                log.write("\n")
            log.flush()
    if result.returncode == 0:
        raise CheckFailed("Tracked-secret scan found likely committed secrets")
    if result.returncode != 1:
        raise CheckFailed(
            f"Tracked-secret scan failed with exit code {result.returncode}"
        )
    emit(f"PASS Tracked-secret scan ({time.monotonic() - started:.1f}s)", log)


def runtime_environment(
    data_dir: Path, port: int, base_env: Mapping[str, str] | None = None
) -> dict[str, str]:
    source = os.environ if base_env is None else base_env
    env = {
        key: value for key, value in source.items() if not key.startswith("KRABVILLE_")
    }
    env.update(
        {
            "PYTHONPATH": str(ROOT / "src"),
            "KRABVILLE_DATA_DIR": str(data_dir),
            "KRABVILLE_DATABASE": str(data_dir / "krabville.db"),
            "KRABVILLE_REPORT_DIR": str(data_dir / "reports"),
            "KRABVILLE_CONTROL_SOCKET": str(data_dir / "control.sock"),
            "KRABVILLE_ASSET_DIR": str(FRONTEND / "public" / "assets"),
            "KRABVILLE_FRONTEND_DIR": str(FRONTEND / "dist"),
            "KRABVILLE_BIND": LOOPBACK,
            "KRABVILLE_PORT": str(port),
            "KRABVILLE_E2E_URL": f"http://{LOOPBACK}:{port}",
            "KRABVILLE_PUBLIC_ORIGIN": f"http://{LOOPBACK}:{port}",
            "KRABVILLE_FAKE_PROVIDER": "true",
            "KRABVILLE_VOTER_SECRET": "verify-release-disposable-secret",
        }
    )
    return env


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((LOOPBACK, 0))
        return int(listener.getsockname()[1])


def wait_for_health(
    process: subprocess.Popen[str], url: str, health_path: Path, timeout: float = 30
) -> None:
    deadline = time.monotonic() + timeout
    last_error = "API did not answer"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise CheckFailed(
                f"API exited before becoming healthy ({process.returncode})"
            )
        try:
            with urlopen(f"{url}/healthz", timeout=2) as response:
                body = response.read()
            payload = json.loads(body)
            if payload.get("ok") is not True:
                raise ValueError("health payload reported ok=false")
            health_path.write_bytes(body + (b"\n" if not body.endswith(b"\n") else b""))
            return
        except (
            HTTPError,
            URLError,
            TimeoutError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            last_error = str(exc)
            time.sleep(1)
    raise CheckFailed(f"API did not become healthy within {timeout:.0f}s: {last_error}")


def artifact_directory() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = ARTIFACT_ROOT / f"{stamp}-{os.getpid()}"
    path.mkdir(parents=True)
    return path


def copy_playwright_results(destination: Path, log: TextIO) -> None:
    source = FRONTEND / "test-results"
    if not source.exists():
        return
    try:
        shutil.copytree(source, destination, dirs_exist_ok=True)
    except OSError as exc:
        emit(f"WARNING could not copy Playwright results: {exc}", log)


def seed_runtime(env: Mapping[str, str], log: TextIO) -> None:
    commands: Sequence[Check] = (
        Check(
            "Disposable runtime initialize",
            (sys.executable, "-m", "krabville.cli", "init"),
        ),
        Check(
            "Disposable runtime start season",
            (sys.executable, "-m", "krabville.cli", "start"),
        ),
        Check(
            "Disposable runtime seed ticks",
            (sys.executable, "-m", "krabville.cli", "tick", "--count", "49"),
        ),
    )
    for check in commands:
        run_command(check, log, env=env)


def main() -> int:
    artifacts = artifact_directory()
    wheel_dir = artifacts / "wheel"
    wheel_dir.mkdir()
    log_path = artifacts / "verify-release.log"
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        emit(f"Release verification evidence: {artifacts}", log)
        try:
            npm = shutil.which("npm") or "npm"
            docker = shutil.which("docker") or "docker"
            for check in ordered_checks(wheel_dir, npm=npm, docker=docker):
                run_command(check, log)
            run_secret_scan(log, git=shutil.which("git") or "git")

            emit("\n==> Disposable runtime seed/API health", log)
            with tempfile.TemporaryDirectory(prefix="krabville-verify-") as temporary:
                data_dir = Path(temporary) / "data"
                seed_env = runtime_environment(data_dir, 0)
                seed_runtime(seed_env, log)

                port = free_loopback_port()
                runtime_env = runtime_environment(data_dir, port)
                api_log_path = artifacts / "krabville-api.log"
                health_path = artifacts / "krabville-health.json"
                playwright_log_path = artifacts / "playwright.log"
                with api_log_path.open(
                    "w", encoding="utf-8", errors="replace"
                ) as api_log:
                    api = subprocess.Popen(
                        (sys.executable, "-m", "krabville.api"),
                        cwd=ROOT,
                        env=runtime_env,
                        stdout=api_log,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    try:
                        url = runtime_env["KRABVILLE_E2E_URL"]
                        wait_for_health(api, url, health_path)
                        emit(f"PASS Disposable runtime seed/API health ({url})", log)
                        with playwright_log_path.open(
                            "w", encoding="utf-8", errors="replace"
                        ) as playwright_log:
                            try:
                                run_command(
                                    Check(
                                        "Playwright matrix",
                                        (npm, "run", "test:e2e"),
                                        FRONTEND,
                                    ),
                                    log,
                                    env=runtime_env,
                                    extra_log=playwright_log,
                                )
                            finally:
                                copy_playwright_results(
                                    artifacts / "playwright-test-results", log
                                )
                    finally:
                        stop_process(api)
        except (CheckFailed, OSError) as exc:
            emit(f"\nFAILED: {exc}", log)
            emit(f"Evidence retained at {artifacts}", log)
            return 1
        except KeyboardInterrupt:
            emit("\nFAILED: interrupted", log)
            emit(f"Evidence retained at {artifacts}", log)
            return 130

        emit("\nPASS unified release verification", log)
        emit(f"Evidence retained at {artifacts}", log)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
