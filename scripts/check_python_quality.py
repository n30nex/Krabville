from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = Path(__file__).with_name("ruff_baseline.json")
TARGETS = (
    "src",
    "tests",
    "scripts",
    "tools/check_version.py",
    "tools/verify_release.py",
)


def run_ruff(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "ruff", *arguments],
        cwd=ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


def relative_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        path = path.relative_to(ROOT)
    return path.as_posix()


def lint_findings() -> Counter[tuple[str, str, str]]:
    result = run_ruff("check", *TARGETS, "--output-format=json")
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr or result.stdout)
    findings = json.loads(result.stdout or "[]")
    return Counter(
        (relative_path(item["filename"]), item["code"], item["message"])
        for item in findings
    )


def unformatted_files() -> set[str]:
    result = run_ruff("format", "--check", *TARGETS)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr or result.stdout)
    prefix = "Would reformat: "
    return {
        relative_path(line[len(prefix) :])
        for line in (result.stdout + result.stderr).splitlines()
        if line.startswith(prefix)
    }


def describe(findings: Counter[tuple[str, str, str]]) -> list[str]:
    lines: list[str] = []
    for (path, code, message), count in sorted(findings.items()):
        suffix = f" x{count}" if count > 1 else ""
        lines.append(f"{path}: {code} {message}{suffix}")
    return lines


def main() -> int:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    expected_lint = Counter(
        (item["path"], item["code"], item["message"]) for item in baseline["lint"]
    )
    expected_format = set(baseline["unformatted"])

    current_lint = lint_findings()
    current_format = unformatted_files()
    new_lint = current_lint - expected_lint
    stale_lint = expected_lint - current_lint
    new_format = current_format - expected_format
    stale_format = expected_format - current_format

    print(
        "Ruff baseline: "
        f"{sum(current_lint.values())}/{sum(expected_lint.values())} lint findings, "
        f"{len(current_format)}/{len(expected_format)} unformatted files"
    )
    if new_lint:
        print("New Ruff lint findings:", *describe(new_lint), sep="\n  ")
    if stale_lint:
        print(
            "Stale Ruff lint baseline entries; refresh the baseline:",
            *describe(stale_lint),
            sep="\n  ",
        )
    if new_format:
        print("New Ruff formatting debt:", *sorted(new_format), sep="\n  ")
    if stale_format:
        print(
            "Stale Ruff formatting baseline entries; refresh the baseline:",
            *sorted(stale_format),
            sep="\n  ",
        )
    return 1 if new_lint or stale_lint or new_format or stale_format else 0


if __name__ == "__main__":
    raise SystemExit(main())
