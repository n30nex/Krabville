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
        SELECT r.id,r.slug,r.name,l.current_stage,l.seasons_in_stage,l.alive,
          hm.household_id
        FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        LEFT JOIN household_members hm ON hm.resident_id=r.id AND hm.ended_season_id IS NULL
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
            connection.execute(
                """
                UPDATE household_members SET role='head',legal_guardian=1,financially_responsible=1
                WHERE resident_id=? AND ended_season_id IS NULL
                """,
                (row["id"],),
            )
            connection.execute(
                """
                UPDATE childcare_arrangements SET status='ended',ended_season_id=?,ended_tick=?
                WHERE child_resident_id=? AND status='active'
                """,
                (season_id, tick, row["id"]),
            )
            _hire_resident(connection, int(row["id"]), season_id, tick)
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
            connection.execute(
                """
                UPDATE childcare_arrangements SET status='ended',ended_season_id=?,ended_tick=?
                WHERE caregiver_resident_id=? AND status='active'
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
                connection.execute(
                    """
                    UPDATE household_members SET ended_season_id=?,ended_tick=?,end_reason='death'
                    WHERE resident_id=? AND ended_season_id IS NULL
                    """,
                    (season_id, tick, row["id"]),
                )
                if row["household_id"]:
                    _release_empty_household(
                        connection, season_id, tick, int(row["household_id"])
                    )
    return changes


def _hire_resident(
    connection: sqlite3.Connection, resident_id: int, season_id: int, tick: int
) -> bool:
    if connection.execute(
        "SELECT 1 FROM employment WHERE resident_id=? AND status IN ('active','leave','suspended')",
        (resident_id,),
    ).fetchone():
        return True
    job = connection.execute(
        """
        SELECT j.id,j.title,j.hourly_wage_cents,b.name employer,
          COALESCE(NULLIF(p.map_location,''),p.name,b.name,'Town Square') workplace
        FROM jobs j
        LEFT JOIN businesses b ON b.id=j.business_id
        LEFT JOIN properties p ON p.id=b.property_id
        WHERE j.active=1 AND (
          SELECT COUNT(*) FROM employment e
          WHERE e.job_id=j.id AND e.status IN ('offered','active','leave','suspended')
        ) < j.positions
        ORDER BY ((j.id + ?) % 31),j.id LIMIT 1
        """,
        (resident_id,),
    ).fetchone()
    if not job:
        connection.execute(
            "UPDATE residents SET role='career seeker',workplace='Town Square' WHERE id=?",
            (resident_id,),
        )
        return False
    connection.execute(
        "UPDATE residents SET role=?,workplace=? WHERE id=?",
        (job["title"], job["workplace"], resident_id),
    )
    connection.execute(
        """
        INSERT INTO employment(
          resident_id,job_id,status,hired_season_id,hired_tick,wage_cents,
          scheduled_minutes_per_day,performance
        ) VALUES(?,?,'active',?,?,?,450,50)
        """,
        (resident_id, job["id"], season_id, tick, job["hourly_wage_cents"]),
    )
    return True


def _release_empty_household(
    connection: sqlite3.Connection, season_id: int, tick: int, household_id: int
) -> None:
    if connection.execute(
        """
        SELECT 1 FROM household_members hm JOIN resident_lifecycle l ON l.resident_id=hm.resident_id
        WHERE hm.household_id=? AND hm.ended_season_id IS NULL AND l.alive=1 LIMIT 1
        """,
        (household_id,),
    ).fetchone():
        return
    heir_household = connection.execute(
        """
        SELECT heir_home.household_id
        FROM household_members former
        JOIN family_links family ON family.resident_id=former.resident_id
          AND family.ended_season_id IS NULL
        JOIN resident_lifecycle heir_life ON heir_life.resident_id=family.relative_resident_id
          AND heir_life.alive=1
        JOIN household_members heir_home ON heir_home.resident_id=family.relative_resident_id
          AND heir_home.ended_season_id IS NULL
        WHERE former.household_id=?
        ORDER BY CASE family.relation_type
          WHEN 'child' THEN 0 WHEN 'spouse' THEN 1 WHEN 'partner' THEN 2 ELSE 3 END,
          family.relative_resident_id LIMIT 1
        """,
        (household_id,),
    ).fetchone()
    heir_household_id = int(heir_household[0]) if heir_household else None
    if heir_household_id and heir_household_id != household_id:
        source_account = connection.execute(
            "SELECT id FROM financial_accounts WHERE household_id=? AND name='Household chequing' AND status='open'",
            (household_id,),
        ).fetchone()
        target_account = connection.execute(
            "SELECT id FROM financial_accounts WHERE household_id=? AND name='Household chequing' AND status='open'",
            (heir_household_id,),
        ).fetchone()
        if source_account and target_account:
            amount = max(0, account_balance(connection, int(source_account[0])))
            if amount:
                transaction_id = int(connection.execute(
                    """
                    INSERT INTO financial_transactions(
                      season_id,tick,category,description,status,external_key,created_at,posted_at
                    ) VALUES(?,?,'inheritance','Household estate transfer','posted',?,?,?) RETURNING id
                    """,
                    (season_id, tick, f"household-estate:{household_id}:{season_id}", now_iso(), now_iso()),
                ).fetchone()[0])
                connection.executemany(
                    "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,?)",
                    (
                        (transaction_id, source_account[0], -amount, "household estate transfer out"),
                        (transaction_id, target_account[0], amount, "household estate received"),
                    ),
                )
        for item in list(connection.execute(
            "SELECT item_id,quantity,condition_score,acquired_tick,expires_tick FROM household_inventory WHERE household_id=? AND quantity>0",
            (household_id,),
        )):
            connection.execute(
                """
                INSERT INTO household_inventory(
                  household_id,item_id,quantity,condition_score,acquired_tick,expires_tick
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(household_id,item_id) DO UPDATE SET
                  quantity=quantity+excluded.quantity,
                  condition_score=MAX(condition_score,excluded.condition_score),
                  acquired_tick=MAX(acquired_tick,excluded.acquired_tick)
                """,
                (
                    heir_household_id, item["item_id"], item["quantity"], item["condition_score"],
                    item["acquired_tick"], item["expires_tick"],
                ),
            )
            connection.execute(
                """
                INSERT INTO inventory_movements(
                  season_id,tick,item_id,quantity,movement_type,from_kind,from_id,to_kind,to_id,note,created_at
                ) VALUES(?,?,?,?,'inherit','household',?,'household',?,'household estate',?)
                """,
                (
                    season_id, tick, item["item_id"], item["quantity"], household_id,
                    heir_household_id, now_iso(),
                ),
            )
        connection.execute("DELETE FROM household_inventory WHERE household_id=?", (household_id,))
        connection.execute(
            """
            UPDATE property_ownership SET household_id=?
            WHERE household_id=? AND disposed_season_id IS NULL
            """,
            (heir_household_id, household_id),
        )
    occupancies = list(connection.execute(
        "SELECT id,property_id FROM property_occupancy WHERE household_id=? AND ended_season_id IS NULL",
        (household_id,),
    ))
    connection.execute(
        """
        UPDATE property_occupancy SET ended_season_id=?,ended_tick=?,end_reason='household dissolved'
        WHERE household_id=? AND ended_season_id IS NULL
        """,
        (season_id, tick, household_id),
    )
    for occupancy in occupancies:
        occupied = connection.execute(
            "SELECT 1 FROM property_occupancy WHERE property_id=? AND ended_season_id IS NULL LIMIT 1",
            (occupancy["property_id"],),
        ).fetchone()
        connection.execute(
            "UPDATE properties SET status=? WHERE id=?",
            ("occupied" if occupied else "available", occupancy["property_id"]),
        )
    connection.execute(
        """
        UPDATE households SET status='dissolved',dissolved_season_id=?,dissolved_tick=?
        WHERE id=? AND status<>'dissolved'
        """,
        (season_id, tick, household_id),
    )
    connection.execute(
        """
        UPDATE financial_accounts SET status='closed',closed_season_id=?,closed_tick=?
        WHERE household_id=? AND status='open'
        """,
        (season_id, tick, household_id),
    )


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
    heir_id = int(heir[0]) if heir else None
    target = connection.execute(
        "SELECT id FROM financial_accounts WHERE resident_id=? AND name='Personal chequing' AND status='open'",
        (heir_id,),
    ).fetchone() if heir_id else None
    if target:
        for source in connection.execute(
            """
            SELECT id FROM financial_accounts
            WHERE resident_id=? AND status='open' AND account_type IN ('cash','chequing','savings')
            ORDER BY id
            """,
            (resident_id,),
        ):
            if int(source["id"]) == int(target[0]):
                continue
            amount = max(0, account_balance(connection, int(source["id"])))
            if not amount:
                continue
            transaction_id = int(connection.execute(
                """
                INSERT INTO financial_transactions(
                  season_id,tick,category,description,status,external_key,created_at,posted_at
                ) VALUES(?,?,'inheritance','Estate inheritance','posted',?,?,?) RETURNING id
                """,
                (
                    season_id, tick, f"estate:{resident_id}:{source['id']}:{season_id}",
                    now_iso(), now_iso(),
                ),
            ).fetchone()[0])
            connection.executemany(
                "INSERT INTO transaction_entries(transaction_id,account_id,amount_cents,memo) VALUES(?,?,?,?)",
                (
                    (transaction_id, source["id"], -amount, "estate transfer out"),
                    (transaction_id, target[0], amount, "inheritance received"),
                ),
            )
        target_investment = connection.execute(
            "SELECT id FROM financial_accounts WHERE resident_id=? AND name='Investments'",
            (heir_id,),
        ).fetchone()
        if not target_investment:
            target_investment = connection.execute(
                """
                INSERT INTO financial_accounts(
                  resident_id,name,account_type,opening_balance_cents,opened_season_id,opened_tick
                ) VALUES(?,'Investments','investment',0,?,?) RETURNING id
                """,
                (heir_id, season_id, tick),
            ).fetchone()
        for investment in list(connection.execute(
            """
            SELECT i.* FROM investments i JOIN financial_accounts a ON a.id=i.account_id
            WHERE a.resident_id=?
            """,
            (resident_id,),
        )):
            existing = connection.execute(
                "SELECT id FROM investments WHERE account_id=? AND symbol=?",
                (target_investment[0], investment["symbol"]),
            ).fetchone()
            if existing:
                connection.execute(
                    """
                    UPDATE investments SET units=units+?,market_value_cents=market_value_cents+?,
                      updated_season_id=?,updated_tick=? WHERE id=?
                    """,
                    (
                        investment["units"], investment["market_value_cents"], season_id,
                        tick, existing[0],
                    ),
                )
                connection.execute("DELETE FROM investments WHERE id=?", (investment["id"],))
            else:
                connection.execute(
                    "UPDATE investments SET account_id=?,updated_season_id=?,updated_tick=? WHERE id=?",
                    (target_investment[0], season_id, tick, investment["id"]),
                )
        for item in list(connection.execute(
            "SELECT item_id,quantity,condition_score,acquired_tick,expires_tick FROM resident_inventory WHERE resident_id=? AND quantity>0",
            (resident_id,),
        )):
            connection.execute(
                """
                INSERT INTO resident_inventory(
                  resident_id,item_id,quantity,condition_score,acquired_tick,expires_tick
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(resident_id,item_id) DO UPDATE SET
                  quantity=quantity+excluded.quantity,
                  condition_score=MAX(condition_score,excluded.condition_score),
                  acquired_tick=MAX(acquired_tick,excluded.acquired_tick)
                """,
                (
                    heir_id, item["item_id"], item["quantity"], item["condition_score"],
                    item["acquired_tick"], item["expires_tick"],
                ),
            )
        connection.execute("DELETE FROM resident_inventory WHERE resident_id=?", (resident_id,))
        connection.execute(
            "UPDATE assets SET resident_id=? WHERE resident_id=? AND disposed_season_id IS NULL",
            (heir_id, resident_id),
        )
    else:
        connection.execute(
            """
            UPDATE investments SET units=0,market_value_cents=0,updated_season_id=?,updated_tick=?
            WHERE account_id IN (SELECT id FROM financial_accounts WHERE resident_id=?)
            """,
            (season_id, tick, resident_id),
        )
    connection.execute(
        """
        UPDATE debts SET status='forgiven',outstanding_cents=0,closed_season_id=?,closed_tick=?
        WHERE borrower_account_id IN (SELECT id FROM financial_accounts WHERE resident_id=?)
          AND status IN ('current','late','defaulted')
        """,
        (season_id, tick, resident_id),
    )
    connection.execute(
        """
        UPDATE financial_accounts SET status='closed',closed_season_id=?,closed_tick=?
        WHERE resident_id=? AND status='open'
        """,
        (season_id, tick, resident_id),
    )


def add_next_generation(
    connection: sqlite3.Connection,
    season_id: int,
    tick: int,
    seed_hex: str,
    *,
    max_population: int = 32,
    max_adults: int = 24,
    target_population: int | None = None,
    max_births: int = 1,
) -> list[dict[str, Any]]:
    living = int(connection.execute(
        "SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1"
    ).fetchone()[0])
    adults = list(connection.execute(
        """
        SELECT r.*,i.family_name,i.appearance_key,l.current_stage,hm.household_id,
          h.slug household_slug,p.id property_id,p.resident_capacity,
          (
            SELECT COUNT(*) FROM property_occupancy occupied
            JOIN household_members member ON member.household_id=occupied.household_id
              AND member.ended_season_id IS NULL
            JOIN resident_lifecycle life ON life.resident_id=member.resident_id AND life.alive=1
            WHERE occupied.property_id=p.id AND occupied.ended_season_id IS NULL
          ) property_residents,
          (
            SELECT COUNT(*) FROM family_links children
            JOIN resident_lifecycle child_life ON child_life.resident_id=children.relative_resident_id
              AND child_life.alive=1 AND child_life.current_stage IN ('baby','child','teen')
            WHERE children.resident_id=r.id AND children.relation_type='child'
              AND children.ended_season_id IS NULL
          ) dependent_count
        FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
        JOIN resident_identities i ON i.resident_id=r.id
        JOIN household_members hm ON hm.resident_id=r.id AND hm.ended_season_id IS NULL
        JOIN households h ON h.id=hm.household_id
        JOIN property_occupancy po ON po.household_id=h.id AND po.ended_season_id IS NULL
        JOIN properties p ON p.id=po.property_id
        WHERE l.current_stage='adult' AND p.resident_capacity>(
          SELECT COUNT(*) FROM property_occupancy occupied
          JOIN household_members member ON member.household_id=occupied.household_id
            AND member.ended_season_id IS NULL
          JOIN resident_lifecycle life ON life.resident_id=member.resident_id AND life.alive=1
          WHERE occupied.property_id=p.id AND occupied.ended_season_id IS NULL
        )
        ORDER BY dependent_count,r.id
        """
    ))
    adult_count = int(connection.execute(
        "SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1 AND current_stage IN ('adult','senior')"
    ).fetchone()[0])
    target_population = min(max_population, target_population or max_population)
    if living >= target_population or adult_count > max_adults or not adults or max_births <= 0:
        return []
    target_births = min(max_births, target_population - living)
    rng = _rng(seed_hex, "births", season_id)
    adults.sort(key=lambda resident: (int(resident["dependent_count"]), rng.random()))
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
        for sku in ("baby-clothes", "blanket", "stuffed-toy"):
            item = connection.execute("SELECT id FROM item_catalog WHERE sku=?", (sku,)).fetchone()
            if item:
                connection.execute(
                    """
                    INSERT INTO resident_inventory(resident_id,item_id,quantity,acquired_tick)
                    VALUES(?,?,1,?) ON CONFLICT(resident_id,item_id) DO NOTHING
                    """,
                    (child_id, item["id"], tick),
                )
        for sku, quantity in (("diapers", 3), ("baby-formula", 3), ("baby-bottle", 1)):
            item = connection.execute("SELECT id FROM item_catalog WHERE sku=?", (sku,)).fetchone()
            if item:
                connection.execute(
                    """
                    INSERT INTO household_inventory(household_id,item_id,quantity,acquired_tick)
                    VALUES(?,?,?,?) ON CONFLICT(household_id,item_id)
                    DO UPDATE SET quantity=quantity+excluded.quantity,acquired_tick=excluded.acquired_tick
                    """,
                    (parent["household_id"], item["id"], quantity, tick),
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


_NEWCOMER_GIVEN_NAMES = (
    "Ada", "Aiden", "Alina", "Andre", "Anika", "Beatrice", "Caleb", "Celine",
    "Dalia", "Diego", "Eden", "Farah", "Felix", "Gia", "Hugo", "Ines",
    "Jamal", "Keira", "Kenji", "Lina", "Malik", "Marta", "Nadia", "Nolan",
    "Orla", "Paolo", "Ravi", "Rosa", "Sana", "Tomas", "Uma", "Yara",
)
_NEWCOMER_FAMILY_NAMES = (
    "Abebe", "Bennett", "Chen", "Costa", "Dubois", "El-Amin", "Fernandes", "Gill",
    "Hernandez", "Ito", "Johnson", "Kaur", "Laurent", "Mensah", "Novak", "Osborne",
    "Patel", "Quinn", "Rossi", "Singh", "Turner", "Usman", "Vega", "Wong",
)
_NEWCOMER_COLORS = (
    "#53b3cb", "#f4b942", "#e76f51", "#78c091", "#9b7ede", "#e56b9f",
    "#4d908e", "#f9844a", "#90be6d", "#577590", "#f9c74f", "#43aa8b",
)


def population_target_for_season(season_number: int) -> int:
    """Grow from 12 to 24 residents across the twenty-season campaign."""

    bounded = max(0, min(20, int(season_number)))
    return 12 + (12 * bounded + 19) // 20


def _available_home(connection: sqlite3.Connection, residents_needed: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT p.*,
          COUNT(DISTINCT CASE WHEN po.ended_season_id IS NULL THEN po.household_id END) active_households,
          COUNT(DISTINCT CASE WHEN po.ended_season_id IS NULL AND hm.ended_season_id IS NULL
            AND life.alive=1 THEN hm.resident_id END) active_residents
        FROM properties p
        LEFT JOIN property_occupancy po ON po.property_id=p.id AND po.ended_season_id IS NULL
        LEFT JOIN household_members hm ON hm.household_id=po.household_id AND hm.ended_season_id IS NULL
        LEFT JOIN resident_lifecycle life ON life.resident_id=hm.resident_id AND life.alive=1
        WHERE p.property_type IN ('house','apartment')
          AND p.status NOT IN ('planned','damaged','closed','demolished')
        GROUP BY p.id
        HAVING p.resident_capacity-active_residents>=?
          AND (p.property_type='apartment' OR active_households=0)
        ORDER BY CASE WHEN p.property_type='apartment' THEN 0 ELSE 1 END,
          CASE WHEN active_households>0 THEN 0 ELSE 1 END,
          p.resident_capacity-active_residents,p.id LIMIT 1
        """,
        (residents_needed,),
    ).fetchone()


def _unique_resident_slug(connection: sqlite3.Connection, given: str, family: str) -> str:
    base = "-".join(f"{given}-{family}".casefold().replace("'", "").split())
    slug = base
    suffix = 2
    while connection.execute("SELECT 1 FROM residents WHERE slug=?", (slug,)).fetchone():
        slug, suffix = f"{base}-{suffix}", suffix + 1
    return slug


def _create_newcomer_resident(
    connection: sqlite3.Connection,
    *,
    season_id: int,
    tick: int,
    seed_hex: str,
    household_id: int,
    home: str,
    given: str,
    family: str,
    stage: str,
    role: str,
    ordinal: int,
) -> dict[str, Any]:
    rng = _rng(seed_hex, "newcomer", season_id, household_id, ordinal)
    slug = _unique_resident_slug(connection, given, family)
    name = f"{given} {family}"
    traits = {
        key: rng.randint(30, 86)
        for key in (
            "openness", "conscientiousness", "extraversion", "agreeableness",
            "emotionalStability", "empathy", "ambition", "spontaneity",
        )
    }
    appearance = {
        "style": rng.choice(("practical", "casual", "artsy", "outdoorsy", "polished")),
        "accentColor": _NEWCOMER_COLORS[(season_id + ordinal) % len(_NEWCOMER_COLORS)],
        "skinTone": rng.choice(("deep", "tan", "medium", "olive", "light-medium", "light")),
        "hairColor": rng.choice(("black", "dark brown", "brown", "auburn")),
        "hairTexture": rng.choice(("straight", "wavy", "curly", "coils", "braided")),
        "eyeColor": rng.choice(("brown", "hazel", "green", "blue")),
    }
    resident_role = {
        "baby": "dependent", "child": "student", "teen": "secondary student",
        "adult": "career seeker", "senior": "retired resident",
    }[stage]
    workplace = "Oak Hill College" if stage in {"child", "teen"} else home
    created = now_iso()
    resident_id = int(connection.execute(
        """
        INSERT INTO residents(
          slug,name,role,home,workplace,color,traits_json,possessions_json,
          routine,about,created_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id
        """,
        (
            slug, name, resident_role, home, workplace, appearance["accentColor"],
            dumps(traits), dumps(["phone", "house keys"] if stage in {"teen", "adult", "senior"} else ["family keepsake"]),
            "Build a stable daily life while getting to know neighbours.",
            f"Moved to Krabville in Season {season_id} with the {family} household.", created,
        ),
    ).fetchone()[0])
    connection.execute(
        """
        UPDATE resident_identities SET generation_seed=?,given_name=?,family_name=?,display_name=?,
          pronouns='they/them',gender_identity=?,orientation=?,ancestry='newcomer',
          appearance_key=?,biography=?,generated_at=? WHERE resident_id=?
        """,
        (
            f"v21-arrival:{season_id}:{slug}", given, family, name,
            "developing" if stage in MINOR_STAGES else rng.choice(("woman", "man", "nonbinary")),
            "not specified" if stage in MINOR_STAGES else rng.choice(("heterosexual", "bisexual", "pansexual", "gay", "lesbian", "asexual")),
            dumps(appearance), f"Arrived in Season {season_id} and is making a life in Krabville.",
            created, resident_id,
        ),
    )
    stage_index = rng.randint(0, 2) if stage == "adult" else 0
    connection.execute(
        """
        UPDATE resident_lifecycle SET current_stage=?,seasons_in_stage=?,alive=1,
          stage_started_season_id=?,genetic_seed=? WHERE resident_id=?
        """,
        (stage, stage_index, season_id, f"genes:v21:{slug}", resident_id),
    )
    connection.execute(
        """
        INSERT INTO household_members(
          household_id,resident_id,role,legal_guardian,financially_responsible,
          joined_season_id,joined_tick
        ) VALUES(?,?,?,?,?,?,?)
        """,
        (
            household_id, resident_id, role, int(stage in ADULT_STAGES),
            int(stage in ADULT_STAGES), season_id, tick,
        ),
    )
    opening = 0 if stage in MINOR_STAGES else rng.randint(90_000, 950_000)
    connection.execute(
        """
        INSERT INTO financial_accounts(
          resident_id,name,account_type,opening_balance_cents,opened_season_id,opened_tick
        ) VALUES(?,'Personal chequing','chequing',?,?,?)
        """,
        (resident_id, opening, season_id, tick),
    )
    if stage in ADULT_STAGES:
        connection.execute(
            """
            INSERT INTO financial_accounts(
              resident_id,name,account_type,opening_balance_cents,opened_season_id,opened_tick
            ) VALUES(?,'Savings','savings',?,?,?)
            """,
            (resident_id, rng.randint(50_000, 1_250_000), season_id, tick),
        )
    if stage in {"teen", "adult", "senior"}:
        connection.execute(
            "INSERT OR IGNORE INTO resident_phones(resident_id,phone_number,issued_season_id,issued_tick) VALUES(?,?,?,?)",
            (resident_id, f"+1 226-555-{100 + resident_id:04d}", season_id, tick),
        )
    if stage == "adult":
        _hire_resident(connection, resident_id, season_id, tick)
    return {"id": resident_id, "slug": slug, "name": name, "stage": stage}


def _add_newcomer_households(
    connection: sqlite3.Connection,
    season_id: int,
    tick: int,
    seed_hex: str,
    target_population: int,
    max_adults: int,
) -> list[dict[str, Any]]:
    arrivals: list[dict[str, Any]] = []
    season_number = int(connection.execute("SELECT number FROM seasons WHERE id=?", (season_id,)).fetchone()[0])
    while True:
        living, adult_count = connection.execute(
            """
            SELECT COUNT(*),COALESCE(SUM(current_stage IN ('adult','senior')),0)
            FROM resident_lifecycle WHERE alive=1
            """
        ).fetchone()
        remaining = target_population - int(living)
        if remaining <= 0:
            break
        group_size = min(3, remaining)
        if group_size == 1:
            stages = ["adult"]
        elif group_size == 2:
            stages = ["adult", "child"] if season_number % 2 else ["adult", "adult"]
        else:
            stages = ["adult", "adult", "child"]
        while int(adult_count) + sum(stage == "adult" for stage in stages) > max_adults:
            stages[stages.index("adult")] = "teen"
        home = _available_home(connection, len(stages))
        if not home:
            break
        rng = _rng(seed_hex, "arrival-household", season_id, len(arrivals))
        family_index = (season_number * 5 + len(arrivals) * 7 + rng.randrange(len(_NEWCOMER_FAMILY_NAMES))) % len(_NEWCOMER_FAMILY_NAMES)
        family = _NEWCOMER_FAMILY_NAMES[family_index]
        for _ in _NEWCOMER_FAMILY_NAMES:
            if not connection.execute(
                "SELECT 1 FROM households WHERE name=? AND status='active'",
                (f"{family} household",),
            ).fetchone():
                break
            family_index = (family_index + 1) % len(_NEWCOMER_FAMILY_NAMES)
            family = _NEWCOMER_FAMILY_NAMES[family_index]
        base_slug = "-".join(f"{family}-household-s{season_number}".casefold().replace("'", "").split())
        household_slug = base_slug
        suffix = 2
        while connection.execute("SELECT 1 FROM households WHERE slug=?", (household_slug,)).fetchone():
            household_slug, suffix = f"{base_slug}-{suffix}", suffix + 1
        household_type = "single" if len(stages) == 1 else "family" if any(stage in MINOR_STAGES for stage in stages) else "couple"
        household_id = int(connection.execute(
            """
            INSERT INTO households(
              slug,name,household_type,status,founded_season_id,founded_tick,financial_policy,created_at
            ) VALUES(?,?,?,'active',?,?,'mixed',?) RETURNING id
            """,
            (household_slug, f"{family} household", household_type, season_id, tick, now_iso()),
        ).fetchone()[0])
        home_name = str(home["map_location"] or home["name"])
        connection.execute(
            """
            INSERT INTO property_occupancy(
              property_id,household_id,occupancy_type,monthly_cost_cents,
              started_season_id,started_tick
            ) VALUES(?,?,'renter',?,?,?)
            """,
            (
                home["id"], household_id,
                118_000 + len(stages) * 18_000 if home["property_type"] == "apartment" else 176_000,
                season_id, tick,
            ),
        )
        connection.execute("UPDATE properties SET status='occupied' WHERE id=?", (home["id"],))
        connection.execute(
            """
            INSERT INTO financial_accounts(
              household_id,name,account_type,opening_balance_cents,opened_season_id,opened_tick
            ) VALUES(?,'Household chequing','chequing',?,?,?)
            """,
            (household_id, rng.randint(350_000, 1_800_000), season_id, tick),
        )
        people: list[dict[str, Any]] = []
        used_given: set[str] = set()
        for ordinal, stage in enumerate(stages):
            given_index = (season_number * 3 + household_id * 5 + ordinal * 11) % len(_NEWCOMER_GIVEN_NAMES)
            given = _NEWCOMER_GIVEN_NAMES[given_index]
            while given in used_given:
                given_index = (given_index + 1) % len(_NEWCOMER_GIVEN_NAMES)
                given = _NEWCOMER_GIVEN_NAMES[given_index]
            used_given.add(given)
            people.append(_create_newcomer_resident(
                connection, season_id=season_id, tick=tick, seed_hex=seed_hex,
                household_id=household_id, home=home_name, given=given, family=family,
                stage=stage, role="head" if ordinal == 0 else "partner" if stage == "adult" else "child",
                ordinal=ordinal,
            ))
        adults = [person for person in people if person["stage"] == "adult"]
        minors = [person for person in people if person["stage"] in MINOR_STAGES]
        if len(adults) >= 2:
            connection.execute(
                """
                INSERT INTO family_links(
                  resident_id,relative_resident_id,relation_type,legal,started_season_id,started_tick
                ) VALUES(?,?,'partner',1,?,?),(?,?,'partner',1,?,?)
                """,
                (adults[0]["id"], adults[1]["id"], season_id, tick, adults[1]["id"], adults[0]["id"], season_id, tick),
            )
        for minor in minors:
            parent = adults[0]
            connection.execute(
                """
                INSERT INTO family_links(
                  resident_id,relative_resident_id,relation_type,biological,legal,started_season_id,started_tick
                ) VALUES(?,?,'parent',1,1,?,?),(?,?,'child',1,1,?,?)
                """,
                (minor["id"], parent["id"], season_id, tick, parent["id"], minor["id"], season_id, tick),
            )
            provider = connection.execute(
                "SELECT id FROM businesses WHERE name IN ('Canal Childcare','Krabville School') ORDER BY name='Canal Childcare' DESC LIMIT 1"
            ).fetchone()
            if provider:
                connection.execute(
                    """
                    INSERT INTO childcare_arrangements(
                      child_resident_id,arrangement_type,provider_business_id,cost_per_day_cents,
                      status,started_season_id,started_tick
                    ) VALUES(?,'school',?,4500,'active',?,?)
                    """,
                    (minor["id"], provider[0], season_id, tick),
                )
        event_id = int(connection.execute(
            """
            INSERT INTO life_events(
              season_id,tick,event_type,subject_resident_id,household_id,property_id,
              title,summary,outcome,severity,permanent,created_at
            ) VALUES(?,?,'arrival',?,?,?,?,?,'settled',68,1,?) RETURNING id
            """,
            (
                season_id, tick, people[0]["id"], household_id, home["id"],
                f"The {family} household arrived",
                f"{', '.join(person['name'] for person in people)} moved into {home_name}.", now_iso(),
            ),
        ).fetchone()[0])
        connection.executemany(
            "INSERT INTO life_event_participants(life_event_id,resident_id,role) VALUES(?,?,'newcomer')",
            ((event_id, person["id"]) for person in people),
        )
        connection.execute(
            """
            INSERT INTO story_ledger(
              season_id,tick,day,entry_type,headline,summary,significance,visibility,life_event_id,created_at
            ) VALUES(?,?,7,'arrival',?,?,72,'public',?,?)
            """,
            (
                season_id, tick, f"The {family} household joined Krabville",
                f"A new household settled at {home_name}, bringing {len(people)} residents.",
                event_id, now_iso(),
            ),
        )
        arrivals.append({
            "household": household_slug, "home": home_name,
            "residents": [person["slug"] for person in people],
        })
    return arrivals


def _repair_guardians(connection: sqlite3.Connection, season_id: int, tick: int) -> list[dict[str, Any]]:
    repaired: list[dict[str, Any]] = []
    minors = list(connection.execute(
        """
        SELECT r.id,r.slug,r.name,r.home,l.current_stage,hm.household_id
        FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
          AND l.current_stage IN ('baby','child','teen')
        JOIN household_members hm ON hm.resident_id=r.id AND hm.ended_season_id IS NULL
        ORDER BY r.id
        """
    ))
    for minor in minors:
        guardian = connection.execute(
            """
            SELECT adult.id,adult.name,home.household_id,adult.home
            FROM household_members home
            JOIN residents adult ON adult.id=home.resident_id
            JOIN resident_lifecycle life ON life.resident_id=adult.id AND life.alive=1
              AND life.current_stage IN ('adult','senior')
            WHERE home.household_id=? AND home.ended_season_id IS NULL
            ORDER BY home.legal_guardian DESC,home.financially_responsible DESC,adult.id LIMIT 1
            """,
            (minor["household_id"],),
        ).fetchone()
        if not guardian:
            guardian = connection.execute(
                """
                SELECT adult.id,adult.name,home.household_id,adult.home
                FROM family_links family
                JOIN residents adult ON adult.id=family.relative_resident_id
                JOIN resident_lifecycle life ON life.resident_id=adult.id AND life.alive=1
                  AND life.current_stage IN ('adult','senior')
                JOIN household_members home ON home.resident_id=adult.id AND home.ended_season_id IS NULL
                WHERE family.resident_id=? AND family.ended_season_id IS NULL
                ORDER BY CASE family.relation_type WHEN 'parent' THEN 0 WHEN 'guardian' THEN 1 ELSE 2 END,adult.id LIMIT 1
                """,
                (minor["id"],),
            ).fetchone()
        if not guardian:
            guardian = connection.execute(
                """
                SELECT adult.id,adult.name,home.household_id,adult.home
                FROM residents adult JOIN resident_lifecycle life ON life.resident_id=adult.id
                  AND life.alive=1 AND life.current_stage='adult'
                JOIN household_members home ON home.resident_id=adult.id AND home.ended_season_id IS NULL
                ORDER BY (
                  SELECT COUNT(*) FROM household_members dependents
                  JOIN resident_lifecycle dependent_life ON dependent_life.resident_id=dependents.resident_id
                    AND dependent_life.alive=1 AND dependent_life.current_stage IN ('baby','child','teen')
                  WHERE dependents.household_id=home.household_id AND dependents.ended_season_id IS NULL
                ),adult.id LIMIT 1
                """
            ).fetchone()
        if not guardian:
            continue
        old_household = int(minor["household_id"])
        new_household = int(guardian["household_id"])
        if old_household != new_household:
            connection.execute(
                """
                UPDATE household_members SET ended_season_id=?,ended_tick=?,end_reason='guardian reassignment'
                WHERE resident_id=? AND ended_season_id IS NULL
                """,
                (season_id, tick, minor["id"]),
            )
            connection.execute(
                """
                INSERT INTO household_members(
                  household_id,resident_id,role,legal_guardian,financially_responsible,
                  joined_season_id,joined_tick
                ) VALUES(?,?,'child',0,0,?,?)
                """,
                (new_household, minor["id"], season_id, tick),
            )
            connection.execute(
                "UPDATE residents SET home=? WHERE id=?",
                (guardian["home"], minor["id"]),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO family_links(
                  resident_id,relative_resident_id,relation_type,legal,started_season_id,started_tick
                ) VALUES(?,?,'guardian',1,?,?),(?,?,'dependent',1,?,?)
                """,
                (minor["id"], guardian["id"], season_id, tick, guardian["id"], minor["id"], season_id, tick),
            )
            _release_empty_household(connection, season_id, tick, old_household)
        active_care = connection.execute(
            "SELECT 1 FROM childcare_arrangements WHERE child_resident_id=? AND status='active' LIMIT 1",
            (minor["id"],),
        ).fetchone()
        if not active_care:
            if minor["current_stage"] == "baby":
                connection.execute(
                    """
                    INSERT INTO childcare_arrangements(
                      child_resident_id,arrangement_type,caregiver_resident_id,cost_per_day_cents,
                      status,started_season_id,started_tick
                    ) VALUES(?,'family',?,0,'active',?,?)
                    """,
                    (minor["id"], guardian["id"], season_id, tick),
                )
                connection.execute(
                    "UPDATE employment SET status='leave' WHERE resident_id=? AND status='active'",
                    (guardian["id"],),
                )
            else:
                provider = connection.execute(
                    "SELECT id FROM businesses WHERE name IN ('Canal Childcare','Krabville School') ORDER BY name='Canal Childcare' DESC LIMIT 1"
                ).fetchone()
                if provider:
                    connection.execute(
                        """
                        INSERT INTO childcare_arrangements(
                          child_resident_id,arrangement_type,provider_business_id,cost_per_day_cents,
                          status,started_season_id,started_tick
                        ) VALUES(?,'school',?,4500,'active',?,?)
                        """,
                        (minor["id"], provider[0], season_id, tick),
                    )
        repaired.append({"resident": minor["slug"], "guardian": int(guardian["id"])})
    return repaired


def grow_population(
    connection: sqlite3.Connection,
    season_id: int,
    tick: int,
    seed_hex: str,
    *,
    max_population: int = 32,
    max_adults: int = 24,
) -> dict[str, Any]:
    season_number = int(connection.execute(
        "SELECT number FROM seasons WHERE id=?", (season_id,)
    ).fetchone()[0])
    target = min(max_population, population_target_for_season(season_number))
    birth_seasons = {1, 4, 7, 10, 13, 16, 19}
    births = add_next_generation(
        connection, season_id, tick, seed_hex, max_population=max_population,
        max_adults=max_adults, target_population=target,
        max_births=int(season_number in birth_seasons),
    )
    arrivals = _add_newcomer_households(
        connection, season_id, tick, seed_hex, target, max_adults
    )
    guardians = _repair_guardians(connection, season_id, tick)
    for resident in connection.execute(
        """
        SELECT r.id FROM residents r JOIN resident_lifecycle l ON l.resident_id=r.id
        WHERE l.alive=1 AND l.current_stage='adult' AND NOT EXISTS (
          SELECT 1 FROM employment e WHERE e.resident_id=r.id
            AND e.status IN ('active','leave','suspended')
        ) ORDER BY r.id
        """
    ):
        _hire_resident(connection, int(resident["id"]), season_id, tick)
    living = int(connection.execute(
        "SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1"
    ).fetchone()[0])
    return {
        "target": target, "living": living, "births": births,
        "arrivals": arrivals, "guardianRepairs": guardians,
    }


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


def _daily_personal_expenses(
    season_id: int, day: int, resident_id: int, needs_json: str | None, employed: bool
) -> dict[str, int]:
    """Build deterministic daily spending from a resident's actual unmet needs."""

    needs = loads(needs_json or "{}", {})
    chooser = _rng(str(season_id), "daily-spend", day, resident_id)

    def satisfaction(key: str, default: int = 70) -> int:
        try:
            return max(0, min(100, int(needs.get(key, default))))
        except (TypeError, ValueError):
            return default

    expenses = {
        "food": chooser.randint(1_150, 1_750) + max(0, 70 - satisfaction("hunger")) * 16,
        "housing": chooser.randint(2_150, 3_050),
        "utilities": chooser.randint(380, 780),
        "transport": chooser.randint(400, 850) if employed else chooser.randint(80, 300),
        "essentials": chooser.randint(250, 700),
        "communications": chooser.randint(160, 460),
    }
    if satisfaction("fun") < 72 or chooser.random() < 0.34:
        expenses["entertainment"] = chooser.randint(550, 2_200)
    if satisfaction("hunger") < 62 or satisfaction("social") < 58 or chooser.random() < 0.28:
        expenses["dining"] = chooser.randint(450, 1_650)
    if satisfaction("health") < 74:
        expenses["healthcare"] = chooser.randint(650, 2_600) + (74 - satisfaction("health")) * 25
    if min(satisfaction("comfort"), satisfaction("safety")) < 58 or chooser.random() < 0.12:
        expenses["repairs"] = chooser.randint(650, 3_200)
    if satisfaction("purpose") < 68 or chooser.random() < 0.22:
        expenses["education"] = chooser.randint(300, 1_450)
    if min(satisfaction("social"), satisfaction("belonging")) < 62:
        expenses["community"] = chooser.randint(250, 1_100)
    return expenses


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
    business_records = list(connection.execute(
        """
        SELECT b.name,b.industry,a.id account_id FROM businesses b JOIN financial_accounts a
          ON a.business_id=b.id AND a.name='Operating' AND a.status='open'
        WHERE b.status IN ('active','struggling')
        """
    ))
    business_accounts = {str(row["name"]): int(row["account_id"]) for row in business_records}
    expense_recipients = {
        "food": "Lagoon General Store",
        "housing": "Krabville Credit Union",
        "utilities": "Community House",
        "transport": "Lagoon Ferry",
        "essentials": "Lagoon General Store",
        "childcare": "Krabville School",
        "communications": "Signal House",
        "entertainment": "Dockside Studio",
        "dining": "Blue Kettle Cafe",
        "healthcare": "Lagoon Health Centre",
        "repairs": "Harbour Works",
        "education": "Harbour Library",
        "community": "Community House",
    }
    recipient_terms = {
        "food": ("grocery", "provisions", "food"),
        "essentials": ("shop", "provisions", "general"),
        "communications": ("radio", "signal", "communications"),
        "entertainment": ("studio", "creative", "recreation"),
        "dining": ("cafe", "food"),
        "healthcare": ("health", "medical", "care"),
        "repairs": ("repair", "hardware", "works"),
        "education": ("school", "library", "education"),
        "community": ("community", "care", "civic"),
        "childcare": ("school", "care", "child"),
    }
    expense_accounts: dict[str, list[int]] = {}
    for category, default_name in expense_recipients.items():
        candidates = [business_accounts[default_name]] if default_name in business_accounts else []
        for business in business_records:
            description = f"{business['name']} {business['industry']}".casefold()
            if any(term in description for term in recipient_terms.get(category, ())):
                candidates.append(int(business["account_id"]))
        expense_accounts[category] = list(dict.fromkeys(candidates))
    totals = {
        "transactions": 0,
        "wages": 0,
        "expenses": 0,
        "childcare": 0,
        "debt": 0,
        "investments": 0,
        "businessIncome": 0,
        "businessPayroll": 0,
        "servicePurchases": 0,
    }
    for row in connection.execute(
        """
        SELECT r.id,r.name,a.id account_id,e.wage_cents,e.scheduled_minutes_per_day,e.status,
          employer.id employer_account_id,s.needs_json
        FROM residents r JOIN financial_accounts a ON a.resident_id=r.id AND a.name='Personal chequing'
        LEFT JOIN resident_state s ON s.resident_id=r.id AND s.season_id=?
        LEFT JOIN employment e ON e.resident_id=r.id AND e.status IN ('active','leave')
        LEFT JOIN jobs j ON j.id=e.job_id
        LEFT JOIN financial_accounts employer ON employer.business_id=j.business_id
          AND employer.name='Operating' AND employer.status='open'
        JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
          AND l.current_stage IN ('teen','adult','senior')
        ORDER BY r.id
        """,
        (season_id,),
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
        expenses = _daily_personal_expenses(
            season_id, day, int(row["id"]), row["needs_json"], row["status"] == "active"
        )
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
            "expenses": expenses,
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
        flows: dict[int, int] = {}
        flow_memos: dict[int, list[str]] = {}

        def add_flow(account_id: int, amount: int, memo: str) -> None:
            if amount:
                flows[account_id] = flows.get(account_id, 0) + amount
                flow_memos.setdefault(account_id, []).append(memo)

        add_flow(int(row["account_id"]), liquid_delta, "resident daily net")
        if investment:
            add_flow(int(investment["account_id"]), investment_delta, "investment valuation")
        if debt_account_id:
            add_flow(debt_account_id, -debt_delta, "debt balance change")
        wages = int(result["totals"]["wages_cents"])
        if wages and row["employer_account_id"]:
            add_flow(int(row["employer_account_id"]), -wages, "payroll:wages")
            totals["businessPayroll"] += wages
        for settled in result["ledger"]:
            category = str(settled["category"])
            candidates = expense_accounts.get(category, [])
            if not candidates:
                continue
            business_account = candidates[
                _rng(str(season_id), "expense-recipient", day, row["id"], category).randrange(len(candidates))
            ]
            receipt = sum(
                int(entry["amount_cents"])
                for entry in settled["entries"]
                if str(entry["account"]).startswith("expense:") and int(entry["amount_cents"]) > 0
            )
            add_flow(business_account, receipt, f"service:{category}")
            totals["businessIncome"] += receipt
            if category not in {"food", "housing", "utilities", "transport", "essentials", "childcare"}:
                totals["servicePurchases"] += 1
        add_flow(clearing_id, -sum(flows.values()), "balanced settlement clearing")
        entries = [
            (account_id, amount, "; ".join(dict.fromkeys(flow_memos.get(account_id, ["daily settlement flow"]))))
            for account_id, amount in flows.items()
            if amount
        ]
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
