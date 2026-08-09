from __future__ import annotations

from itertools import groupby

from krabville.simulation_v2 import NEED_NAMES, score_candidate_actions


def _needs(value: float = 62.0) -> dict[str, float]:
    return {name: value for name in NEED_NAMES}


def test_seeded_weighted_selection_is_reproducible_and_diverse() -> None:
    state = {
        "needs": _needs(),
        "hour": 15,
        "selectionTemperature": 28,
    }
    first = score_candidate_actions(state, seed={"season": 3, "tick": 144, "resident": 7})
    second = score_candidate_actions(state, seed={"season": 3, "tick": 144, "resident": 7})

    assert first == second
    assert first["selection"]["mode"] == "seeded-weighted"
    decisions = {score_candidate_actions(state, seed=index)["decision"] for index in range(40)}
    assert len(decisions) >= 3


def test_depth_context_changes_utility_and_reports_each_factor() -> None:
    baseline_state = {"needs": _needs(), "hour": 10}
    baseline = score_candidate_actions(baseline_state)
    deep = score_candidate_actions(
        {
            **baseline_state,
            "traits": {"conscientiousness": 90, "ambition": 85, "openness": 75},
            "schedule": {"preferredActions": ["pursue_purpose"]},
            "goals": [
                {"status": "active", "targetAction": "pursue_purpose", "priority": 90}
            ],
            "memories": [
                {"content": "project milestone", "salience": 90, "valence": 70}
            ],
            "inventory": {"project notebook": 1, "laptop tool": 1},
            "employment": {"status": "active", "onShift": True},
            "travel": {"pursue_purpose": {"minutes": 8}},
            "venueHours": {"pursue_purpose": {"openNow": True}},
        }
    )

    assert deep["allScores"]["pursue_purpose"] > baseline["allScores"]["pursue_purpose"] + 35
    kinds = {factor["kind"] for factor in deep["factorBreakdown"]["pursue_purpose"]}
    assert {
        "trait",
        "schedule",
        "goal",
        "memory",
        "inventory",
        "employment",
        "travel",
        "venue_hours",
    } <= kinds


def test_relationships_care_and_closed_venues_affect_real_choices() -> None:
    baseline = score_candidate_actions({"needs": _needs(), "hour": 19})
    connected = score_candidate_actions(
        {
            "needs": _needs(),
            "hour": 19,
            "relationships": {
                "friend": {"affinity": 92, "trust": 90, "affection": 84, "tension": 0}
            },
        }
    )
    assert connected["allScores"]["socialize"] > baseline["allScores"]["socialize"]
    assert "relationship" in {
        factor["kind"] for factor in connected["factorBreakdown"]["socialize"]
    }

    care = score_candidate_actions(
        {"needs": _needs(80), "care": {"required": True, "dependentCount": 1}}
    )
    assert care["decision"] == "secure_childcare"
    assert care["factorBreakdown"]["secure_childcare"][0]["kind"] == "care"

    hungry = _needs(75)
    hungry["hunger"] = 4
    closed = score_candidate_actions(
        {"needs": hungry, "venueHours": {"eat_meal": {"openNow": False}}}
    )
    assert "eat_meal" in closed["blockedActions"]
    assert closed["decision"] != "eat_meal"


def test_ordinary_actions_cannot_repeat_indefinitely() -> None:
    history: list[str] = []
    for tick in range(60):
        result = score_candidate_actions(
            {
                "needs": _needs(),
                "hour": 15,
                "currentAction": history[-1] if history else None,
                "actionHistory": history,
                "maxOrdinaryRepeats": 3,
            },
            seed=tick,
        )
        history.append(result["decision"])

    longest_run = max(len(list(group)) for _, group in groupby(history))
    assert longest_run <= 3

    repeated = score_candidate_actions(
        {
            "needs": _needs(),
            "currentAction": "have_fun",
            "actionHistory": ["have_fun"] * 3,
        },
        seed=9,
    )
    assert "have_fun" in repeated["blockedActions"]
    assert repeated["decision"] != "have_fun"


def test_urgent_needs_override_fatigue_and_cooldown() -> None:
    needs = _needs(75)
    needs["health"] = 0
    result = score_candidate_actions(
        {
            "needs": needs,
            "currentAction": "seek_healthcare",
            "actionHistory": ["seek_healthcare"] * 6,
            "cooldowns": {"seek_healthcare": 20},
            "actionFatigue": {"seek_healthcare": 100},
        }
    )
    assert result["decision"] == "seek_healthcare"
    assert "seek_healthcare" not in result["blockedActions"]
    kinds = {factor["kind"] for factor in result["factorBreakdown"]["seek_healthcare"]}
    assert {"urgency", "fatigue", "cooldown"} <= kinds


def test_public_thoughts_vary_but_only_summarize_supplied_factors() -> None:
    state = {
        "needs": {**_needs(95), "purpose": 2},
        "goals": [{"status": "active", "targetAction": "pursue_purpose", "priority": 100}],
        "memories": [{"content": "PRIVATE MEMORY WORDS", "salience": 100, "valence": 80}],
    }
    thoughts = {score_candidate_actions(state, seed=index)["ponder"] for index in range(20)}
    assert len(thoughts) >= 2
    assert all("PRIVATE MEMORY WORDS" not in thought for thought in thoughts)
    assert all(
        any(word in thought.casefold() for word in ("goal", "purpose", "progress", "urgent"))
        for thought in thoughts
    )


