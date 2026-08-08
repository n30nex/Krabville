from __future__ import annotations

import hashlib
import random
import sqlite3
from typing import Any

from .db import dumps, loads, now_iso
from .economy_v2 import settle_day
from .population_v2 import ADULT_STAGES, MINOR_STAGES, generate_starting_population
from .simulation_v2 import DEFAULT_NEEDS, NEED_NAMES


HOME_LOCATIONS = {
    "harbour-family": "Anchor House",
    "garden-family": "Rose House",
    "canal-family": "Birch House",
    "lighthouse-single": "Lantern House",
    "market-single": "Post House",
    "willow-single": "Willow House",
}

WORK_LOCATIONS = {
    "Lagoon Health Centre": "Lagoon Clinic",
    "Harbour Works": "Repair Workshop",
    "Krabville School": "Oak Hill College",
    "Lagoon Field Lab": "Weather Station",
    "Blue Kettle Cafe": "Hobbs Cafe",
    "Signal House": "Radio Shack",
    "Tideway Gardens": "Garden Studio",
    "Krabville Credit Union": "Post Office",
    "Harbour Library": "Lagoon Library",
    "Lagoon Ferry": "Ferry Dock",
    "Dockside Studio": "Radio Shack",
    "Community House": "Town Square",
}

PROPERTY_TYPES = {
    "Krabville School": "school",
    "Lagoon Health Centre": "hospital",
    "Krabville Credit Union": "bank",
    "Blue Kettle Cafe": "shop",
}


def _rng(seed_hex: str, *parts: object) -> random.Random:
    material = seed_hex + "|" + "|".join(str(part) for part in parts)
    return random.Random(int.from_bytes(hashlib.sha256(material.encode()).digest(), "big"))


def _resident_id(connection: sqlite3.Connection, slug: str) -> int:
    row = connection.execute("SELECT id FROM residents WHERE slug=?", (slug,)).fetchone()
    if not row:
        raise RuntimeError(f"resident not found: {slug}")
    return int(row[0])


