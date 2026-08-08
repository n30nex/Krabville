from __future__ import annotations

from copy import deepcopy
import json
import re

import pytest

from krabville.population_v2 import (
    MAX_ADULTS,
    MAX_LIVING,
    PopulationLimitError,
    advance_lifecycle,
    enforce_population_caps,
    generate_starting_population,
)


def test_starting_population_is_deterministic_json_and_has_exact_shape() -> None:
    first = generate_starting_population("season-one-v2")
    second = generate_starting_population("season-one-v2")

    assert first == second
    assert first != generate_starting_population("another-season")
    json.dumps(first)
    assert first["counts"] == {"living": 12, "adults": 8, "minors": 4}
    assert len(first["households"]) == 6
    assert [resident["life"]["stage"] for resident in first["residents"]].count("adult") == 8
    assert sorted(resident["life"]["stage"] for resident in first["residents"][8:]) == [
        "baby",
        "child",
        "child",
        "teen",
    ]
    slugs = [resident["slug"] for resident in first["residents"]]
    assert len(slugs) == len(set(slugs))
    assert all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) for slug in slugs)


def test_households_encode_partnerships_and_minor_care() -> None:
    population = generate_starting_population(20260808)
    residents = {resident["slug"]: resident for resident in population["residents"]}
    families = [household for household in population["households"] if household["kind"] == "family"]

    assert sorted(len(household["memberSlugs"]) for household in families) == [2, 3, 4]
    assert sorted(household["partnership"] for household in families) == [
        "committed",
        "married",
        "single",
    ]
    for household in families:
        assert len(household["caregiverPlan"]) == len(household["minorSlugs"])
        for minor_slug in household["minorSlugs"]:
            minor = residents[minor_slug]
            assert minor["care"]["requiresCare"] is True
            assert minor["parentSlugs"]
            assert set(minor["parentSlugs"]) <= set(household["adultSlugs"])
            assert set(minor["care"]["primaryCaregiverSlugs"]) == set(minor["parentSlugs"])

    baby = next(resident for resident in residents.values() if resident["life"]["stage"] == "baby")
    baby_home = next(household for household in families if baby["slug"] in household["minorSlugs"])
    plan = next(item for item in baby_home["caregiverPlan"] if item["minorSlug"] == baby["slug"])
    assert plan["arrangement"] == "parental leave"
    assert any(residents[parent]["career"]["status"] == "parental-leave" for parent in baby["parentSlugs"])


def test_children_inherit_traits_and_genetic_appearance() -> None:
    population = generate_starting_population("inheritance")
    residents = {resident["slug"]: resident for resident in population["residents"]}
    minors = [resident for resident in residents.values() if resident["householdRole"] == "minor"]

    for child in minors:
        parents = [residents[slug] for slug in child["parentSlugs"]]
        for trait, value in child["traits"].items():
            parent_average = sum(parent["traits"][trait] for parent in parents) / len(parents)
            assert abs(value - parent_average) <= 8.5
        for feature, source_slug in child["appearance"]["inheritedFrom"].items():
            assert source_slug in child["parentSlugs"]
            assert child["appearance"][feature] == residents[source_slug]["appearance"][feature]


def test_lifecycle_transitions_and_mortality_rules() -> None:
    baby = next(
        resident
        for resident in generate_starting_population("lifecycle")["residents"]
        if resident["life"]["stage"] == "baby"
    )

    child = advance_lifecycle(baby, adult_mortality_risk=1.0, mortality_roll=0.0)
    teen = advance_lifecycle(child, adult_mortality_risk=1.0, mortality_roll=0.0)
    adult = advance_lifecycle(teen, adult_mortality_risk=1.0, mortality_roll=0.0)
    assert [child["life"]["stage"], teen["life"]["stage"], adult["life"]["stage"]] == [
        "child",
        "teen",
        "adult",
    ]
    assert child["life"]["alive"] and teen["life"]["alive"] and adult["life"]["alive"]

    senior = advance_lifecycle(adult, 4)
    assert senior["life"]["stage"] == "senior"
    assert senior["life"]["adultSeasons"] == 4
    deceased = advance_lifecycle(senior, 2)
    assert deceased["life"]["alive"] is False
    assert deceased["life"]["deathCause"] == "natural old age"

    at_risk_adult = advance_lifecycle(adult, adult_mortality_risk=0.005, mortality_roll=0.004)
    assert at_risk_adult["life"]["alive"] is False
    assert at_risk_adult["life"]["deathCause"] == "rare adult illness or accident"


def _resident(stage: str, index: int) -> dict:
    return {
        "slug": f"resident-{stage}-{index}",
        "life": {"stage": stage, "alive": True},
    }


def test_population_caps_allow_boundary_and_reject_overflow() -> None:
    boundary = [_resident("adult", index) for index in range(MAX_ADULTS // 2)]
    boundary.extend(_resident("senior", index) for index in range(MAX_ADULTS // 2))
    boundary.extend(_resident("child", index) for index in range(MAX_LIVING - MAX_ADULTS))
    boundary.append({"slug": "former-resident", "life": {"stage": "senior", "alive": False}})
    assert enforce_population_caps(boundary) == {"living": 32, "adults": 24, "minors": 8}

    too_many_living = deepcopy(boundary)
    too_many_living.append(_resident("baby", 99))
    with pytest.raises(PopulationLimitError, match="living population 33"):
        enforce_population_caps(too_many_living)

    too_many_adults = [_resident("adult", index) for index in range(MAX_ADULTS + 1)]
    with pytest.raises(PopulationLimitError, match="adult population 25"):
        enforce_population_caps(too_many_adults)