def test_health_condition_severity_and_treatment_cost_are_explicit() -> None:
    state = {"needs": _needs(80), "hour": 2}
    baseline = score_candidate_actions(state)
    affordable = score_candidate_actions(
        {
            **state,
            "healthConditions": [
                {
                    "status": "active",
                    "severity": 82,
                    "treatmentRequired": True,
                    "treatmentCostCents": 5_000,
                }
            ],
            "finances": {"cashCents": 100_000},
        }
    )
    expensive = score_candidate_actions(
        {
            **state,
            "health": {
                "conditions": [
                    {"status": "active", "severity": 82, "treatmentCost": 800}
                ]
            },
            "finances": {"cash": 100},
        }
    )

    assert affordable["allScores"]["seek_healthcare"] > baseline["allScores"]["seek_healthcare"] + 35
    assert expensive["allScores"]["seek_healthcare"] < affordable["allScores"]["seek_healthcare"]
    factors = {
        factor["key"]: factor["weight"]
        for factor in expensive["factorBreakdown"]["seek_healthcare"]
        if factor["kind"] == "health_condition"
    }
    assert factors["condition_severity"] > 0
    assert factors["treatment_cost"] < 0


def test_severe_condition_overrides_healthcare_cooldown() -> None:
    result = score_candidate_actions(
        {
            "needs": _needs(80),
            "healthConditions": [
                {"status": "active", "severity": 90, "treatmentRequired": True}
            ],
            "currentAction": "seek_healthcare",
            "actionHistory": ["seek_healthcare"] * 4,
            "cooldowns": {"seek_healthcare": {"remainingTicks": 10}},
        }
    )

    assert result["decision"] == "seek_healthcare"
    assert "seek_healthcare" not in result["blockedActions"]
    factors = result["factorBreakdown"]["seek_healthcare"]
    assert any(factor["kind"] == "urgency" and factor["key"] == "condition_severity" for factor in factors)
    assert any(factor["kind"] == "cooldown" and factor["key"] == "urgent_override" for factor in factors)


def test_durable_relationship_dimensions_have_action_specific_effects() -> None:
    relationships = {
        "friend": {
            "respect": 90,
            "affection": 95,
            "attraction": 85,
            "commitment": 90,
            "resentment": 70,
        }
    }
    result = score_candidate_actions(
        {"needs": _needs(), "hour": 19, "relationships": relationships},
        seed="durable-ties",
    )
    repeated = score_candidate_actions(
        {"needs": _needs(), "hour": 19, "relationships": relationships},
        seed="durable-ties",
    )

    assert result == repeated
    social = {
        factor["key"]: factor["weight"]
        for factor in result["factorBreakdown"]["socialize"]
        if factor["kind"] == "relationship"
    }
    assert {"respect", "affection", "attraction", "commitment", "resentment"} <= social.keys()
    assert all(social[key] > 0 for key in ("respect", "affection", "attraction", "commitment"))
    assert social["resentment"] < 0
    privacy = {
        factor["key"]: factor["weight"]
        for factor in result["factorBreakdown"]["get_privacy"]
        if factor["kind"] == "relationship"
    }
    assert privacy["resentment"] > 0


def test_inertia_bonus_yields_to_fatigue_and_explicit_cooldown() -> None:
    state = {"needs": _needs(70), "hour": 15}
    baseline = score_candidate_actions(state)
    continuing = score_candidate_actions({**state, "currentAction": "pursue_purpose"})
    tiring = score_candidate_actions(
        {
            **state,
            "currentAction": "pursue_purpose",
            "actionHistory": ["pursue_purpose", "pursue_purpose"],
        }
    )
    cooled_down = score_candidate_actions(
        {**state, "cooldowns": {"pursue_purpose": {"remaining": 2}}}
    )

    assert continuing["allScores"]["pursue_purpose"] == baseline["allScores"]["pursue_purpose"] + 6
    assert any(
        factor["kind"] == "inertia"
        for factor in continuing["factorBreakdown"]["pursue_purpose"]
    )
    assert tiring["allScores"]["pursue_purpose"] < baseline["allScores"]["pursue_purpose"]
    assert "pursue_purpose" in cooled_down["blockedActions"]
    assert cooled_down["decision"] != "pursue_purpose"


def test_validated_model_preferences_are_only_bounded_nudges() -> None:
    baseline = score_candidate_actions({"needs": _needs(70)})
    preferred = score_candidate_actions(
        {
            "needs": _needs(70),
            "preferredAction": "pursue_purpose",
            "preferenceTags": ["useful work"],
        }
    )
    delta = preferred["allScores"]["pursue_purpose"] - baseline["allScores"]["pursue_purpose"]
    assert delta == 12
    assert any(
        factor["kind"] == "intention" and factor["key"] == "preferred_action"
        for factor in preferred["factorBreakdown"]["pursue_purpose"]
    )