def bootstrap_population(connection: sqlite3.Connection, seed_hex: str) -> None:
    """Replace the legacy demo cast with the deterministic KVsim v2 cast once."""

    if connection.execute("SELECT 1 FROM seasons LIMIT 1").fetchone():
        return
    population = generate_starting_population(seed_hex)
    connection.execute("DELETE FROM residents")
    created = now_iso()
    adult_offsets = iter(_rng(seed_hex, "adult-age").sample([0, 0, 1, 1, 2, 2, 3, 3], 8))

    for resident in population["residents"]:
        career = resident["career"]
        stage = str(resident["life"]["stage"])
        home = HOME_LOCATIONS[str(resident["householdSlug"])]
        workplace = WORK_LOCATIONS.get(str(career["workplace"]), home)
        traits = dict(resident["traits"])
        traits.setdefault("sociability", traits.get("extraversion", 50))
        traits.setdefault("agreeableness", traits.get("agreeableness", 50))
        possessions = [*resident.get("hobbies", []), "phone", "house keys"]
        about = f"Wants to {resident['aspiration']}. Enjoys {', '.join(resident.get('hobbies', [])[:2])}."
        cursor = connection.execute(
            """
            INSERT INTO residents(
              slug,name,role,home,workplace,color,traits_json,possessions_json,
              routine,about,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                resident["slug"], resident["name"], career["title"], home, workplace,
                resident["appearance"]["accentColor"], dumps(traits), dumps(possessions),
                f"Balance {career['title']}, home life, relationships, and {resident.get('hobbies', ['local life'])[0]}.",
                about, created,
            ),
        )
        resident_id = int(cursor.lastrowid)
        stage_index = next(adult_offsets) if stage == "adult" else 0
        connection.execute(
            """
            UPDATE resident_identities SET generation_seed=?,given_name=?,family_name=?,
              display_name=?,pronouns=?,gender_identity=?,orientation=?,ancestry=?,
              appearance_key=?,biography=?,generated_at=? WHERE resident_id=?
            """,
            (
                f"v2:{population['seedFingerprint']}:{resident['slug']}", resident["givenName"],
                resident["familyName"], resident["name"], resident["pronouns"],
                resident["genderIdentity"], resident["orientation"], "Krabville",
                dumps(resident["appearance"]), about, created, resident_id,
            ),
        )
        connection.execute(
            """
            UPDATE resident_lifecycle SET current_stage=?,seasons_in_stage=?,genetic_seed=?
            WHERE resident_id=?
            """,
            (stage, stage_index, f"genes:{population['seedFingerprint']}:{resident['slug']}", resident_id),
        )

    household_ids: dict[str, int] = {}
    property_ids: dict[str, int] = {}
    for household in population["households"]:
        slug = str(household["slug"])
        home = household["home"]
        household_id = int(connection.execute(
            """
            INSERT INTO households(slug,name,household_type,status,founded_tick,financial_policy,created_at)
            VALUES(?,?,?,'active',0,?,?) RETURNING id
            """,
            (slug, household["name"], "family" if household["minorSlugs"] else "single", "mixed", created),
        ).fetchone()[0])
        household_ids[slug] = household_id
        property_id = int(connection.execute(
            """
            INSERT INTO properties(
              slug,name,property_type,address,exterior_key,interior_key,bedrooms,
              resident_capacity,market_value_cents,status,created_tick
            ) VALUES(?,?, 'house',?,?,?,?,?,?, 'occupied',0) RETURNING id
            """,
            (
                f"home-{slug}", home["address"], home["address"], slug, "family-home",
                int(home["bedrooms"]), max(2, int(home["bedrooms"]) * 2),
                265_000_00 + int(home["bedrooms"]) * 55_000_00,
            ),
        ).fetchone()[0])
        property_ids[slug] = property_id
        connection.execute(
            """
            INSERT INTO property_occupancy(property_id,household_id,occupancy_type,monthly_cost_cents,started_tick)
            VALUES(?,?,?,?,0)
            """,
            (property_id, household_id, "owner" if home["tenure"] == "mortgage" else "renter", 185_000 if home["tenure"] == "mortgage" else 145_000),
        )
        if home["tenure"] == "mortgage":
            connection.execute(
                """
                INSERT INTO property_ownership(property_id,household_id,ownership_basis_points,acquired_tick)
                VALUES(?,?,10000,0)
                """,
                (property_id, household_id),
            )
        connection.execute(
            """
            INSERT INTO financial_accounts(household_id,name,account_type,opening_balance_cents,opened_tick)
            VALUES(?, 'Household chequing','chequing',?,0)
            """,
            (household_id, _rng(seed_hex, "household-money", slug).randint(320_000, 1_450_000)),
        )

    residents = {resident["slug"]: resident for resident in population["residents"]}
    for resident in population["residents"]:
        resident_id = _resident_id(connection, str(resident["slug"]))
        household_id = household_ids[str(resident["householdSlug"])]
        role = "child" if resident["life"]["stage"] in MINOR_STAGES else "head"
        if resident.get("partnerSlug"):
            role = "partner"
        connection.execute(
            """
            INSERT INTO household_members(
              household_id,resident_id,role,legal_guardian,financially_responsible,joined_tick
            ) VALUES(?,?,?,?,?,0)
            """,
            (household_id, resident_id, role, int(role in {"head", "partner"}), int(role in {"head", "partner"})),
        )
        opening = 0 if resident["life"]["stage"] in MINOR_STAGES else _rng(seed_hex, "money", resident["slug"]).randint(40_000, 620_000)
        connection.execute(
            """
            INSERT INTO financial_accounts(resident_id,name,account_type,opening_balance_cents,opened_tick)
            VALUES(?, 'Personal chequing','chequing',?,0)
            """,
            (resident_id, opening),
        )
        if resident["life"]["stage"] in ADULT_STAGES:
            money_rng = _rng(seed_hex, "portfolio", resident["slug"])
            connection.execute(
                """
                INSERT INTO financial_accounts(resident_id,name,account_type,opening_balance_cents,opened_tick)
                VALUES(?,'Savings','savings',?,0)
                """,
                (resident_id, money_rng.randint(75_000, 1_600_000)),
            )
            investment_account = int(connection.execute(
                """
                INSERT INTO financial_accounts(resident_id,name,account_type,opening_balance_cents,opened_tick)
                VALUES(?,'Investments','investment',0,0) RETURNING id
                """,
                (resident_id,),
            ).fetchone()[0])
            market_value = money_rng.randint(100_000, 2_400_000)
            connection.execute(
                """
                INSERT INTO investments(
                  account_id,symbol,investment_type,units,average_cost_cents,market_value_cents,
                  acquired_tick,updated_tick
                ) VALUES(?,'KVF','fund',?,?,?,0,0)
                """,
                (investment_account, max(1, market_value / 10_000), 10_000, market_value),
            )
            if money_rng.random() < 0.62:
                loan_account = int(connection.execute(
                    """
                    INSERT INTO financial_accounts(resident_id,name,account_type,opening_balance_cents,opened_tick)
                    VALUES(?,'Personal loan','loan',0,0) RETURNING id
                    """,
                    (resident_id,),
                ).fetchone()[0])
                principal = money_rng.randint(180_000, 4_500_000)
                connection.execute(
                    """
                    INSERT INTO debts(
                      borrower_account_id,debt_type,principal_cents,outstanding_cents,
                      annual_rate_basis_points,minimum_payment_cents,opened_tick,status
                    ) VALUES(?,'loan',?,?,?,?,0,'current')
                    """,
                    (
                        loan_account, principal, principal, money_rng.randint(450, 1_250),
                        max(3_000, principal // 50),
                    ),
                )
        for parent_slug in resident.get("parentSlugs", []):
            parent_id = _resident_id(connection, str(parent_slug))
            connection.execute(
                """
                INSERT INTO family_links(
                  resident_id,relative_resident_id,relation_type,biological,legal,started_tick
                ) VALUES(?,?,'parent',1,1,0),(?,?,'child',1,1,0)
                """,
                (resident_id, parent_id, parent_id, resident_id),
            )
        partner_slug = resident.get("partnerSlug")
        if partner_slug and str(resident["slug"]) < str(partner_slug):
            partner_id = _resident_id(connection, str(partner_slug))
            relation = "spouse" if resident.get("relationshipStatus") == "married" else "partner"
            connection.execute(
                """
                INSERT INTO family_links(resident_id,relative_resident_id,relation_type,legal,started_tick)
                VALUES(?,?,?,?,0),(?,?,?,?,0)
                """,
                (resident_id, partner_id, relation, int(relation == "spouse"), partner_id, resident_id, relation, int(relation == "spouse")),
            )

    _seed_businesses_and_jobs(connection, population, created)
    _seed_childcare(connection, population)


def _seed_businesses_and_jobs(connection: sqlite3.Connection, population: dict[str, Any], created: str) -> None:
    workplaces = {
        str(resident["career"]["workplace"])
        for resident in population["residents"]
        if resident["life"]["stage"] in ADULT_STAGES
    }
    workplaces.update({"Krabville School", "Lagoon Health Centre", "Krabville Credit Union", "Blue Kettle Cafe"})
    workplaces = sorted(workplaces)
    business_ids: dict[str, int] = {}
    job_ids: dict[str, int] = {}
    for index, workplace in enumerate(workplaces):
        slug = "business-" + "-".join(workplace.lower().replace("'", "").split())
        location = WORK_LOCATIONS.get(workplace, "Town Square")
        property_id = int(connection.execute(
            """
            INSERT INTO properties(
              slug,name,property_type,address,exterior_key,interior_key,resident_capacity,
              business_capacity,market_value_cents,status,created_tick
            ) VALUES(?,?,?,?,?, 'workplace',0,12,?, 'occupied',0) RETURNING id
            """,
            (f"property-{slug}", workplace, PROPERTY_TYPES.get(workplace, "office"), location, slug, 420_000_00 + index * 21_000_00),
        ).fetchone()[0])
        business_id = int(connection.execute(
            """
            INSERT INTO businesses(slug,name,industry,property_id,status,valuation_cents,reputation,created_at)
            VALUES(?,?,?,?, 'active',?,50,?) RETURNING id
            """,
            (slug, workplace, PROPERTY_TYPES.get(workplace, "services"), property_id, 180_000_00 + index * 9_000_00, created),
        ).fetchone()[0])
        business_ids[workplace] = business_id
        connection.execute(
            """
            INSERT INTO financial_accounts(business_id,name,account_type,opening_balance_cents,opened_tick)
            VALUES(?, 'Operating','business',2500000,0)
            """,
            (business_id,),
        )
    for resident in population["residents"]:
        if resident["life"]["stage"] not in ADULT_STAGES:
            continue
        career = resident["career"]
        business_id = business_ids[str(career["workplace"])]
        key = f"{business_id}:{career['title']}"
        if key not in job_ids:
            job_ids[key] = int(connection.execute(
                """
                INSERT INTO jobs(business_id,slug,title,category,hourly_wage_cents,weekly_hours,positions)
                VALUES(?,?,?,?,?,?,2) RETURNING id
                """,
                (business_id, str(career["title"]).replace(" ", "-"), career["title"], "regular", max(1_650, int(career["annualIncomeCad"] * 100 / 2080)), 37.5),
            ).fetchone()[0])
        status = "leave" if career["status"] == "parental-leave" else "active"
        connection.execute(
            """
            INSERT INTO employment(resident_id,job_id,status,hired_tick,wage_cents,scheduled_minutes_per_day)
            VALUES(?,?,?,0,?,450)
            """,
            (_resident_id(connection, str(resident["slug"])), job_ids[key], status, max(1_650, int(career["annualIncomeCad"] * 100 / 2080))),
        )


def _seed_childcare(connection: sqlite3.Connection, population: dict[str, Any]) -> None:
    school = connection.execute("SELECT id FROM businesses WHERE name='Krabville School'").fetchone()
    for resident in population["residents"]:
        stage = str(resident["life"]["stage"])
        if stage not in MINOR_STAGES:
            continue
        child_id = _resident_id(connection, str(resident["slug"]))
        parent_id = _resident_id(connection, str(resident["parentSlugs"][0]))
        arrangement = "parent" if stage == "baby" else "school"
        provider_id = int(school[0]) if arrangement == "school" and school else None
        connection.execute(
            """
            INSERT INTO childcare_arrangements(
              child_resident_id,arrangement_type,caregiver_resident_id,provider_business_id,
              cost_per_day_cents,status,started_tick
            ) VALUES(?,?,?,?,?,'active',0)
            """,
            (child_id, arrangement, parent_id if arrangement == "parent" else None, provider_id, 0 if arrangement == "parent" else 4_500),
        )


def initialize_v2_season_state(
    connection: sqlite3.Connection,
    season_id: int,
    prior_season_id: int | None,
    seed_hex: str,
) -> None:
    """Reset needs while carrying identity, family, economy, memories and relationships."""

    rng = _rng(seed_hex, "needs")
    for resident in connection.execute(
        """
        SELECT r.id,r.slug,l.current_stage,l.seasons_in_stage,
          hm.household_id
        FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        LEFT JOIN household_members hm ON hm.resident_id=r.id AND hm.ended_season_id IS NULL
        WHERE l.alive=1 ORDER BY r.id
        """
    ):
        stage = str(resident["current_stage"])
        care_state = "needs_care" if stage in {"baby", "child"} else "independent"
        connection.execute(
            """
            INSERT INTO resident_season_state(
              season_id,resident_id,household_id,life_stage,stage_season_index,
              mood_label,mood_valence,stress,health_score,care_state,decision_state,updated_tick
            ) VALUES(?,?,?,?,?,'steady',20,12,100,?,'idle',0)
            """,
            (season_id, resident["id"], resident["household_id"], stage, resident["seasons_in_stage"], care_state),
        )
        needs = {
            name: max(42, min(96, round(DEFAULT_NEEDS[name] + rng.randint(-12, 12))))
            for name in NEED_NAMES
        }
        if stage == "baby":
            needs.update({"energy": 58, "hunger": 55, "safety": 88, "autonomy": 45})
        connection.execute(
            "UPDATE resident_state SET needs_json=? WHERE season_id=? AND resident_id=?",
            (dumps(needs), season_id, resident["id"]),
        )
        connection.executemany(
            """
            INSERT INTO resident_needs(season_id,resident_id,need_key,satisfaction,updated_tick)
            VALUES(?,?,?,?,0)
            """,
            [(season_id, resident["id"], name, int(value)) for name, value in needs.items()],
        )
        aspiration = connection.execute(
            "SELECT biography FROM resident_identities WHERE resident_id=?", (resident["id"],)
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO resident_wants(
              season_id,resident_id,kind,description,status,priority,progress,created_tick
            ) VALUES(?,?,'aspiration',?,'active',70,0,0)
            """,
            (season_id, resident["id"], str(aspiration)[:300]),
        )
        if prior_season_id:
            for want in connection.execute(
                """
                SELECT id,kind,description,priority,progress FROM resident_wants
                WHERE season_id=? AND resident_id=? AND kind IN ('hobby','obligation')
                  AND status IN ('active','pursuing') ORDER BY priority DESC LIMIT 4
                """,
                (prior_season_id, resident["id"]),
            ):
                connection.execute(
                    """
                    INSERT INTO resident_wants(
                      season_id,resident_id,kind,description,status,priority,progress,
                      carry_over_from_want_id,created_tick
                    ) VALUES(?,?,?,?,?,?,?, ?,0)
                    """,
                    (season_id, resident["id"], want["kind"], want["description"], "active", want["priority"], want["progress"], want["id"]),
                )


