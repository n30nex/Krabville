"""Deterministic, JSON-shaped simulation primitives for KVsim 2.0.

All needs use one rule: 100 is fully satisfied and 0 is urgent.  The module is
deliberately independent of the database so ``world.py`` can adopt it a piece
at a time.
"""

from __future__ import annotations

import math
from typing import Any


NEED_NAMES = (
    "energy",
    "hunger",
    "hygiene",
    "health",
    "comfort",
    "safety",
    "fun",
    "social",
    "belonging",
    "privacy",
    "purpose",
    "autonomy",
    "financial_security",
)

DEFAULT_NEEDS = {name: 72.0 for name in NEED_NAMES}

_BASE_DECAY = {
    "energy": 0.22,
    "hunger": 0.30,
    "hygiene": 0.08,
    "health": 0.01,
    "comfort": 0.08,
    "safety": 0.02,
    "fun": 0.12,
    "social": 0.10,
    "belonging": 0.035,
    "privacy": 0.04,
    "purpose": 0.07,
    "autonomy": 0.05,
    "financial_security": 0.005,
}

_STAGE_DECAY = {
    "baby": {"energy": 1.55, "hunger": 1.65, "hygiene": 1.45, "health": 1.25, "safety": 1.35},
    "child": {"energy": 1.20, "hunger": 1.20, "hygiene": 1.15, "fun": 1.25, "social": 1.15},
    "teen": {"energy": 1.10, "hunger": 1.10, "social": 1.20, "privacy": 1.25, "autonomy": 1.30},
    "adult": {},
    "senior": {"energy": 1.25, "health": 1.45, "comfort": 1.20, "safety": 1.20},
}

_ACTIVITY_EFFECTS = {
    "sleep": {"energy": 2.50, "health": 0.16, "comfort": 0.35, "privacy": 0.12},
    "eat": {"hunger": 2.80, "comfort": 0.28, "health": 0.08},
    "wash": {"hygiene": 3.20, "comfort": 0.20},
    "healthcare": {"health": 1.80, "safety": 0.35, "comfort": 0.15},
    "relax": {"comfort": 1.20, "fun": 0.60, "privacy": 0.55, "energy": 0.20},
    "shelter": {"safety": 1.45, "comfort": 0.70},
    "play": {"fun": 1.85, "autonomy": 0.45, "energy": -0.20},
    "socialize": {"social": 1.75, "belonging": 0.70, "fun": 0.35, "privacy": -0.25},
    "community": {"belonging": 1.45, "social": 0.65, "purpose": 0.45},
    "solitude": {"privacy": 1.70, "autonomy": 0.55, "comfort": 0.25, "social": -0.10},
    "purpose": {"purpose": 1.40, "autonomy": 0.35, "fun": 0.12, "energy": -0.18},
    "independent": {"autonomy": 1.55, "fun": 0.35, "purpose": 0.18},
    "work": {"financial_security": 0.95, "purpose": 0.75, "autonomy": -0.18, "energy": -0.18},
    "caregiving": {"belonging": 0.90, "purpose": 0.75, "social": 0.40, "energy": -0.24},
}

_ACTIVITY_ALIASES = {
    "sleep": ("sleep", "nap", "rest in bed"),
    "eat": ("eat", "meal", "breakfast", "lunch", "dinner", "supper", "bottle", "feeding", "snack"),
    "wash": ("wash", "shower", "bath", "hygiene", "changing", "diaper"),
    "healthcare": ("doctor", "clinic", "hospital", "healthcare", "recovering"),
    "relax": ("relax", "reading", "coffee", "quiet at home"),
    "shelter": ("shelter", "seeking safety", "staying inside"),
    "play": ("play", "game", "hobby", "recreation", "exercise"),
    "socialize": ("social", "neighbour", "friend", "conversation", "date"),
    "community": ("community", "festival", "volunteer", "town event"),
    "solitude": ("solitude", "alone", "private time"),
    "purpose": ("project", "study", "school", "creative"),
    "independent": ("independent", "explore", "personal choice"),
    "work": ("work", "job", "shift", "business"),
    "caregiving": ("caregiving", "childcare", "caring for"),
}

_NEED_WEIGHTS = {
    "energy": 1.10,
    "hunger": 1.05,
    "hygiene": 0.70,
    "health": 1.30,
    "comfort": 0.75,
    "safety": 1.30,
    "fun": 0.70,
    "social": 0.85,
    "belonging": 0.95,
    "privacy": 0.65,
    "purpose": 0.95,
    "autonomy": 0.90,
    "financial_security": 1.15,
}

