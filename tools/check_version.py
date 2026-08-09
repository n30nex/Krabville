#!/usr/bin/env python3
"""Fail when Krabville release metadata disagrees."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"[0-9a-f]{40}")
MIGRATION_RE = re.compile(r"^(\d{3})_.+\.sql$")
IMAGE_RE = re.compile(r"^\s*image:\s*['\"]?krabville:([^\s'\"]+)", re.MULTILINE)


def _python_version(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        ):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    raise ValueError(f"missing string __version__ in {path}")


def _git_head(root: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().lower()


def _git_tag_commit(root: Path, tag: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().lower() if result.returncode == 0 else None


def _health_payload(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "krabville-version-check"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("health response is not a JSON object")
    return payload


def check_repository(
    root: Path = ROOT,
    *,
    release_tag: str | None = None,
    release_commit: str | None = None,
    release_schema: int | None = None,
    health: dict[str, Any] | None = None,
    head_commit: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((root / "frontend" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    compose = (root / "compose.yaml").read_text(encoding="utf-8")

    version = str(pyproject["project"]["version"])
    versions = {
        "Python package": _python_version(root / "src" / "krabville" / "__init__.py"),
        "frontend package": str(package["version"]),
        "frontend lock": str(lock["version"]),
        "frontend lock root": str(lock["packages"][""]["version"]),
    }
    errors = [
        f"{name} version {value!r} does not match pyproject.toml {version!r}"
        for name, value in versions.items()
        if value != version
    ]

    images = IMAGE_RE.findall(compose)
    if not images:
        errors.append("compose.yaml has no explicit krabville image version")
    elif any(image != version for image in images):
        errors.append(
            f"Compose image version(s) {sorted(set(images))!r} do not match {version!r}"
        )
    if "KRABVILLE_RELEASE_COMMIT: ${KRABVILLE_RELEASE_COMMIT:-unknown}" not in compose:
        errors.append("compose.yaml does not pass through KRABVILLE_RELEASE_COMMIT")

    migration_paths = sorted((root / "src" / "krabville" / "migrations").glob("*.sql"))
    malformed = [path.name for path in migration_paths if not MIGRATION_RE.fullmatch(path.name)]
    migration_versions = [
        int(match.group(1))
        for path in migration_paths
        if (match := MIGRATION_RE.fullmatch(path.name))
    ]
    schema = max(migration_versions, default=0)
    if malformed:
        errors.append(f"invalid migration filename(s): {', '.join(malformed)}")
    if migration_versions != list(range(1, schema + 1)):
        errors.append(f"migration versions are not contiguous through {schema}: {migration_versions}")

    release_values = (release_tag, release_commit, release_schema)
    release_mode = any(value is not None for value in release_values)
    release_complete = all(value is not None for value in release_values)
    if release_mode and not release_complete:
        errors.append("release checks require --release-tag, --release-commit, and --schema-version")
    elif release_mode:
        assert release_tag is not None and release_commit is not None and release_schema is not None
        if release_tag != f"v{version}":
            errors.append(f"release tag {release_tag!r} must be 'v{version}'")
        release_commit = release_commit.lower()
        if not SHA_RE.fullmatch(release_commit):
            errors.append("release commit must be a full 40-character Git SHA")
        else:
            head = (head_commit or _git_head(root)).lower()
            if release_commit != head:
                errors.append(f"release commit {release_commit} does not match HEAD {head}")
            tag_commit = _git_tag_commit(root, release_tag)
            if tag_commit is None:
                errors.append(f"release tag {release_tag!r} cannot be resolved")
            elif tag_commit != release_commit:
                errors.append(
                    f"release tag {release_tag} points to {tag_commit}, not {release_commit}"
                )
        if release_schema != schema:
            errors.append(f"release schema {release_schema} does not match latest migration {schema}")

    if health is not None:
        if not release_mode or not release_complete:
            errors.append("runtime health checks require complete release inputs")
        else:
            runtime_release = health.get("release")
            runtime_schema = health.get("schema")
            if health.get("ok") is not True:
                errors.append("runtime health is not ok")
            if not isinstance(runtime_release, dict):
                errors.append("runtime health is missing release metadata")
            else:
                if runtime_release.get("version") != version:
                    errors.append("runtime version does not match package version")
                if runtime_release.get("commit") != release_commit:
                    errors.append("runtime commit does not match release commit")
            if not isinstance(runtime_schema, dict):
                errors.append("runtime health is missing schema metadata")
            elif (
                runtime_schema.get("version") != schema
                or runtime_schema.get("required") != schema
                or runtime_schema.get("current") is not True
            ):
                errors.append("runtime schema does not match the latest migration")

    return {"version": version, "schema": schema}, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-tag")
    parser.add_argument("--release-commit")
    parser.add_argument("--schema-version", type=int)
    parser.add_argument("--health-url")
    args = parser.parse_args(argv)

    try:
        health = _health_payload(args.health_url) if args.health_url else None
        metadata, errors = check_repository(
            release_tag=args.release_tag,
            release_commit=args.release_commit,
            release_schema=args.schema_version,
            health=health,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK version={metadata['version']} schema={metadata['schema']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
