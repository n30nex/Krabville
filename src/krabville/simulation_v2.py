"""Deterministic, JSON-shaped simulation primitives for KVsim 2.0.

All needs use one rule: 100 is fully satisfied and 0 is urgent.  The module is
deliberately independent of the database so ``world.py`` can adopt it a piece
at a time.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
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

_ACTION_TERMS = {
    "restore_energy": ("sleep", "rest", "nap", "bed"),
    "eat_meal": ("eat", "meal", "food", "cook", "breakfast", "lunch", "dinner"),
    "wash_up": ("wash", "hygiene", "shower", "bath", "soap"),
    "seek_healthcare": ("health", "doctor", "clinic", "medicine", "recover"),
    "get_comfortable": ("comfort", "relax", "home", "warm", "quiet"),
    "seek_safety": ("safety", "safe", "shelter", "danger"),
    "have_fun": ("fun", "play", "game", "hobby", "music", "entertainment"),
    "socialize": ("social", "friend", "talk", "call", "visit", "date"),
    "join_community": ("community", "volunteer", "neighbour", "festival", "belong"),
    "get_privacy": ("privacy", "alone", "solitude", "private", "quiet"),
    "pursue_purpose": ("purpose", "goal", "study", "project", "create", "practice", "practise"),
    "reclaim_autonomy": ("autonomy", "independent", "choice", "explore", "personal"),
    "improve_finances": ("finance", "money", "work", "job", "shift", "business", "debt"),
    "secure_childcare": ("care", "childcare", "caregiver", "dependent", "school pickup"),
}

_TRAIT_EFFECTS = {
    "restore_energy": (("conscientiousness",), 0.05),
    "wash_up": (("conscientiousness",), 0.08),
    "have_fun": (("openness", "spontaneity"), 0.10),
    "socialize": (("extraversion", "sociability"), 0.18),
    "join_community": (("agreeableness", "empathy"), 0.14),
    "get_privacy": (("extraversion", "sociability"), -0.12),
    "pursue_purpose": (("conscientiousness", "ambition", "openness"), 0.10),
    "reclaim_autonomy": (("openness", "spontaneity", "risk"), 0.09),
    "improve_finances": (("conscientiousness", "ambition"), 0.14),
    "secure_childcare": (("agreeableness", "empathy", "conscientiousness"), 0.10),
}

_NEED_LABELS = {name: name.replace("_", " ") for name in NEED_NAMES}


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


def _items(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if not isinstance(value, dict):
        return [] if value in (None, False, "") else [value]
    record_keys = {
        "action", "targetAction", "description", "content", "status", "priority",
        "affinity", "trust", "tension", "salience", "open", "openNow",
    }
    if record_keys.intersection(value):
        return [value]
    nested = [item for item in value.values() if isinstance(item, (dict, list, tuple, str))]
    return nested or [value]


def _text_blob(value: Any, depth: int = 0) -> str:
    if depth > 3 or value is None or isinstance(value, (bool, int, float)):
        return ""
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, dict):
        return " ".join(
            part
            for key, item in value.items()
            for part in (_text_blob(key, depth + 1), _text_blob(item, depth + 1))
            if part
        )
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text_blob(item, depth + 1) for item in value)
    return str(value).casefold()


def _matches_action(action: str, value: Any) -> bool:
    text = _text_blob(value)
    return action.casefold() in text or any(term in text for term in _ACTION_TERMS[action])


def _stable_seed(value: Any) -> int:
    try:
        material = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        material = repr(value)
    return int.from_bytes(hashlib.sha256(material.encode("utf-8", "replace")).digest()[:8], "big")


def _canonical_action(value: Any) -> str:
    text = str(value or "").casefold().strip()
    if text in _ACTION_TERMS:
        return text
    for action, terms in _ACTION_TERMS.items():
        if any(term in text for term in terms):
            return action
    return text


def _recent_actions(state: dict[str, Any]) -> list[str]:
    raw = state.get("actionHistory", state.get("recentActions", []))
    values = list(raw) if isinstance(raw, (list, tuple)) else []
    actions = [
        _canonical_action(item.get("action") if isinstance(item, dict) else item)
        for item in values
    ]
    actions = [action for action in actions if action]
    if state.get("historyNewestFirst"):
        actions.reverse()
    return actions


def _trailing_repeats(actions: list[str], action: str) -> int:
    count = 0
    for previous in reversed(actions):
        if previous != action:
            break
        count += 1
    return count


def _mapping_value(value: Any, action: str) -> Any:
    if not isinstance(value, dict):
        return None
    if action in value:
        return value[action]
    for key, item in value.items():
        if _canonical_action(key) == action:
            return item
    return None


def _active_cooldown(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _number(value) > 0
    if isinstance(value, dict):
        if value.get("active") is not None:
            return bool(value["active"])
        return any(_number(value.get(key), 0.0) > 0 for key in ("remaining", "remainingTicks", "minutes"))
    return False


def _clock_hour(value: Any) -> float | None:
    if isinstance(value, str) and ":" in value:
        hours, minutes, *_ = value.split(":") + ["0"]
        try:
            return (int(hours) % 24) + int(minutes) / 60.0
        except ValueError:
            return None
    if isinstance(value, (int, float)):
        return _number(value) % 24
    return None


def _venue_is_open(state: dict[str, Any], action: str) -> bool | None:
    venues = state.get("venueHours", state.get("venues"))
    record = _mapping_value(venues, action)
    if record is None:
        for item in _items(venues):
            if isinstance(item, dict) and _matches_action(action, item.get("action", item.get("kind", ""))):
                record = item
                break
    if record is None:
        return None
    if isinstance(record, bool):
        return record
    if isinstance(record, str):
        return record.casefold() not in {"closed", "unavailable", "false", "off"}
    if not isinstance(record, dict):
        return bool(record)
    for key in ("openNow", "isOpen", "available"):
        if key in record:
            return bool(record[key])
    if "open" in record and isinstance(record["open"], bool):
        return record["open"]
    opens = _clock_hour(record.get("opens", record.get("open")))
    closes = _clock_hour(record.get("closes", record.get("close")))
    if opens is None or closes is None:
        return None
    hour = _number(state.get("hour"), 12.0) % 24
    return opens <= hour < closes if opens < closes else hour >= opens or hour < closes


def _travel_penalty(state: dict[str, Any], action: str) -> float:
    travel = state.get("travel", state.get("travelCosts", state.get("travelMinutes")))
    value = _mapping_value(travel, action)
    if value is None:
        return 0.0
    if isinstance(value, dict):
        minutes = max(0.0, _number(value.get("minutes", value.get("durationMinutes")), 0.0))
        cost = max(0.0, _number(value.get("cost", value.get("costCents")), 0.0))
        if "costCents" in value:
            cost /= 100.0
        distance = max(0.0, _number(value.get("distanceKm"), 0.0))
        return min(30.0, minutes * 0.22 + cost * 0.08 + distance * 0.9)
    return min(25.0, max(0.0, _number(value)) * 0.22)


def _trait_bonus(traits: dict[str, Any], action: str) -> float:
    names, coefficient = _TRAIT_EFFECTS.get(action, ((), 0.0))
    values = []
    for name in names:
        aliases = (name, "extraversion") if name == "sociability" else (name,)
        found = next((traits[key] for key in aliases if key in traits), None)
        if found is not None:
            values.append(_clamp(_number(found, 50.0)))
    if not values:
        return 0.0
    return (sum(values) / len(values) - 50.0) * coefficient


def _relationship_effects(value: Any, action: str) -> list[tuple[str, float]]:
    records = [record for record in _items(value) if isinstance(record, dict)]
    coefficients = {
        "socialize": {
            "affinity": 0.10, "trust": 0.08, "respect": 0.05,
            "affection": 0.12, "attraction": 0.08, "commitment": 0.09,
            "familiarity": 0.04, "tension": -0.08, "resentment": -0.12,
        },
        "join_community": {
            "trust": 0.06, "respect": 0.10, "affection": 0.04,
            "commitment": 0.04, "familiarity": 0.06, "tension": -0.04,
            "resentment": -0.05,
        },
        "get_privacy": {"tension": 0.10, "resentment": 0.14},
        "seek_safety": {"tension": 0.08, "resentment": 0.10},
        "secure_childcare": {
            "trust": 0.08, "respect": 0.05, "affection": 0.05,
            "commitment": 0.12, "resentment": -0.06,
        },
    }.get(action, {})
    if not records or not coefficients:
        return []
    effects = []
    for dimension, coefficient in coefficients.items():
        values = [
            _clamp(_number(record[dimension], 0.0 if dimension in {"tension", "resentment"} else 50.0))
            for record in records
            if dimension in record
        ]
        if not values:
            continue
        average = sum(values) / len(values)
        centered = average if dimension in {"tension", "resentment"} else average - 50.0
        weight = centered * coefficient
        if abs(weight) >= 0.01:
            effects.append((dimension, weight))
    return effects


def _condition_severity(value: Any) -> float:
    severity = _number(value, 0.0)
    if 0 < severity <= 1:
        severity *= 100.0
    return _clamp(severity)


def _treatment_cost(record: dict[str, Any]) -> float:
    treatment = record.get("treatment") if isinstance(record.get("treatment"), dict) else {}
    if "treatmentCostCents" in record:
        return max(0.0, _number(record["treatmentCostCents"])) / 100.0
    if "costCents" in treatment:
        return max(0.0, _number(treatment["costCents"])) / 100.0
    for source, key in ((record, "treatmentCost"), (record, "estimatedCost"), (treatment, "cost")):
        if key in source:
            return max(0.0, _number(source[key]))
    return 0.0


def _healthcare_effects(state: dict[str, Any]) -> tuple[list[tuple[str, float]], bool]:
    health = state.get("health") if isinstance(state.get("health"), dict) else {}
    conditions = state.get("healthConditions")
    if conditions is None:
        conditions = health.get("conditions")
    if conditions is None and any(key in health for key in ("severity", "treatmentCost", "treatmentCostCents")):
        conditions = [health]

    active = []
    for condition in _items(conditions):
        record = condition if isinstance(condition, dict) else {"severity": condition}
        status = str(record.get("status", "active")).casefold()
        if record.get("active") is False or status in {"recovered", "resolved", "cured", "closed"}:
            continue
        active.append(record)
    if not active:
        return [], False

    severities = [
        _condition_severity(record.get("severity", record.get("severityScore", 0.0)))
        for record in active
    ]
    maximum = max(severities, default=0.0)
    combined = min(100.0, maximum + sum(sorted(severities, reverse=True)[1:]) * 0.20)
    severity_weight = combined * 0.62
    effects: list[tuple[str, float]] = [("condition_severity", severity_weight)]
    if len(active) > 1:
        effects.append(("active_conditions", min(8.0, (len(active) - 1) * 2.0)))
    if any(bool(record.get("contagious")) for record in active):
        effects.append(("contagiousness", 5.0))
    if any(bool(record.get("treatmentRequired", record.get("requiresTreatment", False))) for record in active):
        effects.append(("treatment_required", 8.0))

    gross_cost = sum(_treatment_cost(record) for record in active)
    coverage = _number(health.get("insuranceCoverage", state.get("insuranceCoverage")), 0.0)
    if coverage > 1:
        coverage /= 100.0
    effective_cost = gross_cost * (1.0 - _clamp(coverage, 0.0, 1.0))
    if effective_cost:
        finances = dict(state.get("finances") or {})
        if "cashCents" in finances:
            available = max(0.0, _number(finances["cashCents"])) / 100.0
        elif "balanceCents" in finances:
            available = max(0.0, _number(finances["balanceCents"])) / 100.0
        else:
            available = max(
                0.0,
                _number(finances.get("cash", finances.get("balance", finances.get("disposableIncome"))), 0.0),
            )
        burden = effective_cost / max(50.0, available if available else 100.0)
        effects.append(("treatment_cost", -min(28.0, 4.0 + burden * 14.0)))

    urgent_threshold = _clamp(_number(state.get("healthSeverityUrgentThreshold"), 65.0), 35.0, 90.0)
    emergency = any(bool(record.get("emergency")) for record in active)
    return effects, emergency or maximum >= urgent_threshold


def _memory_bonus(value: Any, action: str) -> float:
    total = 0.0
    for memory in _items(value):
        if not _matches_action(action, memory):
            continue
        record = memory if isinstance(memory, dict) else {}
        salience = _clamp(_number(record.get("salience"), 45.0))
        valence = _number(record.get("valence"), 20.0)
        direction = -0.65 if valence < 0 else 1.0
        total += min(9.0, salience * 0.09) * direction
    return _clamp(total, -16.0, 16.0)


def _goal_bonus(value: Any, action: str) -> float:
    total = 0.0
    for goal in _items(value):
        if isinstance(goal, dict) and str(goal.get("status", "active")).casefold() not in {"active", "open", "in_progress"}:
            continue
        if not _matches_action(action, goal):
            continue
        priority = _number(goal.get("priority"), 60.0) if isinstance(goal, dict) else 60.0
        total += 5.0 + _clamp(priority) * 0.14
    return min(26.0, total)


def _employment_bonus(value: Any, action: str, hour: float) -> float:
    if value in (None, ""):
        return 0.0
    record = value if isinstance(value, dict) else {}
    text = _text_blob(value)
    inactive = value is False or any(word in text for word in ("unemployed", "jobless", "inactive"))
    active = not inactive and (value is True or bool(record) or bool(text))
    on_shift = bool(record.get("onShift", record.get("workingNow", False)))
    scheduled = 8 <= hour < 12 or 13 <= hour < 17.5
    if action == "improve_finances":
        return 18.0 if on_shift else 11.0 if active and scheduled else 9.0 if inactive else 3.0
    if action == "pursue_purpose" and active:
        return 7.0 if scheduled else 3.0
    return 0.0


def _inventory_bonus(value: Any, action: str) -> float:
    if value in (None, "", [], {}):
        return 0.0
    return 8.0 if _matches_action(action, value) else 0.0


def _care_is_due(value: Any) -> bool:
    if not isinstance(value, dict):
        text = _text_blob(value)
        return any(word in text for word in ("due", "required", "uncovered", "handoff"))
    if any(bool(value.get(key)) for key in ("due", "required", "handoffDue", "uncovered")):
        return True
    dependents = _number(value.get("dependents", value.get("dependentCount")), 0.0)
    coverage = _number(value.get("coverage", value.get("caregiverCoverage")), 1.0)
    return dependents > 0 and coverage < 1.0


def _factor(kind: str, key: str, weight: float, explanation: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "key": key,
        "weight": round(weight, 2),
        "explanation": explanation,
    }


def _thought_for(choice: dict[str, Any], seed: Any) -> str:
    need = str(choice["primaryNeed"])
    label = str(choice["label"]).rstrip(".")
    factors = [factor for factor in choice["factors"] if factor["weight"] > 0]
    kinds = {factor["kind"] for factor in factors}
    if "care" in kinds:
        variants = (
            "Care comes first; I need to make sure everyone depending on me is covered.",
            "Someone needs care now, so I am sorting that out before anything else.",
            "I have a care duty to cover before I can move on with my day.",
        )
    elif "health_condition" in kinds:
        variants = (
            "My health condition needs proper attention, so I am seeking treatment.",
            "The symptoms are serious enough that getting healthcare is the sensible next step.",
            "I need to deal with this condition instead of trying to push through it.",
        )
    elif "urgency" in kinds:
        variants = (
            f"My {_NEED_LABELS[need]} is too low to ignore, so {label.casefold()} comes first.",
            f"This is urgent: I need to {label.casefold()} now.",
            f"I cannot put off my {_NEED_LABELS[need]} any longer.",
        )
    elif "goal" in kinds:
        variants = (
            f"{label} moves an active goal forward today.",
            f"I have a goal tied to this, so {label.casefold()} is a useful next step.",
            f"This choice gives one of my active goals real progress.",
        )
    elif "schedule" in kinds:
        variants = (
            f"The timing fits my routine, so I will {label.casefold()}.",
            f"This is the part of the day when {label.casefold()} makes sense.",
            f"My schedule points toward {label.casefold()} next.",
        )
    elif "relationship" in kinds:
        variants = (
            f"The people around me make {label.casefold()} feel like the right next move.",
            f"My relationships are part of why I want to {label.casefold()} now.",
            f"Who I have been spending time with makes this choice feel timely.",
        )
    elif "employment" in kinds:
        variants = (
            f"My work situation makes {label.casefold()} the practical choice.",
            f"Work and money are shaping what I do next, so I will {label.casefold()}.",
            f"This fits what my job situation needs from me today.",
        )
    elif "inventory" in kinds:
        variants = (
            f"I already have what I need to {label.casefold()}.",
            f"What I am carrying makes {label.casefold()} easy to do now.",
            f"I can use what I have on hand to {label.casefold()}.",
        )
    elif "memory" in kinds:
        variants = (
            f"What I remember makes {label.casefold()} feel worthwhile now.",
            f"A recent memory is nudging me to {label.casefold()}.",
            f"Past experience makes this a sensible next choice.",
        )
    else:
        variants = (
            str(choice["thought"]),
            f"My {_NEED_LABELS[need]} needs attention, so I will {label.casefold()}.",
            f"{label} fits what I need most right now.",
        )
    index = 0 if seed is None else random.Random(_stable_seed((seed, choice["action"], "thought"))).randrange(len(variants))
    return variants[index]


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


def score_candidate_actions(
    state: dict[str, Any],
    *,
    seed: Any = None,
    weighted: bool | None = None,
) -> dict[str, Any]:
    """Score actions, optionally making a reproducible weighted selection.

    Existing callers remain highest-utility and deterministic. Supplying ``seed``
    (or ``decisionSeed``/``seed`` in state) enables a bounded weighted draw.
    Rich v2.2 context is optional; absent fields contribute no utility.
    """

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
    hour = _number(state.get("hour"), 12.0) % 24
    traits = dict(state.get("traits") or {})
    schedule = state.get("schedule", state.get("routine"))
    goals = state.get("goals", state.get("activeGoals"))
    relationships = state.get("relationships", state.get("relationship"))
    memories = state.get("memories")
    inventory = state.get("inventory", state.get("possessions"))
    employment = state.get("employment")
    care = state.get("care", state.get("careDuties"))
    preferred_action = _canonical_action(state.get("preferredAction", ""))
    preference_tags = state.get("preferenceTags", [])
    current = _canonical_action(state.get("currentAction"))
    history = _recent_actions(state)
    max_repeats = int(_clamp(_number(state.get("maxOrdinaryRepeats"), 3.0), 1.0, 8.0))
    urgency_threshold = _clamp(_number(state.get("urgencyThreshold"), 18.0), 5.0, 40.0)
    cooldowns = state.get("cooldowns", {})
    explicit_fatigue = state.get("actionFatigue", state.get("fatigue", {}))
    healthcare_effects, health_condition_urgent = _healthcare_effects(state)
    choices = []

    for order, need in enumerate(NEED_NAMES):
        action, label, default_thought = _ACTION_BY_NEED[need]
        deficit = 100.0 - needs[need]
        base = deficit * _NEED_WEIGHTS[need] + max(0.0, 35.0 - needs[need]) * 0.65
        factors = [_factor("need", need, base, "Current need satisfaction shaped this option.")]
        score = base

        scheduled = _schedule_bonus(need, state)
        if scheduled:
            score += scheduled
            factors.append(_factor("schedule", "time_of_day", scheduled, "The time of day supports this action."))
        if schedule and _matches_action(action, schedule):
            score += 16.0
            factors.append(_factor("schedule", "routine", 16.0, "The resident's current routine supports this action."))
        if want_boost.get(need, 0.0):
            boost = want_boost[need]
            score += boost
            factors.append(_factor("want", need, boost, "An active short-term want supports this action."))

        trait = _trait_bonus(traits, action)
        if trait:
            score += trait
            factors.append(_factor("trait", action, trait, "Stable traits make this action more or less appealing."))
        goal = _goal_bonus(goals, action)
        if goal:
            score += goal
            factors.append(_factor("goal", action, goal, "An active goal is directly connected to this action."))
        if preferred_action == action:
            score += 12.0
            factors.append(_factor(
                "intention", "preferred_action", 12.0,
                "A validated intention provides a bounded preference for this action.",
            ))
        elif preference_tags and _matches_action(action, preference_tags):
            score += 6.0
            factors.append(_factor(
                "intention", "preference_tags", 6.0,
                "Validated preference tags provide a small bounded nudge.",
            ))
        for dimension, relationship in _relationship_effects(relationships, action):
            score += relationship
            factors.append(
                _factor(
                    "relationship", dimension, relationship,
                    f"Durable {dimension} affects the appeal of this action.",
                )
            )
        memory = _memory_bonus(memories, action)
        if memory:
            score += memory
            factors.append(_factor("memory", action, memory, "Relevant memories affect this choice without exposing their text."))
        available_item = _inventory_bonus(inventory, action)
        if available_item:
            score += available_item
            factors.append(_factor("inventory", action, available_item, "A useful item is already available."))
        work = _employment_bonus(employment, action, hour)
        if work:
            score += work
            factors.append(_factor("employment", action, work, "Employment status and shift timing affect this action."))
        if action == "seek_healthcare":
            for key, effect in healthcare_effects:
                score += effect
                explanation = {
                    "condition_severity": "Active condition severity raises treatment urgency.",
                    "active_conditions": "Multiple active conditions increase the value of care.",
                    "contagiousness": "A contagious condition makes timely care more important.",
                    "treatment_required": "A recorded treatment requirement supports seeking care.",
                    "treatment_cost": "Expected out-of-pocket cost makes treatment harder to pursue.",
                }[key]
                factors.append(_factor("health_condition", key, effect, explanation))

        if need == "comfort" and condition in {"rain", "storm", "snow", "first-snow"}:
            score += 22.0
            factors.append(_factor("weather", condition, 22.0, "Bad weather increases the value of comfort."))
        elif need == "safety" and condition in {"storm", "first-snow"}:
            score += 30.0
            factors.append(_factor("weather", condition, 30.0, "Hazardous weather increases safety urgency."))
        elif need == "social":
            social = min(14.0, nearby * 3.0)
            score += social
            if social:
                factors.append(_factor("proximity", "nearby_residents", social, "Nearby residents make social contact easier."))
        elif need == "privacy":
            privacy = crowding * 0.28
            score += privacy
            if privacy:
                factors.append(_factor("crowding", "privacy", privacy, "Crowding raises the value of private space."))
        elif need == "belonging" and event:
            catalyst = _clamp(_number(event.get("salience"), 30.0)) * 0.28
            score += catalyst
            factors.append(_factor("event", "community", catalyst, "The current event creates a community opportunity."))
        elif need == "financial_security":
            pressure = min(35.0, debt / 100.0)
            score += pressure
            if pressure:
                factors.append(_factor("finances", "debt", pressure, "Debt increases financial urgency."))

        if stage in {"baby", "child"} and need == "financial_security":
            label = "Find caregiver support"
            default_thought = "I need a grown-up I trust to make this feel secure."
        elif stage in {"baby", "child", "teen"} and need == "purpose":
            label = "Learn or practise something"

        urgent = needs[need] <= urgency_threshold or (action == "seek_healthcare" and health_condition_urgent)
        if urgent:
            urgency = max(3.0, (urgency_threshold - needs[need] + 1.0) * 1.6)
            score += urgency
            urgency_key = "condition_severity" if action == "seek_healthcare" and health_condition_urgent else need
            factors.append(_factor("urgency", urgency_key, urgency, "This need is urgent enough to override ordinary fatigue."))

        blocked = False
        repeats = _trailing_repeats(history, action)
        if current == action and not history:
            repeats = 1
        if current == action and repeats <= 1:
            score += 6.0
            factors.append(_factor("inertia", action, 6.0, "Finishing a recently started action avoids needless switching."))
        if repeats > 1:
            fatigue = min(70.0, (repeats - 1) * 17.0)
            if urgent:
                fatigue *= 0.2
            score -= fatigue
            factors.append(_factor("fatigue", action, -fatigue, "Repeated ordinary actions become less attractive."))
        if repeats >= max_repeats and not urgent:
            blocked = True
            score -= 120.0
            factors.append(_factor("cooldown", "repeat_limit", -120.0, "The ordinary repeat limit requires a change of activity."))

        action_fatigue = _clamp(_number(_mapping_value(explicit_fatigue, action), 0.0))
        if action_fatigue:
            penalty = action_fatigue * (0.06 if urgent else 0.30)
            score -= penalty
            factors.append(_factor("fatigue", "explicit", -penalty, "Accumulated action fatigue discourages repetition."))
        if _active_cooldown(_mapping_value(cooldowns, action)):
            if urgent:
                score -= 2.0
                factors.append(_factor("cooldown", "urgent_override", -2.0, "Urgency overrides this action's ordinary cooldown."))
            else:
                blocked = True
                score -= 120.0
                factors.append(_factor("cooldown", "active", -120.0, "This action is on cooldown."))

        travel = _travel_penalty(state, action)
        if travel:
            score -= travel
            factors.append(_factor("travel", action, -travel, "Travel time and cost reduce this action's utility."))
        venue_open = _venue_is_open(state, action)
        if venue_open is False:
            blocked = True
            score -= 140.0
            factors.append(_factor("venue_hours", action, -140.0, "The required venue is closed."))
        elif venue_open is True:
            score += 3.0
            factors.append(_factor("venue_hours", action, 3.0, "The required venue is currently open."))

        choices.append(
            {
                "action": action,
                "label": label,
                "score": round(max(0.0, score), 2),
                "primaryNeed": need,
                "needValue": needs[need],
                "thought": default_thought,
                "factors": factors,
                "urgent": urgent,
                "available": not blocked,
                "_order": order,
            }
        )

    dependents = int(max(0.0, _number(state.get("uncoveredDependents"), 0.0)))
    care_due = dependents > 0 or _care_is_due(care)
    if care_due:
        care_score = 105.0 + dependents * 18.0 if dependents else 72.0
        care_factors = [_factor("care", "coverage", care_score, "A real care duty requires coverage before other plans.")]
        for dimension, relationship in _relationship_effects(relationships, "secure_childcare"):
            care_score += relationship
            care_factors.append(
                _factor(
                    "relationship", dimension, relationship,
                    f"Durable {dimension} affects willingness to cover care.",
                )
            )
        choices.append(
            {
                "action": "secure_childcare",
                "label": "Make sure the children are cared for",
                "score": round(care_score, 2),
                "primaryNeed": "safety",
                "needValue": needs["safety"],
                "thought": "I cannot leave until I know the children are safe with someone.",
                "factors": care_factors,
                "urgent": dependents > 0,
                "available": True,
                "_order": len(choices),
            }
        )

    choices.sort(key=lambda choice: (-choice["score"], choice["_order"]))
    available = [choice for choice in choices if choice["available"]]
    if not available:
        available = choices[:]

    selection_seed = seed
    if selection_seed is None:
        selection_seed = state.get("decisionSeed", state.get("seed"))
    weighted_selection = bool(selection_seed is not None) if weighted is None else bool(weighted)
    if weighted_selection and selection_seed is None:
        selection_seed = {"needs": needs, "hour": hour, "history": history, "current": current}

    pool_limit = int(_clamp(_number(state.get("selectionPoolSize"), 5.0), 2.0, 8.0))
    peak = available[0]["score"]
    pool = [choice for choice in available[:pool_limit] if peak - choice["score"] <= 55.0] or available[:1]
    temperature = _clamp(_number(state.get("selectionTemperature"), 22.0), 4.0, 50.0)
    pool_weights = [math.exp((choice["score"] - peak) / temperature) for choice in pool]
    selected = pool[0]
    if weighted_selection and len(pool) > 1:
        rng = random.Random(_stable_seed((selection_seed, "decision")))
        target = rng.random() * sum(pool_weights)
        cumulative = 0.0
        for choice, weight_value in zip(pool, pool_weights, strict=True):
            cumulative += weight_value
            if target <= cumulative:
                selected = choice
                break

    displayed = [selected]
    displayed.extend(choice for choice in available if choice is not selected and len(displayed) < 3)
    display_peak = max(choice["score"] for choice in displayed)
    display_weights = [math.exp((choice["score"] - display_peak) / temperature) for choice in displayed]
    display_total = sum(display_weights)
    utility_ranks = {choice["action"]: rank for rank, choice in enumerate(available, 1)}
    for rank, (choice, weight_value) in enumerate(zip(displayed, display_weights, strict=True), 1):
        choice["rank"] = rank
        choice["utilityRank"] = utility_ranks[choice["action"]]
        choice["selected"] = rank == 1
        choice["confidence"] = round(weight_value / display_total * 100.0, 1)
        choice["thought"] = _thought_for(choice, selection_seed)
        choice.pop("_order")

    all_scores = {choice["action"]: choice["score"] for choice in choices}
    all_factors = {choice["action"]: choice["factors"] for choice in choices}
    blocked = [choice["action"] for choice in choices if not choice["available"]]
    return {
        "choices": displayed,
        "decision": selected["action"],
        "ponder": selected["thought"],
        "allScores": all_scores,
        "factorBreakdown": all_factors,
        "blockedActions": blocked,
        "selection": {
            "mode": "seeded-weighted" if weighted_selection else "highest-utility",
            "poolSize": len(pool),
            "temperature": round(temperature, 2),
        },
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
