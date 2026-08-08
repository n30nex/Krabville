from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import random
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any


MAX_LIVING = 32
MAX_ADULTS = 24
MINOR_STAGES = frozenset({"baby", "child", "teen"})
ADULT_STAGES = frozenset({"adult", "senior"})
LIFE_STAGES = MINOR_STAGES | ADULT_STAGES

_GENETIC_APPEARANCE = ("skinTone", "hairColor", "hairTexture", "eyeColor")
_TRAIT_NAMES = (
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "emotionalStability",
    "empathy",
    "ambition",
    "spontaneity",
)

_IDENTITIES = (
    ("Amara", "Okafor", "woman", "she/her", "deep", "black", "coils", "brown"),
    ("Mateo", "Alvarez", "man", "he/him", "tan", "black", "wavy", "brown"),
    ("Priya", "Raman", "woman", "she/her", "medium", "black", "straight", "brown"),
    ("Jun", "Park", "nonbinary", "they/them", "light-medium", "black", "straight", "brown"),
    ("Elias", "Haddad", "man", "he/him", "olive", "dark brown", "curly", "hazel"),
    ("Sofia", "Martins", "woman", "she/her", "light", "brown", "wavy", "green"),
    ("Nia", "Thompson", "woman", "she/her", "deep", "black", "braided", "brown"),
    ("Luca", "Bianchi", "man", "he/him", "light", "brown", "curly", "blue"),
    ("Noor", "Rahman", "nonbinary", "they/them", "medium", "black", "wavy", "brown"),
    ("Gabriel", "Tremblay", "man", "he/him", "light", "auburn", "wavy", "green"),
    ("Hana", "Sato", "woman", "she/her", "light-medium", "black", "straight", "brown"),
    ("Maya", "Cardinal", "woman", "she/her", "medium", "dark brown", "straight", "hazel"),
    ("Leila", "Bekele", "woman", "she/her", "deep", "black", "coils", "brown"),
    ("Owen", "MacLeod", "man", "he/him", "fair", "red", "curly", "blue"),
    ("Samira", "Farouk", "woman", "she/her", "olive", "black", "wavy", "hazel"),
    ("Theo", "Nguyen", "man", "he/him", "light-medium", "black", "straight", "brown"),
)

_CAREERS = (
    ("paramedic", "Lagoon Health Centre", 68_000),
    ("carpenter", "Harbour Works", 61_000),
    ("teacher", "Krabville School", 66_000),
    ("marine biologist", "Lagoon Field Lab", 74_000),
    ("cafe owner", "Blue Kettle Cafe", 58_000),
    ("radio technician", "Signal House", 72_000),
    ("urban gardener", "Tideway Gardens", 53_000),
    ("accountant", "Krabville Credit Union", 69_000),
    ("librarian", "Harbour Library", 59_000),
    ("ferry captain", "Lagoon Ferry", 76_000),
    ("software developer", "Dockside Studio", 82_000),
    ("social worker", "Community House", 65_000),
)

_HOBBIES = (
    "birdwatching",
    "board games",
    "canoeing",
    "cooking",
    "community theatre",
    "electronics",
    "gardening",
    "guitar",
    "hiking",
    "painting",
    "photography",
    "pottery",
    "reading",
    "running",
    "stargazing",
    "woodworking",
)

_ASPIRATIONS = (
    "build a secure and loving family life",
    "create a business that improves the town",
    "become a respected leader without losing close friendships",
    "master a craft and teach it to someone younger",
    "own a peaceful home beside the Lagoon",
    "make a discovery that changes how Krabville sees itself",
    "be financially independent and generous with neighbours",
    "live an adventurous life full of meaningful stories",
    "leave Krabville healthier than they found it",
    "create art that becomes part of the town's identity",
)

_ORIENTATIONS = (
    "heterosexual",
    "gay",
    "lesbian",
    "bisexual",
    "pansexual",
    "asexual",
)

_ACCENT_COLORS = (
    "#53b3cb",
    "#f4b942",
    "#e76f51",
    "#78c091",
    "#9b7ede",
    "#e56b9f",
    "#4d908e",
    "#f9844a",
)

_CHILD_NAMES = {
    "baby": ("Ari", "Mira", "Leo", "Imani", "Noa", "Remy", "Zuri", "Milo"),
    "child": ("Niko", "Zoe", "Iris", "Dev", "Talia", "Jamie", "Anya", "Micah"),
    "teen": ("Robin", "Sasha", "Emery", "Drew", "Quinn", "Riley", "Avery", "Morgan"),
}