_ACTION_BY_NEED = {
    "energy": ("restore_energy", "Get some sleep", "I need to slow down and get some sleep."),
    "hunger": ("eat_meal", "Eat a proper meal", "Food first, then I can think clearly."),
    "hygiene": ("wash_up", "Wash up", "I would feel much better after washing up."),
    "health": ("seek_healthcare", "Look after my health", "This is not something I should ignore."),
    "comfort": ("get_comfortable", "Find somewhere comfortable", "I want somewhere warm and familiar for a while."),
    "safety": ("seek_safety", "Get somewhere safe", "I should get out of harm's way."),
    "fun": ("have_fun", "Do something enjoyable", "I need something fun before the day gets away from me."),
    "social": ("socialize", "Spend time with someone", "I wonder who is around right now."),
    "belonging": ("join_community", "Reconnect with the community", "I want to feel part of things again."),
    "privacy": ("get_privacy", "Find some private space", "I need a little time where nobody needs me."),
    "purpose": ("pursue_purpose", "Make meaningful progress", "I should do one thing that really matters to me."),
    "autonomy": ("reclaim_autonomy", "Make my own choice", "I want this next choice to be mine."),
    "financial_security": ("improve_finances", "Improve my finances", "I need to make the numbers feel safer."),
}


def _number(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def normalize_needs(needs: dict[str, Any]) -> dict[str, float]:
    """Return all v2 needs, clamped to 0..100 with high meaning satisfied."""

    return {
        name: round(_clamp(_number(needs.get(name), DEFAULT_NEEDS[name])), 2)
        for name in NEED_NAMES
    }


def _activity_kind(activity: Any) -> str:
    text = str(activity or "").casefold()
    for kind, aliases in _ACTIVITY_ALIASES.items():
        if any(alias in text for alias in aliases):
            return kind
    return "idle"


def update_needs(state: dict[str, Any]) -> dict[str, Any]:
    """Decay and recover needs for one bounded simulation interval."""

    before = normalize_needs(dict(state.get("needs") or {}))
    minutes = _clamp(_number(state.get("elapsedMinutes"), 5.0), 0.0, 1_440.0)
    factor = minutes / 5.0
    stage = str(state.get("lifeStage") or "adult").casefold()
    stage_decay = _STAGE_DECAY.get(stage, _STAGE_DECAY["adult"])
    activity = _activity_kind(state.get("activity"))
    deltas = {
        name: -_BASE_DECAY[name] * stage_decay.get(name, 1.0) * factor
        for name in NEED_NAMES
    }
    for name, effect in _ACTIVITY_EFFECTS.get(activity, {}).items():
        deltas[name] += effect * factor

    weather = dict(state.get("weather") or {})
    condition = str(weather.get("condition") or "clear").casefold()
    activity_text = str(state.get("activity") or "").casefold()
    outdoors = bool(state.get("outdoors", any(word in activity_text for word in ("walk", "outside", "garden", "dock"))))
    temperature = _number(weather.get("temperatureC"), 21.0)
    if outdoors and condition in {"rain", "storm", "snow", "first-snow", "fog"}:
        severity = 1.0 if condition in {"rain", "fog"} else 1.8
        deltas["comfort"] -= 0.30 * severity * factor
        deltas["safety"] -= 0.24 * severity * factor
        deltas["hygiene"] -= 0.10 * severity * factor
    if outdoors and (temperature < 5 or temperature > 31):
        severity = min(2.0, abs(temperature - (5 if temperature < 5 else 31)) / 10 + 0.5)
        deltas["health"] -= 0.12 * severity * factor
        deltas["comfort"] -= 0.28 * severity * factor
        deltas["energy"] -= 0.12 * severity * factor

    health_data = dict(state.get("health") or {})
    illness = _clamp(_number(health_data.get("severity"), 0.0)) / 100.0
    illness = max(illness, (100.0 - before["health"]) / 200.0)
    if illness:
        deltas["energy"] -= 0.65 * illness * factor
        deltas["comfort"] -= 0.42 * illness * factor
        deltas["fun"] -= 0.30 * illness * factor
        deltas["autonomy"] -= 0.20 * illness * factor

    crowding = _clamp(_number(state.get("crowding"), 0.0)) / 100.0
    deltas["privacy"] -= 0.50 * crowding * factor
    after = {
        name: round(_clamp(before[name] + deltas[name]), 2)
        for name in NEED_NAMES
    }
    actual = {name: round(after[name] - before[name], 2) for name in NEED_NAMES}
    drivers = [
        {"need": name, "delta": delta}
        for name, delta in sorted(actual.items(), key=lambda item: (-abs(item[1]), item[0]))
        if delta
    ][:4]
    return {"needs": after, "deltas": actual, "activity": activity, "drivers": drivers}


def derive_mood(state: dict[str, Any]) -> dict[str, Any]:
    """Derive a compact mood from needs and current situational stress."""

    needs = normalize_needs(dict(state.get("needs") or {}))
    total_weight = sum(_NEED_WEIGHTS.values())
    satisfaction = sum(needs[name] * _NEED_WEIGHTS[name] for name in NEED_NAMES) / total_weight
    event_stress = _clamp(_number(state.get("eventStress"), 0.0))
    stress_needs = ("health", "safety", "financial_security", "autonomy", "privacy")
    stress = sum(100.0 - needs[name] for name in stress_needs) / len(stress_needs)
    stress = _clamp(stress * 0.78 + event_stress * 0.45)
    valence = _clamp((satisfaction - 50.0) * 2.0 - event_stress * 0.25, -100.0, 100.0)
    arousal = _clamp(24.0 + stress * 0.48 + (100.0 - needs["energy"]) * 0.25)
    deficits = sorted(NEED_NAMES, key=lambda name: (needs[name], NEED_NAMES.index(name)))
    worst = deficits[0]
    if needs["health"] < 25:
        label = "unwell"
    elif needs["safety"] < 25:
        label = "afraid"
    elif needs["energy"] < 20:
        label = "exhausted"
    elif needs["social"] < 25 or needs["belonging"] < 25:
        label = "lonely"
    elif needs["fun"] < 25:
        label = "bored"
    elif needs["purpose"] < 25:
        label = "aimless"
    elif needs["financial_security"] < 25:
        label = "worried"
    elif satisfaction >= 82 and stress < 22:
        label = "content"
    elif satisfaction >= 66:
        label = "steady"
    elif satisfaction >= 46:
        label = "strained"
    else:
        label = "distressed"
    return {
        "label": label,
        "valence": round(valence, 2),
        "arousal": round(arousal, 2),
        "stress": round(stress, 2),
        "satisfaction": round(satisfaction, 2),
        "dominantNeed": worst,
        "drivers": [{"need": name, "value": needs[name]} for name in deficits[:3]],
    }


def generate_short_term_wants(state: dict[str, Any]) -> dict[str, Any]:
    """Create deterministic, need-led wants suitable for a resident docket."""

    needs = normalize_needs(dict(state.get("needs") or {}))
    limit = int(_clamp(_number(state.get("limit"), 3.0), 1.0, 6.0))
    wants = []
    for order, name in enumerate(NEED_NAMES):
        action, label, thought = _ACTION_BY_NEED[name]
        urgency = (100.0 - needs[name]) * _NEED_WEIGHTS[name]
        wants.append(
            {
                "kind": action,
                "label": label,
                "priority": round(urgency, 2),
                "sourceNeed": name,
                "thought": thought,
                "expiresInMinutes": 60 if needs[name] < 25 else 180 if needs[name] < 55 else 360,
                "_order": order,
            }
        )
    wants.sort(key=lambda want: (-want["priority"], want["_order"]))
    for want in wants:
        want.pop("_order")
    return {"wants": wants[:limit], "dominantNeed": wants[0]["sourceNeed"]}


def _schedule_bonus(need: str, state: dict[str, Any]) -> float:
    hour = _number(state.get("hour"), 12.0) % 24
    meal = 6.5 <= hour < 8.5 or 11.5 <= hour < 13.5 or 17.5 <= hour < 20
    work = 8 <= hour < 12 or 13 <= hour < 17.5
    evening = 17 <= hour < 22
    sleep = hour >= 22 or hour < 6
    bonuses = {
        "energy": 46.0 if sleep else 0.0,
        "hunger": 34.0 if meal else 0.0,
        "hygiene": 14.0 if 6 <= hour < 8 or 20 <= hour < 22 else 0.0,
        "health": 12.0 if 8 <= hour < 18 else 0.0,
        "fun": 12.0 if evening else 0.0,
        "social": 15.0 if evening else 0.0,
        "purpose": 27.0 if work else 0.0,
        "financial_security": 30.0 if work else -12.0,
        "privacy": 10.0 if evening else 0.0,
    }
    return bonuses.get(need, 0.0)


def score_candidate_actions(state: dict[str, Any]) -> dict[str, Any]:
    """Rank need-led actions and return the three most useful choices."""

    needs = normalize_needs(dict(state.get("needs") or {}))
    wants = list(state.get("wants") or generate_short_term_wants({"needs": needs, "limit": 6})["wants"])
    want_boost = {
        str(want.get("sourceNeed")): _clamp(_number(want.get("priority"), 0.0)) * 0.24
        for want in wants
        if isinstance(want, dict)
    }
    condition = str(dict(state.get("weather") or {}).get("condition") or "clear").casefold()
    nearby = _clamp(_number(state.get("nearbyResidents"), 0.0), 0.0, 20.0)
    crowding = _clamp(_number(state.get("crowding"), nearby * 8.0))
    debt = max(0.0, _number(dict(state.get("finances") or {}).get("debt"), 0.0))
    event = dict(state.get("event") or {})
    stage = str(state.get("lifeStage") or "adult").casefold()
    choices = []
    for order, need in enumerate(NEED_NAMES):
        action, label, thought = _ACTION_BY_NEED[need]
        deficit = 100.0 - needs[need]
        score = deficit * _NEED_WEIGHTS[need] + max(0.0, 35.0 - needs[need]) * 0.65
        score += _schedule_bonus(need, state) + want_boost.get(need, 0.0)
        if need == "comfort" and condition in {"rain", "storm", "snow", "first-snow"}:
            score += 22.0
        elif need == "safety" and condition in {"storm", "first-snow"}:
            score += 30.0
        elif need == "social":
            score += min(14.0, nearby * 3.0)
        elif need == "privacy":
            score += crowding * 0.28
        elif need == "belonging" and event:
            score += _clamp(_number(event.get("salience"), 30.0)) * 0.28
        elif need == "financial_security":
            score += min(35.0, debt / 100.0)
        if stage in {"baby", "child"} and need == "financial_security":
            label = "Find caregiver support"
            thought = "I need a grown-up I trust to make this feel secure."
        elif stage in {"baby", "child", "teen"} and need == "purpose":
            label = "Learn or practise something"
        current = str(state.get("currentAction") or "")
        if current == action:
            score += 5.0
        choices.append(
            {
                "action": action,
                "label": label,
                "score": round(max(0.0, score), 2),
                "primaryNeed": need,
                "needValue": needs[need],
                "thought": thought,
                "_order": order,
            }
        )

    dependents = int(max(0.0, _number(state.get("uncoveredDependents"), 0.0)))
    if dependents:
        choices.append(
            {
                "action": "secure_childcare",
                "label": "Make sure the children are cared for",
                "score": round(105.0 + dependents * 18.0, 2),
                "primaryNeed": "safety",
                "needValue": needs["safety"],
                "thought": "I cannot leave until I know the children are safe with someone.",
                "_order": len(choices),
            }
        )
    choices.sort(key=lambda choice: (-choice["score"], choice["_order"]))
    top = choices[:3]
    peak = top[0]["score"]
    weights = [math.exp((choice["score"] - peak) / 18.0) for choice in top]
    weight_total = sum(weights)
    for rank, (choice, weight) in enumerate(zip(top, weights, strict=True), 1):
        choice["rank"] = rank
        choice["confidence"] = round(weight / weight_total * 100.0, 1)
        choice.pop("_order")
    all_scores = {choice["action"]: choice["score"] for choice in choices}
    return {
        "choices": top,
        "decision": top[0]["action"],
        "ponder": top[0]["thought"],
        "allScores": all_scores,
    }


def boredom_score(state: dict[str, Any]) -> dict[str, Any]:
    """Score how badly the town needs a director-injected catalyst."""

    quiet = _clamp(_number(state.get("minutesSinceMeaningfulEvent"), 0.0), 0.0, 1_440.0)
    repetition = _clamp(_number(state.get("routineRepetition"), 0.0), 0.0, 1.0)
    meaningful = max(0.0, _number(state.get("meaningfulEvents"), 0.0))
    changes = max(0.0, _number(state.get("activityChanges"), 0.0))
    conversations = max(0.0, _number(state.get("conversations"), 0.0))
    conflicts = max(0.0, _number(state.get("conflicts"), 0.0))
    goal_progress = max(0.0, _number(state.get("goalProgress"), 0.0))
    relationship_changes = max(0.0, _number(state.get("relationshipChanges"), 0.0))
    score = 18.0 + min(48.0, quiet / 10.0) + repetition * 32.0
    score -= meaningful * 18.0 + changes * 1.5 + conversations * 3.0
    score -= conflicts * 12.0 + goal_progress * 0.35 + relationship_changes * 9.0
    score = round(_clamp(score), 2)
    reasons = []
    if quiet >= 180:
        reasons.append("nothing consequential has happened recently")
    if repetition >= 0.65:
        reasons.append("routines are repeating")
    if meaningful + conflicts + relationship_changes == 0:
        reasons.append("no story thread is moving")
    if score < 45:
        reasons = ["current resident activity is carrying the story"]
    return {
        "score": score,
        "level": "high" if score >= 70 else "medium" if score >= 45 else "low",
        "shouldDirect": score >= 70,
        "reasons": reasons[:3],
    }


def family_intent(state: dict[str, Any]) -> dict[str, Any]:
    """Return a realistic family priority while respecting population limits."""

    resident = dict(state.get("resident") or {})
    household = dict(state.get("household") or {})
    population = dict(state.get("population") or {})
    needs = normalize_needs(dict(resident.get("needs") or state.get("needs") or {}))
    stage = str(resident.get("lifeStage") or "adult").casefold()
    living = int(max(0.0, _number(population.get("living"), 0.0)))
    cap = int(max(1.0, _number(population.get("cap"), 32.0)))
    minors = int(max(0.0, _number(population.get("minors"), 0.0)))
    minor_cap = int(max(0.0, _number(population.get("minorCap"), cap)))
    dependents = household.get("dependents") or []
    dependent_count = len(dependents) if isinstance(dependents, list) else int(max(0.0, _number(dependents)))
    coverage = _number(household.get("caregiverCoverage"), 1.0)
    coverage = _clamp(coverage * 100.0 if coverage <= 1.0 else coverage) / 100.0
    disposable = _number(household.get("monthlyDisposableIncome"), 0.0)
    childcare_cost = max(0.0, _number(household.get("monthlyChildcareCost"), 900.0))
    room = max(0, cap - living)
    minor_room = max(0, minor_cap - minors)
    capacity = {"living": living, "cap": cap, "remaining": room, "minorRemaining": minor_room}

    if dependent_count and coverage < 1.0:
        if disposable >= childcare_cost:
            intent = "hire_caregiver"
            reason = "care coverage is missing and the household can afford paid help"
        elif _number(household.get("familySupport"), 0.0) >= 55:
            intent = "ask_family_for_childcare"
            reason = "care coverage is missing and trusted family support is available"
        else:
            intent = "take_family_leave"
            reason = "a caregiver must stay home until safe care is arranged"
        return {
            "intent": intent,
            "score": round(100.0 - coverage * 40.0, 2),
            "reason": reason,
            "allowsFamilyGrowth": False,
            "population": capacity,
        }

    if stage != "adult":
        return {
            "intent": "no_family_growth",
            "score": 0.0,
            "reason": "family growth decisions belong to adults",
            "allowsFamilyGrowth": False,
            "population": capacity,
        }
    if room == 0 or minor_room == 0:
        return {
            "intent": "defer_family_growth",
            "score": 0.0,
            "reason": "the stable population limit has been reached",
            "allowsFamilyGrowth": False,
            "population": capacity,
        }

    desire = _clamp(_number(resident.get("familyDesire"), 35.0))
    relationship = dict(resident.get("relationship") or {})
    commitment = _clamp(_number(relationship.get("commitment"), 35.0))
    trust = _clamp(_number(relationship.get("trust"), 50.0))
    housing_capacity = int(max(0.0, _number(household.get("housingCapacity"), 1.0)))
    members = int(max(0.0, _number(household.get("members"), 1.0)))
    housing = 100.0 if housing_capacity > members else 25.0
    support = _clamp(_number(household.get("familySupport"), 40.0))
    score = (
        desire * 0.30
        + needs["health"] * 0.10
        + needs["safety"] * 0.08
        + needs["financial_security"] * 0.15
        + needs["autonomy"] * 0.07
        + commitment * 0.10
        + trust * 0.08
        + housing * 0.07
        + support * 0.05
    )
    score = round(_clamp(score), 2)
    if score >= 68:
        intent = "consider_family_growth"
        reason = "desire, stability, care, and housing make growth realistic"
    elif score >= 48:
        intent = "discuss_future_family"
        reason = "the idea is plausible but important conditions remain unsettled"
    else:
        intent = "no_change"
        reason = "current needs and circumstances outweigh family growth"
    return {
        "intent": intent,
        "score": score,
        "reason": reason,
        "allowsFamilyGrowth": intent == "consider_family_growth",
        "population": capacity,
    }
