from __future__ import annotations

import argparse
from pathlib import Path

from krabville.quality_baseline import (
    DEFAULT_SEEDS,
    run_quality_baseline,
    write_evidence,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic KVsim simulation-quality baseline."
    )
    parser.add_argument(
        "--seed",
        action="append",
        dest="seeds",
        help="64-character hexadecimal seed; repeat for each seed (minimum two)",
    )
    parser.add_argument("--ticks", type=int, default=2016)
    parser.add_argument("--replays", type=int, default=2)
    parser.add_argument(
        "--output-dir", type=Path, default=Path(".qa/simulation-quality")
    )
    arguments = parser.parse_args()
    report = run_quality_baseline(
        seeds=arguments.seeds or DEFAULT_SEEDS,
        ticks=arguments.ticks,
        replays=arguments.replays,
    )
    json_path, markdown_path = write_evidence(report, arguments.output_dir)
    print(f"Simulation quality: {report['status']}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