_HOUSEHOLD_SPECS = (
    ("harbour-family", "Harbour House 01", "mortgage", 3),
    ("garden-family", "Garden House 02", "rent", 3),
    ("canal-family", "Canal Apartment 03", "rent", 2),
    ("lighthouse-single", "Lighthouse Flat 04", "rent", 1),
    ("market-single", "Market Loft 05", "rent", 1),
    ("willow-single", "Willow Cottage 06", "mortgage", 1),
)


class PopulationLimitError(ValueError):
    """Raised when a population exceeds KVsim's supported living limits."""


def _stable_seed(seed: int | str | bytes) -> tuple[int, str]:
    value = seed if isinstance(seed, bytes) else str(seed).encode("utf-8")
    digest = sha256(value).digest()
    return int.from_bytes(digest, "big"), digest.hex()[:16]


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def _traits(rng: random.Random) -> dict[str, int]:
    return {name: rng.randint(28, 88) for name in _TRAIT_NAMES}


def _adult_record(
    identity: tuple[str, ...],
    career: tuple[str, str, int],
    orientation: str,
    household_slug: str,
    rng: random.Random,
) -> dict[str, Any]:
    first, last, gender, pronouns, skin, hair, texture, eyes = identity
    name = f"{first} {last}"
    title, workplace, income = career
    return {
        "slug": _slug(name),
        "name": name,
        "givenName": first,
        "familyName": last,
        "genderIdentity": gender,
        "pronouns": pronouns,
        "orientation": orientation,
        "householdSlug": household_slug,
        "householdRole": "adult",
        "partnerSlug": None,
        "parentSlugs": [],
        "childSlugs": [],
        "traits": _traits(rng),
        "career": {
            "title": title,
            "workplace": workplace,
            "status": "employed",
            "annualIncomeCad": income,
        },
        "hobbies": rng.sample(_HOBBIES, 3),
        "aspiration": rng.choice(_ASPIRATIONS),
        "appearance": {
            "skinTone": skin,
            "hairColor": hair,
            "hairTexture": texture,
            "eyeColor": eyes,
            "style": rng.choice(("practical", "casual", "artsy", "outdoorsy", "polished")),
            "accentColor": rng.choice(_ACCENT_COLORS),
        },
        "life": {
            "stage": "adult",
            "alive": True,
            "seasonsInStage": 0,
            "adultSeasons": 0,
            "seniorSeasons": 0,
            "totalSeasons": 0,
            "deathCause": None,
        },
        "care": {"requiresCare": False, "primaryCaregiverSlugs": []},
    }


def _child_record(
    stage: str,
    parents: Sequence[Mapping[str, Any]],
    household_slug: str,
    used_slugs: set[str],
    rng: random.Random,
) -> dict[str, Any]:
    first_names = list(_CHILD_NAMES[stage])
    rng.shuffle(first_names)
    family_name = str(rng.choice(parents)["familyName"])
    for first_name in first_names:
        slug = _slug(f"{first_name} {family_name}")
        if slug not in used_slugs:
            break
    else:  # Curated pools are larger than the starting population.
        raise ValueError("unable to create a unique child slug")

    parent_slugs = [str(parent["slug"]) for parent in parents]
    trait_values: dict[str, int] = {}
    for trait in _TRAIT_NAMES:
        inherited = sum(int(parent["traits"][trait]) for parent in parents) / len(parents)
        trait_values[trait] = max(0, min(100, round(inherited + rng.randint(-8, 8))))

    appearance: dict[str, Any] = {
        "style": {"baby": "soft", "child": "playful", "teen": "individual"}[stage],
        "accentColor": rng.choice(_ACCENT_COLORS),
    }
    inherited_from: dict[str, str] = {}
    for feature in _GENETIC_APPEARANCE:
        parent = rng.choice(parents)
        appearance[feature] = parent["appearance"][feature]
        inherited_from[feature] = str(parent["slug"])
    appearance["inheritedFrom"] = inherited_from

    school = {
        "baby": ("dependent", "home"),
        "child": ("student", "Krabville School"),
        "teen": ("student", "Krabville Secondary School"),
    }[stage]
    aspiration = {
        "baby": "feel safe, loved, and curious about the world",
        "child": "discover a favourite talent and make lasting friends",
        "teen": "become independent without losing important relationships",
    }[stage]
    return {
        "slug": slug,
        "name": f"{first_name} {family_name}",
        "givenName": first_name,
        "familyName": family_name,
        "genderIdentity": "developing",
        "pronouns": "they/them",
        "orientation": "not specified",
        "householdSlug": household_slug,
        "householdRole": "minor",
        "partnerSlug": None,
        "parentSlugs": parent_slugs,
        "childSlugs": [],
        "traits": trait_values,
        "career": {
            "title": school[0],
            "workplace": school[1],
            "status": "dependent",
            "annualIncomeCad": 0,
        },
        "hobbies": rng.sample(_HOBBIES, 2),
        "aspiration": aspiration,
        "appearance": appearance,
        "life": {
            "stage": stage,
            "alive": True,
            "seasonsInStage": 0,
            "adultSeasons": 0,
            "seniorSeasons": 0,
            "totalSeasons": 0,
            "deathCause": None,
        },
        "care": {
            "requiresCare": True,
            "primaryCaregiverSlugs": parent_slugs,
        },
    }