def apply_lifecycle_boundary(connection: sqlite3.Connection, season_id: int, tick: int) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for row in connection.execute(
        """
        SELECT r.id,r.slug,r.name,l.current_stage,l.seasons_in_stage,l.alive
        FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        WHERE l.alive=1 ORDER BY r.id
        """
    ):
        stage = str(row["current_stage"])
        index = int(row["seasons_in_stage"]) + 1
        next_stage = stage
        alive = 1
        cause = None
        if stage == "baby" and index >= 1:
            next_stage, index = "child", 0
        elif stage == "child" and index >= 1:
            next_stage, index = "teen", 0
        elif stage == "teen" and index >= 1:
            next_stage, index = "adult", 0
        elif stage == "adult" and index >= 4:
            next_stage, index = "senior", 0
        elif stage == "senior" and index >= 2:
            next_stage, alive, cause = "deceased", 0, "natural old age"
        connection.execute(
            """
            UPDATE resident_lifecycle SET current_stage=?,seasons_in_stage=?,alive=?,
              stage_started_season_id=CASE WHEN current_stage<>? THEN ? ELSE stage_started_season_id END,
              death_season_id=CASE WHEN ?=0 THEN ? ELSE NULL END,
              death_tick=CASE WHEN ?=0 THEN ? ELSE NULL END,death_cause=?
            WHERE resident_id=?
            """,
            (next_stage, index, alive, next_stage, season_id, alive, season_id, alive, tick, cause, row["id"]),
        )
        if next_stage == "child":
            connection.execute(
                "UPDATE residents SET role='student',workplace='Oak Hill College' WHERE id=?",
                (row["id"],),
            )
            prior_care = connection.execute(
                "SELECT id,caregiver_resident_id FROM childcare_arrangements WHERE child_resident_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if prior_care:
                connection.execute(
                    "UPDATE childcare_arrangements SET status='ended',ended_season_id=?,ended_tick=? WHERE id=?",
                    (season_id, tick, prior_care["id"]),
                )
                school = connection.execute("SELECT id FROM businesses WHERE name='Krabville School'").fetchone()
                if school:
                    connection.execute(
                        """
                        INSERT INTO childcare_arrangements(
                          child_resident_id,arrangement_type,provider_business_id,cost_per_day_cents,
                          status,started_season_id,started_tick
                        ) VALUES(?,'school',?,4500,'active',?,?)
                        """,
                        (row["id"], school[0], season_id, tick),
                    )
                caregiver_id = prior_care["caregiver_resident_id"]
                if caregiver_id and not connection.execute(
                    """
                    SELECT 1 FROM childcare_arrangements c JOIN resident_lifecycle l ON l.resident_id=c.child_resident_id
                    WHERE c.caregiver_resident_id=? AND c.status='active' AND l.alive=1 AND l.current_stage='baby' LIMIT 1
                    """,
                    (caregiver_id,),
                ).fetchone():
                    connection.execute("UPDATE employment SET status='active' WHERE resident_id=? AND status='leave'", (caregiver_id,))
        elif next_stage == "teen":
            connection.execute(
                "UPDATE residents SET role='secondary student',workplace='Oak Hill College' WHERE id=?",
                (row["id"],),
            )
        elif next_stage == "adult" and stage != "adult":
            job = connection.execute(
                """
                SELECT j.id,j.title,j.hourly_wage_cents,b.name employer FROM jobs j
                LEFT JOIN businesses b ON b.id=j.business_id WHERE j.active=1
                ORDER BY ((j.id + ?) % 17),j.id LIMIT 1
                """,
                (row["id"],),
            ).fetchone()
            if job:
                connection.execute(
                    "UPDATE residents SET role=?,workplace=? WHERE id=?",
                    (job["title"], WORK_LOCATIONS.get(str(job["employer"]), "Town Square"), row["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO employment(
                      resident_id,job_id,status,hired_season_id,hired_tick,wage_cents,
                      scheduled_minutes_per_day,performance
                    ) VALUES(?,?,'active',?,?,?,450,50)
                    """,
                    (row["id"], job["id"], season_id, tick, job["hourly_wage_cents"]),
                )
        elif next_stage == "senior" and stage != "senior":
            connection.execute(
                """
                UPDATE employment SET status='retired',ended_season_id=?,ended_tick=?,end_reason='retirement'
                WHERE resident_id=? AND status IN ('active','leave','suspended')
                """,
                (season_id, tick, row["id"]),
            )
            connection.execute(
                "UPDATE residents SET role='retired resident',workplace=home WHERE id=?",
                (row["id"],),
            )
        elif not alive:
            connection.execute(
                """
                UPDATE employment SET status='terminated',ended_season_id=?,ended_tick=?,end_reason='death'
                WHERE resident_id=? AND status IN ('active','leave','suspended')
                """,
                (season_id, tick, row["id"]),
            )
        if next_stage != stage:
            title = f"{row['name']} became {('an ' if next_stage[0] in 'aeiou' else 'a ')}{next_stage}." if alive else f"Krabville said goodbye to {row['name']}."
            event_id = int(connection.execute(
                """
                INSERT INTO life_events(
                  season_id,tick,event_type,subject_resident_id,title,summary,outcome,severity,permanent,created_at
                ) VALUES(?,?,?,?,?,?,?,?,1,?) RETURNING id
                """,
                (season_id, tick, "life_stage" if alive else "death", row["id"], title, title, next_stage, 65 if alive else 100, now_iso()),
            ).fetchone()[0])
            connection.execute(
                """
                INSERT INTO story_ledger(
                  season_id,tick,day,entry_type,headline,summary,significance,visibility,life_event_id,created_at
                ) VALUES(?,?,7,?,?,?,?, 'public',?,?)
                """,
                (season_id, tick, "lifecycle", title, title, 70 if alive else 100, event_id, now_iso()),
            )
            changes.append({"resident": row["slug"], "from": stage, "to": next_stage})
            if not alive:
                _settle_estate(connection, season_id, tick, int(row["id"]))
    return changes


def _settle_estate(connection: sqlite3.Connection, season_id: int, tick: int, resident_id: int) -> None:
    heir = connection.execute(
        """
        SELECT r.id FROM family_links f JOIN residents r ON r.id=f.relative_resident_id
        JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
          AND l.current_stage IN ('adult','senior')
        WHERE f.resident_id=? AND f.ended_season_id IS NULL
          AND f.relation_type IN ('child','spouse','partner','sibling')
        ORDER BY CASE f.relation_type WHEN 'child' THEN 0 WHEN 'spouse' THEN 1 ELSE 2 END,r.id
        LIMIT 1
        """,
        (resident_id,),
    ).fetchone()
    source = connection.execute(
        "SELECT id FROM financial_accounts WHERE resident_id=? AND name='Personal chequing'",
        (resident_id,),
    ).fetchone()
    target = connection.execute(
        "SELECT id FROM financial_accounts WHERE resident_id=? AND name='Personal chequing'",
        (int(heir[0]),),
    ).fetchone() if heir else None
    if not source or not target:
        return
    amount = max(0, account_balance(connection, int(source[0])))
    if not amount:
        return
    transaction_id = int(connection.execute(
        """
        INSERT INTO financial_transactions(
          season_id,tick,category,description,status,external_key,created_at,posted_at
        ) VALUES(?,?,'inheritance','Estate inheritance','posted',?,?,?) RETURNING id
        """,
        (season_id, tick, f"estate:{resident_id}:{season_id}", now_iso(), now_iso()),
    ).fetchone()[0])
    connection.execute(
        "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,'estate transfer out')",
        (transaction_id, source[0], -amount),
    )
    connection.execute(
        "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,'inheritance received')",
        (transaction_id, target[0], amount),
    )


def add_next_generation(
    connection: sqlite3.Connection,
    season_id: int,
    tick: int,
    seed_hex: str,
    *,
    max_population: int = 32,
    max_adults: int = 24,
) -> list[dict[str, Any]]:
    living = int(connection.execute(
        "SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1"
    ).fetchone()[0])
    adults = list(connection.execute(
        """
        SELECT r.*,i.family_name,i.appearance_key,l.current_stage,hm.household_id,h.slug household_slug
        FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
        JOIN resident_identities i ON i.resident_id=r.id
        JOIN household_members hm ON hm.resident_id=r.id AND hm.ended_season_id IS NULL
        JOIN households h ON h.id=hm.household_id
        WHERE l.current_stage='adult' ORDER BY r.id
        """
    ))
    adult_count = int(connection.execute(
        "SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1 AND current_stage IN ('adult','senior')"
    ).fetchone()[0])
    if living >= max_population or adult_count >= max_adults or not adults:
        return []
    target_births = 2 if living < 16 else 1 if living < 24 else 0
    rng = _rng(seed_hex, "births", season_id)
    rng.shuffle(adults)
    names = ("Alex", "Bailey", "Cameron", "Dara", "Emery", "Finley", "Harper", "Indie", "Jules", "Kai", "Lane", "Marin", "Noel", "Parker", "River", "Shay", "Taylor", "Wren")
    births: list[dict[str, Any]] = []
    for index, parent in enumerate(adults[:target_births]):
        first = names[(season_id * 3 + index + rng.randrange(len(names))) % len(names)]
        family = str(parent["family_name"] or parent["name"].split()[-1])
        base_slug = "-".join(f"{first}-{family}".lower().split())
        slug = base_slug
        suffix = 2
        while connection.execute("SELECT 1 FROM residents WHERE slug=?", (slug,)).fetchone():
            slug, suffix = f"{base_slug}-{suffix}", suffix + 1
        display = f"{first} {family}"
        traits = loads(parent["traits_json"], {})
        traits = {key: max(0, min(100, int(value) + rng.randint(-7, 7))) for key, value in traits.items()}
        created = now_iso()
        child_id = int(connection.execute(
            """
            INSERT INTO residents(
              slug,name,role,home,workplace,color,traits_json,possessions_json,
              routine,about,created_at
            ) VALUES(?,?, 'dependent',?,?,?,?,?,'Care, play, sleep, and discover the Lagoon.',?,?)
            RETURNING id
            """,
            (
                slug, display, parent["home"], parent["home"], parent["color"],
                dumps(traits), dumps(["blanket", "family keepsake"]),
                f"Born in Season {season_id} to the {family} family.", created,
            ),
        ).fetchone()[0])
        connection.execute(
            """
            UPDATE resident_identities SET generation_seed=?,given_name=?,family_name=?,display_name=?,
              pronouns='they/them',gender_identity='developing',orientation='not specified',
              ancestry='Krabville',appearance_key=?,biography=?,generated_at=? WHERE resident_id=?
            """,
            (
                f"v2-birth:{season_id}:{slug}", first, family, display, parent["appearance_key"],
                f"Born in Season {season_id}; growing up in Krabville.", created, child_id,
            ),
        )
        connection.execute(
            """
            UPDATE resident_lifecycle SET birth_season_id=?,birth_tick=?,current_stage='baby',
              stage_started_season_id=?,seasons_in_stage=0,alive=1,genetic_seed=? WHERE resident_id=?
            """,
            (season_id, tick, season_id, f"genes:{parent['slug']}:{slug}", child_id),
        )
        connection.execute(
            """
            INSERT INTO household_members(
              household_id,resident_id,role,legal_guardian,financially_responsible,joined_season_id,joined_tick
            ) VALUES(?,?,'child',0,0,?,?)
            """,
            (parent["household_id"], child_id, season_id, tick),
        )
        connection.execute(
            """
            INSERT INTO family_links(
              resident_id,relative_resident_id,relation_type,biological,legal,started_season_id,started_tick
            ) VALUES(?,?,'parent',1,1,?,?),(?,?,'child',1,1,?,?)
            """,
            (child_id, parent["id"], season_id, tick, parent["id"], child_id, season_id, tick),
        )
        connection.execute(
            """
            INSERT INTO financial_accounts(resident_id,name,account_type,opening_balance_cents,opened_season_id,opened_tick)
            VALUES(?,'Personal chequing','chequing',0,?,?)
            """,
            (child_id, season_id, tick),
        )
        connection.execute(
            """
            INSERT INTO childcare_arrangements(
              child_resident_id,arrangement_type,caregiver_resident_id,cost_per_day_cents,
              status,started_season_id,started_tick
            ) VALUES(?,'parent',?,0,'active',?,?)
            """,
            (child_id, parent["id"], season_id, tick),
        )
        connection.execute("UPDATE employment SET status='leave' WHERE resident_id=? AND status='active'", (parent["id"],))
        event_id = int(connection.execute(
            """
            INSERT INTO life_events(
              season_id,tick,event_type,subject_resident_id,related_resident_id,household_id,
              title,summary,outcome,severity,permanent,created_at
            ) VALUES(?,?,'birth',?,?,?,?,?,'A new resident joined Krabville.',85,1,?) RETURNING id
            """,
            (
                season_id, tick, child_id, parent["id"], parent["household_id"],
                f"{display} was born", f"{display} joined the {family} family.", created,
            ),
        ).fetchone()[0])
        connection.execute(
            """
            INSERT INTO story_ledger(
              season_id,tick,day,entry_type,headline,summary,significance,visibility,life_event_id,created_at
            ) VALUES(?,?,7,'birth',?,?,85,'public',?,?)
            """,
            (season_id, tick, f"{display} was born", f"A new generation began in the {family} household.", event_id, created),
        )
        births.append({"resident": slug, "name": display, "parent": parent["slug"]})
        living += 1
        if living >= max_population:
            break
    return births


def account_balance(connection: sqlite3.Connection, account_id: int) -> int:
    row = connection.execute(
        """
        SELECT a.opening_balance_cents + COALESCE(SUM(CASE WHEN t.status='posted' THEN e.amount_cents ELSE 0 END),0)
        FROM financial_accounts a LEFT JOIN transaction_entries e ON e.account_id=a.id
        LEFT JOIN financial_transactions t ON t.id=e.transaction_id WHERE a.id=? GROUP BY a.id
        """,
        (account_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def settle_daily_economy(connection: sqlite3.Connection, season_id: int, day: int, tick: int) -> dict[str, int]:
    """Post one idempotent, balanced household settlement at 04:00."""

    clearing = connection.execute(
        """
        SELECT a.id FROM financial_accounts a JOIN businesses b ON b.id=a.business_id
        WHERE b.name='Krabville Credit Union' AND a.name='Operating'
        """
    ).fetchone()
    if not clearing:
        return {"transactions": 0, "wages": 0, "expenses": 0}
    clearing_id = int(clearing[0])
    totals = {"transactions": 0, "wages": 0, "expenses": 0, "childcare": 0, "debt": 0, "investments": 0}
    for row in connection.execute(
        """
        SELECT r.id,r.name,a.id account_id,e.wage_cents,e.scheduled_minutes_per_day,e.status
        FROM residents r JOIN financial_accounts a ON a.resident_id=r.id AND a.name='Personal chequing'
        LEFT JOIN employment e ON e.resident_id=r.id AND e.status IN ('active','leave')
        JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
        ORDER BY r.id
        """
    ):
        key = f"settlement:{day}:resident:{row['id']}"
        transaction_row = connection.execute(
            "SELECT id FROM financial_transactions WHERE season_id=? AND external_key=?",
            (season_id, key),
        ).fetchone()
        if transaction_row:
            continue
        investment = connection.execute(
            """
            SELECT i.*,a.id account_id FROM investments i JOIN financial_accounts a ON a.id=i.account_id
            WHERE a.resident_id=? ORDER BY i.id LIMIT 1
            """,
            (row["id"],),
        ).fetchone()
        debt = connection.execute(
            """
            SELECT d.*,a.id account_id FROM debts d JOIN financial_accounts a ON a.id=d.borrower_account_id
            WHERE a.resident_id=? AND d.status IN ('current','late','defaulted') ORDER BY d.id LIMIT 1
            """,
            (row["id"],),
        ).fetchone()
        childcare = 0
        for care in connection.execute(
            """
            SELECT c.child_resident_id,c.cost_per_day_cents FROM childcare_arrangements c
            JOIN family_links f ON f.relative_resident_id=c.child_resident_id
            WHERE f.resident_id=? AND f.relation_type='child' AND f.ended_season_id IS NULL
              AND c.status='active'
            """,
            (row["id"],),
        ):
            parent_count = int(connection.execute(
                """
                SELECT COUNT(*) FROM family_links WHERE relative_resident_id=?
                  AND relation_type='child' AND ended_season_id IS NULL
                """,
                (care["child_resident_id"],),
            ).fetchone()[0])
            childcare += int(care["cost_per_day_cents"]) // max(1, parent_count)
        before_bank = account_balance(connection, int(row["account_id"]))
        before_debt = int(debt["outstanding_cents"]) if debt else 0
        before_investment = int(investment["market_value_cents"]) if investment else 0
        result = settle_day({
            "balances": {
                "cash_cents": 0,
                "bank_cents": max(0, before_bank),
                "debt_cents": before_debt,
                "investments_cents": before_investment,
            },
            "employment": {
                "active": row["status"] == "active",
                "hourly_wage_cents": int(row["wage_cents"] or 0),
                "worked_minutes": int(row["scheduled_minutes_per_day"] or 0),
            } if row["status"] else {},
            "expenses": {"food": 1_800, "housing": 2_500, "utilities": 500, "transport": 600, "essentials": 400},
            "childcare": {"active": childcare > 0, "cost_per_day_cents": childcare},
            "debt": {
                "annual_rate_basis_points": int(debt["annual_rate_basis_points"]) if debt else 750,
                "minimum_payment_cents": int(debt["minimum_payment_cents"]) if debt else 0,
            },
            "investment_return_bps": _rng(str(season_id), "investment", day, row["id"]).randint(-20, 20),
        })
        after = result["balances"]
        liquid_delta = int(after["bank_cents"] + after["cash_cents"] - before_bank)
        investment_delta = int(after["investments_cents"] - before_investment)
        debt_delta = int(after["debt_cents"] - before_debt)
        if debt:
            connection.execute(
                "UPDATE debts SET outstanding_cents=?,status=CASE WHEN ?=0 THEN 'paid' ELSE status END WHERE id=?",
                (after["debt_cents"], after["debt_cents"], debt["id"]),
            )
            debt_account_id = int(debt["account_id"])
        elif int(after["debt_cents"]) > 0:
            debt_account_id = int(connection.execute(
                """
                INSERT INTO financial_accounts(resident_id,name,account_type,opening_balance_cents,opened_season_id,opened_tick)
                VALUES(?,'Emergency credit','loan',0,?,?) RETURNING id
                """,
                (row["id"], season_id, tick),
            ).fetchone()[0])
            connection.execute(
                """
                INSERT INTO debts(
                  borrower_account_id,debt_type,principal_cents,outstanding_cents,
                  annual_rate_basis_points,minimum_payment_cents,opened_season_id,opened_tick,status
                ) VALUES(?,'credit',?,?,750,2500,?,?,'current')
                """,
                (debt_account_id, after["debt_cents"], after["debt_cents"], season_id, tick),
            )
        else:
            debt_account_id = None
        if investment:
            connection.execute(
                "UPDATE investments SET market_value_cents=?,updated_season_id=?,updated_tick=? WHERE id=?",
                (after["investments_cents"], season_id, tick, investment["id"]),
            )
        transaction_id = int(connection.execute(
            """
            INSERT INTO financial_transactions(
              season_id,tick,category,description,status,external_key,created_at,posted_at
            ) VALUES(?,?, 'daily_settlement',?,'posted',?,?,?) RETURNING id
            """,
            (season_id, tick, f"Daily economy settlement for {row['name']}", key, now_iso(), now_iso()),
        ).fetchone()[0])
        entries: list[tuple[int, int, str]] = []
        if liquid_delta:
            entries.append((int(row["account_id"]), liquid_delta, "daily liquid change"))
        if investment_delta and investment:
            entries.append((int(investment["account_id"]), investment_delta, "investment valuation"))
        if debt_delta and debt_account_id:
            entries.append((debt_account_id, -debt_delta, "debt liability change"))
        offset = -sum(amount for _, amount, _ in entries)
        if offset:
            entries.append((clearing_id, offset, "town clearing"))
        connection.executemany(
            "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,?)",
            [(transaction_id, account_id, amount, memo) for account_id, amount, memo in entries],
        )
        totals["transactions"] += 1
        totals["wages"] += int(result["totals"]["wages_cents"])
        totals["expenses"] += int(result["totals"]["expenses_cents"])
        totals["childcare"] += int(result["totals"]["childcare_cents"])
        totals["debt"] += int(after["debt_cents"])
        totals["investments"] += int(after["investments_cents"])
    return totals


def resident_finances(connection: sqlite3.Connection, resident_id: int) -> dict[str, int]:
    account = connection.execute(
        "SELECT id FROM financial_accounts WHERE resident_id=? AND name='Personal chequing'",
        (resident_id,),
    ).fetchone()
    cash = account_balance(connection, int(account[0])) if account else 0
    debt = int(connection.execute(
        """
        SELECT COALESCE(SUM(d.outstanding_cents),0) FROM debts d
        JOIN financial_accounts a ON a.id=d.borrower_account_id
        WHERE a.resident_id=? AND d.status IN ('current','late','defaulted')
        """,
        (resident_id,),
    ).fetchone()[0])
    return {"cashCents": cash, "debtCents": debt}
