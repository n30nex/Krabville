from __future__ import annotations

import json

import pytest

from krabville.simulation_v2 import (
    DEFAULT_NEEDS,
    NEED_NAMES,
    boredom_score,
    derive_mood,
    family_intent,
    generate_short_term_wants,
    normalize_needs,
    score_candidate_actions,
    update_needs,
)


def test_normalize_needs_is_high_good_complete_and_bounded() -> None:
    result = normalize_needs({"energy": -4, "hunger": 180, "health": "bad", "fun": float("nan")})
    assert tuple(result) == NEED_NAMES
    assert result["energy"] == 0
    assert result["hunger"] == 100
    assert result["health"] == DEFAULT_NEEDS["health"]
    assert result["fun"] == DEFAULT_NEEDS["fun"]
    assert all(0 <= value <= 100 for value in result.values())
    json.dumps(result)


def test_need_update_is_deterministic_bounded_and_activity_recovers_need() -> None:
    state = {
        "needs": {name: 50 for name in NEED_NAMES},
        "activity": "sleeping",
        "lifeStage": "adult",
        "weather": {"condition": "clear", "temperatureC": 21},
        "elapsedMinutes": 5,
    }
    first = update_needs(state)
    assert first == update_needs(state)
    assert first["needs"]["energy"] > 50
    assert first["needs"]["hunger"] < 50
    assert state["needs"]["energy"] == 50
    extreme = update_needs({**state, "elapsedMinutes": 1_440, "activity": "work shift"})
    assert all(0 <= value <= 100 for value in extreme["needs"].values())
    json.dumps(first)


def test_life_stage_weather_and_health_change_decay() -> None:
    base = {"needs": {name: 80 for name in NEED_NAMES}, "activity": "walking outside", "elapsedMinutes": 5}
    adult = update_needs({**base, "lifeStage": "adult", "weather": {"condition": "clear", "temperatureC": 21}})
    baby = update_needs({**base, "lifeStage": "baby", "weather": {"condition": "clear", "temperatureC": 21}})
    storm = update_needs({**base, "lifeStage": "adult", "weather": {"condition": "storm", "temperatureC": -8}})
    ill = update_needs({**base, "lifeStage": "adult", "health": {"severity": 90}})
    assert baby["needs"]["energy"] < adult["needs"]["energy"]
    assert storm["needs"]["safety"] < adult["needs"]["safety"]
    assert storm["needs"]["comfort"] < adult["needs"]["comfort"]
    assert ill["needs"]["energy"] < adult["needs"]["energy"]
    assert ill["needs"]["fun"] < adult["needs"]["fun"]


@pytest.mark.parametrize("need", NEED_NAMES)
def test_every_need_changes_mood_and_its_action_utility(need: str) -> None:
    baseline = {name: 80 for name in NEED_NAMES}
    low = dict(baseline)
    low[need] = 5
    baseline_mood = derive_mood({"needs": baseline})
    low_mood = derive_mood({"needs": low})
    baseline_actions = score_candidate_actions({"needs": baseline, "hour": 14})
    low_actions = score_candidate_actions({"needs": low, "hour": 14})
    action = {
        "energy": "restore_energy",
        "hunger": "eat_meal",
        "hygiene": "wash_up",
        "health": "seek_healthcare",
        "comfort": "get_comfortable",
        "safety": "seek_safety",
        "fun": "have_fun",
        "social": "socialize",
        "belonging": "join_community",
        "privacy": "get_privacy",
        "purpose": "pursue_purpose",
        "autonomy": "reclaim_autonomy",
        "financial_security": "improve_finances",
    }[need]
    assert low_mood["valence"] < baseline_mood["valence"]
    assert low_actions["allScores"][action] > baseline_actions["allScores"][action]


def test_wants_and_top_three_are_deterministic_and_explainable() -> None:
    needs = {name: 85 for name in NEED_NAMES}
    needs.update({"hunger": 4, "privacy": 12, "purpose": 18})
    wants = generate_short_term_wants({"needs": needs})
    actions = score_candidate_actions({"needs": needs, "hour": 12, "wants": wants["wants"]})
    assert [want["sourceNeed"] for want in wants["wants"]] == ["hunger", "purpose", "privacy"]
    assert len(actions["choices"]) == 3
    assert actions == score_candidate_actions({"needs": needs, "hour": 12, "wants": wants["wants"]})
    assert actions["decision"] == "eat_meal"
    assert sum(choice["confidence"] for choice in actions["choices"]) == pytest.approx(100, abs=0.2)
    assert all(choice["thought"] for choice in actions["choices"])
    json.dumps(actions)


def test_childcare_preempts_other_actions() -> None:
    result = score_candidate_actions(
        {"needs": {name: 90 for name in NEED_NAMES}, "uncoveredDependents": 2}
    )
    assert result["decision"] == "secure_childcare"


def test_boredom_is_bounded_and_directs_only_a_stagnant_town() -> None:
    busy = boredom_score(
        {
            "minutesSinceMeaningfulEvent": 15,
            "routineRepetition": 0.1,
            "meaningfulEvents": 2,
            "activityChanges": 8,
            "conversations": 4,
            "conflicts": 1,
            "relationshipChanges": 2,
        }
    )
    stagnant = boredom_score({"minutesSinceMeaningfulEvent": 900, "routineRepetition": 1})
    assert 0 <= busy["score"] < 45
    assert busy["shouldDirect"] is False
    assert 70 <= stagnant["score"] <= 100
    assert stagnant["shouldDirect"] is True
    json.dumps(stagnant)


def test_family_intent_respects_population_cap_and_childcare() -> None:
    stable = {
        "resident": {
            "lifeStage": "adult",
            "familyDesire": 95,
            "needs": {name: 92 for name in NEED_NAMES},
            "relationship": {"commitment": 90, "trust": 90},
        },
        "household": {
            "members": 2,
            "housingCapacity": 5,
            "caregiverCoverage": 1,
            "familySupport": 80,
            "monthlyDisposableIncome": 2_000,
        },
        "population": {"living": 12, "cap": 32, "minors": 4, "minorCap": 12},
    }
    allowed = family_intent(stable)
    capped = family_intent({**stable, "population": {"living": 32, "cap": 32, "minors": 12, "minorCap": 12}})
    childcare = family_intent(
        {
            **stable,
            "household": {
                **stable["household"],
                "dependents": [{"lifeStage": "baby"}],
                "caregiverCoverage": 0,
            },
        }
    )
    assert allowed["intent"] == "consider_family_growth"
    assert allowed["allowsFamilyGrowth"] is True
    assert capped["intent"] == "defer_family_growth"
    assert capped["allowsFamilyGrowth"] is False
    assert childcare["intent"] == "hire_caregiver"
    assert childcare["allowsFamilyGrowth"] is False
    for result in (allowed, capped, childcare):
        assert 0 <= result["score"] <= 100
        json.dumps(result)