def _home(slug: str, address: str, tenure: str, bedrooms: int) -> dict[str, Any]:
    return {
        "slug": slug,
        "address": address,
        "tenure": tenure,
        "bedrooms": bedrooms,
    }


def generate_starting_population(seed: int | str | bytes) -> dict[str, Any]:
    """Create the fresh KVsim 2.0 cast without relying on global random state."""

    seed_value, fingerprint = _stable_seed(seed)
    rng = random.Random(seed_value)
    identities = rng.sample(_IDENTITIES, 8)
    careers = rng.sample(_CAREERS, 8)
    orientations = ["bisexual", "pansexual", "pansexual", "bisexual"]
    orientations.extend(rng.sample(_ORIENTATIONS, 4))
    household_slugs = [
        "harbour-family",
        "harbour-family",
        "garden-family",
        "garden-family",
        "canal-family",
        "lighthouse-single",
        "market-single",
        "willow-single",
    ]
    adults = [
        _adult_record(identity, career, orientations[index], household_slugs[index], rng)
        for index, (identity, career) in enumerate(zip(identities, careers, strict=True))
    ]

    adults[0]["partnerSlug"] = adults[1]["slug"]
    adults[1]["partnerSlug"] = adults[0]["slug"]
    adults[0]["relationshipStatus"] = adults[1]["relationshipStatus"] = "married"
    adults[2]["partnerSlug"] = adults[3]["slug"]
    adults[3]["partnerSlug"] = adults[2]["slug"]
    adults[2]["relationshipStatus"] = adults[3]["relationshipStatus"] = "committed"
    for adult in adults[4:]:
        adult["relationshipStatus"] = "single"

    used_slugs = {str(adult["slug"]) for adult in adults}
    children = [
        _child_record("baby", adults[0:2], "harbour-family", used_slugs, rng),
        _child_record("child", adults[0:2], "harbour-family", used_slugs, rng),
        _child_record("child", adults[2:4], "garden-family", used_slugs, rng),
        _child_record("teen", adults[4:5], "canal-family", used_slugs, rng),
    ]
    for child in children:
        used_slugs.add(str(child["slug"]))
        for parent in adults:
            if parent["slug"] in child["parentSlugs"]:
                parent["childSlugs"].append(child["slug"])

    adults[0]["career"]["status"] = "parental-leave"
    household_members = {
        "harbour-family": [adults[0], adults[1], children[0], children[1]],
        "garden-family": [adults[2], adults[3], children[2]],
        "canal-family": [adults[4], children[3]],
        "lighthouse-single": [adults[5]],
        "market-single": [adults[6]],
        "willow-single": [adults[7]],
    }
    care_arrangements = {
        "harbour-family": {
            children[0]["slug"]: "parental leave",
            children[1]["slug"]: "school and family care",
        },
        "garden-family": {children[2]["slug"]: "school and paid after-school care"},
        "canal-family": {children[3]["slug"]: "secondary school and parent supervision"},
    }

    households: list[dict[str, Any]] = []
    for slug, address, tenure, bedrooms in _HOUSEHOLD_SPECS:
        members = household_members[slug]
        adults_in_home = [member for member in members if member["life"]["stage"] in ADULT_STAGES]
        minors_in_home = [member for member in members if member["life"]["stage"] in MINOR_STAGES]
        households.append(
            {
                "slug": slug,
                "name": f"{address} household",
                "kind": "family" if minors_in_home else "single",
                "partnership": (
                    adults_in_home[0].get("relationshipStatus")
                    if len(adults_in_home) == 2
                    else "single"
                ),
                "home": _home(slug, address, tenure, bedrooms),
                "memberSlugs": [member["slug"] for member in members],
                "adultSlugs": [member["slug"] for member in adults_in_home],
                "minorSlugs": [member["slug"] for member in minors_in_home],
                "caregiverPlan": [
                    {
                        "minorSlug": minor["slug"],
                        "caregiverSlugs": minor["parentSlugs"],
                        "arrangement": care_arrangements[slug][minor["slug"]],
                    }
                    for minor in minors_in_home
                ],
            }
        )

    residents = adults + children
    counts = enforce_population_caps(residents)
    return {
        "schemaVersion": 2,
        "seedFingerprint": fingerprint,
        "limits": {"maxLiving": MAX_LIVING, "maxAdults": MAX_ADULTS},
        "counts": counts,
        "residents": residents,
        "households": households,
    }


