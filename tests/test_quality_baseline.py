from __future__ import annotations

import json

import pytest

from krabville.quality_baseline import (
    render_markdown,
    run_quality_baseline,
    write_evidence,
)


TEST_SEEDS = ("31" * 32, "32" * 32)


def test_multi_seed_quality_report_is_stable_complete_and_provider_free(
    tmp_path,
) -> None:
    first = run_quality_baseline(seeds=TEST_SEEDS, ticks=24, replays=2)
    second = run_quality_baseline(seeds=TEST_SEEDS, ticks=24, replays=2)

    assert first == second
    assert first["status"] == "pass"
    assert first["runMode"] == "partial"
    assert first["configuration"] == {
        "seeds": list(TEST_SEEDS),
        "ticksPerSeed": 24,
        "replaysPerSeed": 2,
        "providerMode": "disabled",
        "minutesPerTick": 5,
        "criticalNeedThreshold": 20,
    }
    assert len(first["runs"]) == 2
    for run in first["runs"]:
        assert set(run) >= {
            "behaviour",
            "social",
            "economy",
            "careAndHealth",
            "eventConcentration",
            "lifecycleAndPopulation",
            "narrativeEvidence",
            "reproducibility",
        }
        assert run["reproducibility"]["matches"] is True
        assert run["narrativeEvidence"]["modelAttempts"] == 0
        assert run["economy"]["unbalancedTransactions"] == 0
        assert (
            run["social"]["residentCount"]
            == run["lifecycleAndPopulation"]["initialLiving"]
        )
        initial_stages = run["lifecycleAndPopulation"]["initialLifeStages"]
        expected_dependents = initial_stages.get("baby", 0) + initial_stages.get(
            "child", 0
        )
        assert run["careAndHealth"]["dependents"] == expected_dependents
        assert run["careAndHealth"]["dependents"] == sum(
            run["careAndHealth"]["careState"].values()
        )
        assert run["invariantsPass"] is True

    first_paths = write_evidence(first, tmp_path / "first")
    second_paths = write_evidence(second, tmp_path / "second")
    assert first_paths[0].read_bytes() == second_paths[0].read_bytes()
    assert first_paths[1].read_bytes() == second_paths[1].read_bytes()
    assert json.loads(first_paths[0].read_text(encoding="utf-8")) == first
    markdown = render_markdown(first)
    assert "Correctness invariants" in markdown
    assert "observational" in markdown


@pytest.mark.parametrize(
    ("seeds", "ticks", "replays", "message"),
    [
        (("31" * 32,), 24, 2, "at least two seeds"),
        (("31" * 32, "31" * 32), 24, 2, "unique"),
        (("not-a-seed", "32" * 32), 24, 2, "64 hexadecimal"),
        (TEST_SEEDS, 0, 2, "ticks"),
        (TEST_SEEDS, 24, 1, "at least two replays"),
    ],
)
def test_quality_report_rejects_non_reproducible_configuration(
    seeds, ticks, replays, message
) -> None:
    with pytest.raises(ValueError, match=message):
        run_quality_baseline(seeds=seeds, ticks=ticks, replays=replays)