def population_counts(residents: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    living = [resident for resident in residents if bool(resident["life"].get("alive", True))]
    stages = [str(resident["life"]["stage"]) for resident in living]
    unknown = sorted(set(stages) - LIFE_STAGES)
    if unknown:
        raise ValueError(f"unknown living life stage: {', '.join(unknown)}")
    adults = sum(stage in ADULT_STAGES for stage in stages)
    minors = sum(stage in MINOR_STAGES for stage in stages)
    return {"living": len(living), "adults": adults, "minors": minors}


def enforce_population_caps(residents: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = population_counts(residents)
    if counts["living"] > MAX_LIVING:
        raise PopulationLimitError(f"living population {counts['living']} exceeds {MAX_LIVING}")
    if counts["adults"] > MAX_ADULTS:
        raise PopulationLimitError(f"adult population {counts['adults']} exceeds {MAX_ADULTS}")
    return counts


def _apply_stage(record: dict[str, Any], stage: str) -> None:
    life = record["life"]
    life["stage"] = stage
    life["seasonsInStage"] = 0
    if stage == "child":
        record["householdRole"] = "minor"
        record["career"] = {
            "title": "student",
            "workplace": "Krabville School",
            "status": "dependent",
            "annualIncomeCad": 0,
        }
    elif stage == "teen":
        record["householdRole"] = "minor"
        record["career"] = {
            "title": "student",
            "workplace": "Krabville Secondary School",
            "status": "dependent",
            "annualIncomeCad": 0,
        }
    elif stage == "adult":
        record["householdRole"] = "adult"
        record["care"]["requiresCare"] = False
        record["career"] = {
            "title": "career seeker",
            "workplace": "Krabville",
            "status": "seeking",
            "annualIncomeCad": 0,
        }
    elif stage == "senior":
        record["career"]["status"] = "retired"


def advance_lifecycle(
    resident: Mapping[str, Any],
    seasons: int = 1,
    *,
    adult_mortality_risk: float = 0.0,
    mortality_roll: float = 1.0,
) -> dict[str, Any]:
    """Advance a copy of a resident using explicit, deterministic mortality inputs.

    A caller can model a rare adult event with a small risk and a precomputed roll.
    Minors ignore mortality risk. Seniors complete two seasons and then die naturally.
    """

    if isinstance(seasons, bool) or not isinstance(seasons, int) or seasons < 0:
        raise ValueError("seasons must be a non-negative integer")
    if not 0.0 <= adult_mortality_risk <= 1.0:
        raise ValueError("adult_mortality_risk must be between 0 and 1")
    if not 0.0 <= mortality_roll <= 1.0:
        raise ValueError("mortality_roll must be between 0 and 1")

    record = deepcopy(dict(resident))
    life = record["life"]
    if str(life["stage"]) not in LIFE_STAGES:
        raise ValueError(f"unknown life stage: {life['stage']}")

    for _ in range(seasons):
        if not bool(life.get("alive", True)):
            break
        stage = str(life["stage"])
        if stage == "adult" and adult_mortality_risk > mortality_roll:
            life["alive"] = False
            life["deathCause"] = "rare adult illness or accident"
            break

        life["totalSeasons"] = int(life.get("totalSeasons", 0)) + 1
        life["seasonsInStage"] = int(life.get("seasonsInStage", 0)) + 1
        if stage == "baby":
            _apply_stage(record, "child")
        elif stage == "child":
            _apply_stage(record, "teen")
        elif stage == "teen":
            _apply_stage(record, "adult")
        elif stage == "adult":
            life["adultSeasons"] = int(life.get("adultSeasons", 0)) + 1
            if life["adultSeasons"] >= 4:
                _apply_stage(record, "senior")
        elif stage == "senior":
            life["seniorSeasons"] = int(life.get("seniorSeasons", 0)) + 1
            if life["seniorSeasons"] >= 2:
                life["alive"] = False
                life["deathCause"] = "natural old age"
    return record
