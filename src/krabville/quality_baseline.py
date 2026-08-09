from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Sequence

from . import __version__
from .config import Settings
from .db import initialize, required_schema_version
from .population_v2 import MAX_ADULTS, MAX_LIVING
from .runtime_v2 import account_balance
from .world import TARGET_TICKS, TICKS_PER_DAY, advance_tick, start_season


REPORT_SCHEMA_VERSION = 1
MINUTES_PER_TICK = 5
CRITICAL_NEED_THRESHOLD = 20
DEFAULT_SEEDS = tuple(
    hashlib.sha256(f"kvsim-2.3-quality-seed-{number}".encode()).hexdigest()
    for number in range(1, 4)
)
RELATIONSHIP_FIELDS = (
    "affinity",
    "trust",
    "tension",
    "familiarity",
    "attraction",
    "affection",
    "respect",
    "commitment",
    "resentment",
    "interactions",
)


def _sorted_counts(values: Counter[str]) -> dict[str, int]:
    return {key: int(values[key]) for key in sorted(values)}


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def _settings(root: Path) -> Settings:
    return Settings(
        data_dir=root,
        database_path=root / "krabville.sqlite3",
        asset_dir=root / "assets",
        report_dir=root / "reports",
        frontend_dir=root / "frontend",
        control_socket=root / "control.sock",
        bind_host="127.0.0.1",
        port=18890,
        tick_seconds=0.01,
        fake_provider=True,
        primary_model="disabled",
        primary_reasoning="low",
        fallback_model="disabled",
        fallback_reasoning="low",
        call_limit=150,
        token_guard=1_500_000,
        inference_timeout=10,
        voter_secret="deterministic-quality-baseline",
        public_origin="http://127.0.0.1",
        auto_continue=False,
    )


def _stage_counts(connection: sqlite3.Connection) -> dict[str, int]:
    return _sorted_counts(
        Counter(
            {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    """
                    SELECT current_stage,COUNT(*) FROM resident_lifecycle
                    WHERE alive=1 GROUP BY current_stage
                    """
                )
            }
        )
    )


def _relationship_snapshot(
    connection: sqlite3.Connection, season_id: int
) -> dict[tuple[int, int], dict[str, int]]:
    columns = ",".join(RELATIONSHIP_FIELDS)
    return {
        (int(row["resident_a"]), int(row["resident_b"])): {
            field: int(row[field]) for field in RELATIONSHIP_FIELDS
        }
        for row in connection.execute(
            f"SELECT resident_a,resident_b,{columns} FROM relationships "
            "WHERE season_id=? ORDER BY resident_a,resident_b",
            (season_id,),
        )
    }


def _financial_totals(connection: sqlite3.Connection) -> dict[str, Any]:
    by_owner: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    for row in connection.execute(
        """
        SELECT id,account_type,
          CASE WHEN resident_id IS NOT NULL THEN 'resident'
               WHEN household_id IS NOT NULL THEN 'household'
               ELSE 'business' END owner_kind
        FROM financial_accounts WHERE status<>'closed' ORDER BY id
        """
    ):
        balance = account_balance(connection, int(row["id"]))
        by_owner[str(row["owner_kind"])] += balance
        by_type[str(row["account_type"])] += balance
    debt = int(
        connection.execute(
            "SELECT COALESCE(SUM(outstanding_cents),0) FROM debts WHERE status<>'paid'"
        ).fetchone()[0]
    )
    investments = int(
        connection.execute(
            "SELECT COALESCE(SUM(market_value_cents),0) FROM investments"
        ).fetchone()[0]
    )
    return {
        "accountBalancesCents": _sorted_counts(by_type),
        "ownerBalancesCents": _sorted_counts(by_owner),
        "debtCents": debt,
        "investmentValueCents": investments,
    }


def _observer(connection: sqlite3.Connection) -> dict[str, Any]:
    living, adults = connection.execute(
        """
        SELECT COUNT(*),COALESCE(SUM(current_stage IN ('adult','senior')),0)
        FROM resident_lifecycle WHERE alive=1
        """
    ).fetchone()
    return {
        "critical_need_ticks": Counter(),
        "dependent_ticks": 0,
        "uncovered_dependent_ticks": 0,
        "minimum_coverage_minutes": 1440,
        "population_min": int(living),
        "population_max": int(living),
        "adult_min": int(adults),
        "adult_max": int(adults),
    }


def _observe_tick(
    connection: sqlite3.Connection, season_id: int, observed: dict[str, Any]
) -> None:
    for row in connection.execute(
        """
        SELECT need_key,satisfaction FROM resident_needs
        WHERE season_id=? AND satisfaction<=?
        """,
        (season_id, CRITICAL_NEED_THRESHOLD),
    ):
        observed["critical_need_ticks"][str(row["need_key"])] += 1

    dependents = list(
        connection.execute(
            """
            SELECT care_state,caregiver_coverage_minutes
            FROM resident_season_state
            WHERE season_id=? AND life_stage IN ('baby','child')
            """,
            (season_id,),
        )
    )
    observed["dependent_ticks"] += len(dependents)
    for row in dependents:
        coverage = int(row["caregiver_coverage_minutes"])
        observed["minimum_coverage_minutes"] = min(
            observed["minimum_coverage_minutes"], coverage
        )
        if str(row["care_state"]) == "uncovered":
            observed["uncovered_dependent_ticks"] += 1

    living, adults = connection.execute(
        """
        SELECT COUNT(*),COALESCE(SUM(current_stage IN ('adult','senior')),0)
        FROM resident_lifecycle WHERE alive=1
        """
    ).fetchone()
    observed["population_min"] = min(observed["population_min"], int(living))
    observed["population_max"] = max(observed["population_max"], int(living))
    observed["adult_min"] = min(observed["adult_min"], int(adults))
    observed["adult_max"] = max(observed["adult_max"], int(adults))


def _longest_streak(actions: list[str]) -> tuple[int, int]:
    longest = 0
    repeated = 0
    previous = ""
    length = 0
    for action in actions:
        if action == previous:
            length += 1
        else:
            if length >= 3:
                repeated += 1
            previous = action
            length = 1
        longest = max(longest, length)
    if length >= 3:
        repeated += 1
    return longest, repeated


def _behaviour(
    connection: sqlite3.Connection, season_id: int, observed: dict[str, Any]
) -> dict[str, Any]:
    decisions = list(
        connection.execute(
            """
            SELECT decision.id,decision.tick,decision.phase,decision.chosen_action,
                   decision.interruption_reason,resident.slug,state.life_stage
            FROM decision_history decision
            JOIN residents resident ON resident.id=decision.resident_id
            JOIN resident_season_state state
              ON state.season_id=decision.season_id
             AND state.resident_id=decision.resident_id
            WHERE decision.season_id=? AND decision.chosen_action IS NOT NULL
            ORDER BY resident.slug,decision.tick,decision.id
            """,
            (season_id,),
        )
    )
    actions: Counter[str] = Counter()
    by_resident: dict[str, Counter[str]] = defaultdict(Counter)
    by_stage: dict[str, Counter[str]] = defaultdict(Counter)
    by_hour: dict[str, Counter[str]] = defaultdict(Counter)
    sequences: dict[str, list[str]] = defaultdict(list)
    blocked = 0
    for row in decisions:
        action = str(row["chosen_action"])
        slug = str(row["slug"])
        actions[action] += 1
        by_resident[slug][action] += 1
        by_stage[str(row["life_stage"])][action] += 1
        by_hour[f"{(int(row['tick']) % TICKS_PER_DAY) // 12:02d}"][action] += 1
        sequences[slug].append(action)
        if row["phase"] in {"interrupted", "abandoned"}:
            blocked += 1

    streaks = {slug: _longest_streak(sequence) for slug, sequence in sequences.items()}
    option_rows = list(
        connection.execute(
            """
            SELECT decision.id,COUNT(option.option_rank) option_count,
                   COUNT(DISTINCT option.action) distinct_actions
            FROM decision_history decision
            JOIN decision_options option ON option.decision_id=decision.id
            WHERE decision.season_id=? GROUP BY decision.id ORDER BY decision.id
            """,
            (season_id,),
        )
    )
    critical = {
        key: int(count) * MINUTES_PER_TICK
        for key, count in sorted(observed["critical_need_ticks"].items())
    }
    goal_status = Counter(
        f"{row['scope']}:{row['status']}"
        for row in connection.execute(
            "SELECT scope,status FROM goals WHERE season_id=?", (season_id,)
        )
    )
    life_goal_status = Counter(
        str(row[0])
        for row in connection.execute(
            """
            SELECT status FROM life_goals
            WHERE created_season_id<=? AND (completed_season_id IS NULL OR completed_season_id>=?)
            """,
            (season_id, season_id),
        )
    )
    return {
        "decisionCount": len(decisions),
        "uniqueActions": len(actions),
        "actionDistribution": _sorted_counts(actions),
        "actionsByResident": {
            key: _sorted_counts(value) for key, value in sorted(by_resident.items())
        },
        "actionsByLifeStage": {
            key: _sorted_counts(value) for key, value in sorted(by_stage.items())
        },
        "actionsByHour": {
            key: _sorted_counts(value) for key, value in sorted(by_hour.items())
        },
        "longestRepeatedActionStreak": max(
            (value[0] for value in streaks.values()), default=0
        ),
        "longestStreakByResident": {
            key: value[0] for key, value in sorted(streaks.items())
        },
        "repeatedStreaksAtLeastThree": sum(value[1] for value in streaks.values()),
        "residentsWithStreakAtLeastThree": sum(
            value[0] >= 3 for value in streaks.values()
        ),
        "meanOptionsPerDecision": round(
            sum(int(row["option_count"]) for row in option_rows) / len(option_rows), 6
        )
        if option_rows
        else 0.0,
        "meanDistinctAlternativesPerDecision": round(
            sum(int(row["distinct_actions"]) for row in option_rows) / len(option_rows),
            6,
        )
        if option_rows
        else 0.0,
        "blockedOrInterruptedDecisions": blocked,
        "missedCommitments": int(
            connection.execute(
                "SELECT COUNT(*) FROM communication_commitments WHERE status='missed'"
            ).fetchone()[0]
        ),
        "criticalNeedResidentMinutes": sum(critical.values()),
        "criticalNeedMinutesByNeed": critical,
        "goalStatus": _sorted_counts(goal_status),
        "lifeGoalStatus": _sorted_counts(life_goal_status),
    }


def _social(
    connection: sqlite3.Connection,
    season_id: int,
    initial: dict[tuple[int, int], dict[str, int]],
) -> dict[str, Any]:
    names = {
        int(row["id"]): str(row["slug"])
        for row in connection.execute(
            """
            SELECT resident.id,resident.slug
            FROM resident_season_state state
            JOIN residents resident ON resident.id=state.resident_id
            WHERE state.season_id=? ORDER BY resident.id
            """,
            (season_id,),
        )
    }
    final = _relationship_snapshot(connection, season_id)
    dimensions = [field for field in RELATIONSHIP_FIELDS if field != "interactions"]
    absolute_deltas: Counter[str] = Counter()
    moved_pairs = 0
    interaction_by_resident: Counter[str] = Counter()
    interaction_by_pair: dict[str, int] = {}
    for pair, current in final.items():
        before = initial.get(pair, {field: 0 for field in RELATIONSHIP_FIELDS})
        if any(current[field] != before[field] for field in dimensions):
            moved_pairs += 1
        for field in dimensions:
            absolute_deltas[field] += abs(current[field] - before[field])
        interactions = max(0, current["interactions"] - before["interactions"])
        pair_name = f"{names[pair[0]]}|{names[pair[1]]}"
        interaction_by_pair[pair_name] = interactions
        interaction_by_resident[names[pair[0]]] += interactions
        interaction_by_resident[names[pair[1]]] += interactions

    total_pair_interactions = sum(interaction_by_pair.values())
    resident_slugs = sorted(names.values())
    conversations = list(
        connection.execute(
            "SELECT resident_a,resident_b,summary FROM conversations WHERE season_id=? ORDER BY id",
            (season_id,),
        )
    )
    summaries = Counter(str(row["summary"]) for row in conversations)
    return {
        "residentCount": len(resident_slugs),
        "relationshipPairs": len(final),
        "movedPairs": moved_pairs,
        "movedPairShare": _ratio(moved_pairs, len(final)),
        "meanAbsoluteDeltaByDimension": {
            field: round(absolute_deltas[field] / len(final), 6) if final else 0.0
            for field in dimensions
        },
        "totalInteractionDelta": total_pair_interactions,
        "interactionsByResident": {
            slug: int(interaction_by_resident[slug]) for slug in resident_slugs
        },
        "isolatedResidents": [
            slug for slug in resident_slugs if interaction_by_resident[slug] == 0
        ],
        "dominantPairInteractionShare": _ratio(
            max(interaction_by_pair.values(), default=0), total_pair_interactions
        ),
        "conversationCount": len(conversations),
        "conversationPairCount": len(
            {
                tuple(sorted((int(row["resident_a"]), int(row["resident_b"]))))
                for row in conversations
            }
        ),
        "repeatedConversationSummaries": sum(
            count - 1 for count in summaries.values() if count > 1
        ),
    }


def _economy(
    connection: sqlite3.Connection,
    season_id: int,
    initial: dict[str, Any],
) -> dict[str, Any]:
    transaction_rows = list(
        connection.execute(
            """
            SELECT transaction_record.id,transaction_record.category,
                   COUNT(entry.id) entry_count,COALESCE(SUM(entry.amount_cents),0) balance,
                   COALESCE(SUM(CASE WHEN entry.amount_cents>0 THEN entry.amount_cents ELSE 0 END),0) credits,
                   COALESCE(SUM(CASE WHEN entry.amount_cents<0 THEN -entry.amount_cents ELSE 0 END),0) debits
            FROM financial_transactions transaction_record
            LEFT JOIN transaction_entries entry ON entry.transaction_id=transaction_record.id
            WHERE transaction_record.season_id=? AND transaction_record.status='posted'
            GROUP BY transaction_record.id ORDER BY transaction_record.id
            """,
            (season_id,),
        )
    )
    category_counts = Counter(
        str(row[0])
        for row in connection.execute(
            """
            SELECT category FROM financial_transactions
            WHERE season_id=? AND status='posted'
            """,
            (season_id,),
        )
    )
    movement_units = Counter()
    for row in connection.execute(
        """
        SELECT movement_type,COALESCE(SUM(quantity),0) units
        FROM inventory_movements WHERE season_id=? GROUP BY movement_type
        """,
        (season_id,),
    ):
        movement_units[str(row["movement_type"])] = round(float(row["units"]), 3)
    active_products = int(
        connection.execute(
            "SELECT COUNT(*) FROM item_catalog WHERE active=1"
        ).fetchone()[0]
    )
    purchased_products = int(
        connection.execute(
            """
            SELECT COUNT(DISTINCT item_id) FROM inventory_movements
            WHERE season_id=? AND movement_type='purchase'
            """,
            (season_id,),
        ).fetchone()[0]
    )
    ending = _financial_totals(connection)
    owner_delta = {
        owner: int(ending["ownerBalancesCents"].get(owner, 0))
        - int(initial["ownerBalancesCents"].get(owner, 0))
        for owner in sorted(
            set(initial["ownerBalancesCents"]) | set(ending["ownerBalancesCents"])
        )
    }
    return {
        "postedTransactions": len(transaction_rows),
        "ledgerEntries": sum(int(row["entry_count"]) for row in transaction_rows),
        "totalDebitsCents": sum(int(row["debits"]) for row in transaction_rows),
        "totalCreditsCents": sum(int(row["credits"]) for row in transaction_rows),
        "aggregateEntryBalanceCents": sum(
            int(row["balance"]) for row in transaction_rows
        ),
        "unbalancedTransactions": sum(
            int(row["entry_count"]) < 2 or int(row["balance"]) != 0
            for row in transaction_rows
        ),
        "transactionsByCategory": _sorted_counts(category_counts),
        "initialFinancialTotals": initial,
        "finalFinancialTotals": ending,
        "ownerBalanceDeltaCents": owner_delta,
        "activeProducts": active_products,
        "purchasedProducts": purchased_products,
        "productTurnoverShare": _ratio(purchased_products, active_products),
        "purchasedProductCategories": int(
            connection.execute(
                """
                SELECT COUNT(DISTINCT item.category)
                FROM inventory_movements movement
                JOIN item_catalog item ON item.id=movement.item_id
                WHERE movement.season_id=? AND movement.movement_type='purchase'
                """,
                (season_id,),
            ).fetchone()[0]
        ),
        "inventoryUnitsByMovement": {
            key: movement_units[key] for key in sorted(movement_units)
        },
        "productsWithPriceMovement": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM (
                  SELECT item_id FROM price_history WHERE season_id=?
                  GROUP BY item_id HAVING MIN(average_price_cents)<>MAX(average_price_cents)
                )
                """,
                (season_id,),
            ).fetchone()[0]
        ),
        "endingStockouts": int(
            connection.execute(
                "SELECT COUNT(*) FROM business_inventory WHERE quantity<=0"
            ).fetchone()[0]
        ),
        "businessStatus": _sorted_counts(
            Counter(
                str(row[0])
                for row in connection.execute("SELECT status FROM businesses")
            )
        ),
    }


def _scheduled_minutes(intervals: list[tuple[int, int]]) -> int:
    total = 0
    end = 0
    for start, stop in sorted(intervals):
        if stop <= end:
            continue
        total += stop - max(start, end)
        end = stop
    return total


def _care(
    connection: sqlite3.Connection, season_id: int, observed: dict[str, Any]
) -> dict[str, Any]:
    dependents = [
        int(row[0])
        for row in connection.execute(
            """
            SELECT resident_id FROM resident_season_state
            WHERE season_id=? AND life_stage IN ('baby','child') ORDER BY resident_id
            """,
            (season_id,),
        )
    ]
    scheduled: dict[str, int] = {}
    for resident_id in dependents:
        for day in range(7):
            intervals = [
                (int(row[0]), int(row[1]))
                for row in connection.execute(
                    """
                    SELECT schedule.start_minute,schedule.end_minute
                    FROM childcare_arrangements arrangement
                    JOIN childcare_schedule schedule ON schedule.arrangement_id=arrangement.id
                    WHERE arrangement.child_resident_id=?
                      AND COALESCE(arrangement.started_season_id,?)<=?
                      AND (arrangement.ended_season_id IS NULL OR arrangement.ended_season_id>=?)
                      AND schedule.day_of_week=?
                    """,
                    (resident_id, season_id, season_id, season_id, day),
                )
            ]
            scheduled[f"{resident_id}:{day}"] = _scheduled_minutes(intervals)
    state_counts = Counter(
        str(row[0])
        for row in connection.execute(
            """
            SELECT care_state FROM resident_season_state
            WHERE season_id=? AND life_stage IN ('baby','child')
            """,
            (season_id,),
        )
    )
    health_status = Counter(
        str(row[0])
        for row in connection.execute("SELECT status FROM health_conditions")
    )
    dependent_ticks = int(observed["dependent_ticks"])
    uncovered_ticks = int(observed["uncovered_dependent_ticks"])
    return {
        "dependents": len(dependents),
        "careState": _sorted_counts(state_counts),
        "observedDependentResidentTicks": dependent_ticks,
        "uncoveredDependentResidentTicks": uncovered_ticks,
        "observedCoverageShare": _ratio(
            dependent_ticks - uncovered_ticks, dependent_ticks
        ),
        "minimumAuthoritativeCoverageMinutes": int(
            observed["minimum_coverage_minutes"]
        ),
        "minimumScheduledCoverageMinutesPerDay": min(scheduled.values(), default=0),
        "dependentsWithoutActiveArrangement": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM resident_season_state state
                WHERE state.season_id=? AND state.life_stage IN ('baby','child')
                  AND NOT EXISTS (
                    SELECT 1 FROM childcare_arrangements arrangement
                    WHERE arrangement.child_resident_id=state.resident_id
                      AND COALESCE(arrangement.started_season_id,?)<=?
                      AND (arrangement.ended_season_id IS NULL OR arrangement.ended_season_id>=?)
                  )
                """,
                (season_id, season_id, season_id, season_id),
            ).fetchone()[0]
        ),
        "dependentsWithoutLegalGuardian": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM resident_season_state child
                WHERE child.season_id=? AND child.life_stage IN ('baby','child')
                  AND NOT EXISTS (
                    SELECT 1 FROM household_members child_home
                    JOIN household_members guardian
                      ON guardian.household_id=child_home.household_id
                     AND guardian.legal_guardian=1
                    JOIN resident_season_state guardian_state
                      ON guardian_state.resident_id=guardian.resident_id
                     AND guardian_state.season_id=child.season_id
                    WHERE child_home.resident_id=child.resident_id
                      AND COALESCE(child_home.joined_season_id,child.season_id)<=child.season_id
                      AND (child_home.ended_season_id IS NULL OR child_home.ended_season_id>=child.season_id)
                      AND COALESCE(guardian.joined_season_id,child.season_id)<=child.season_id
                      AND (guardian.ended_season_id IS NULL OR guardian.ended_season_id>=child.season_id)
                      AND guardian.resident_id<>child.resident_id
                  )
                """,
                (season_id,),
            ).fetchone()[0]
        ),
        "maximumResidentCaregiverLoad": int(
            connection.execute(
                """
                SELECT COALESCE(MAX(dependents),0) FROM (
                  SELECT caregiver_resident_id,COUNT(DISTINCT child_resident_id) dependents
                  FROM childcare_arrangements arrangement
                  WHERE caregiver_resident_id IS NOT NULL
                    AND COALESCE(arrangement.started_season_id,?)<=?
                    AND (arrangement.ended_season_id IS NULL OR arrangement.ended_season_id>=?)
                    AND arrangement.child_resident_id IN (
                      SELECT resident_id FROM resident_season_state
                      WHERE season_id=? AND life_stage IN ('baby','child')
                    )
                  GROUP BY caregiver_resident_id
                )
                """,
                (season_id, season_id, season_id, season_id),
            ).fetchone()[0]
        ),
        "failedCareCommitments": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM communication_commitments
                WHERE commitment_type='care' AND status IN ('missed','cancelled')
                """
            ).fetchone()[0]
        ),
        "healthConditionsByStatus": _sorted_counts(health_status),
        "untreatedActiveConditions": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM health_conditions
                WHERE status IN ('active','recovering') AND provider_business_id IS NULL
                """
            ).fetchone()[0]
        ),
    }


def _event_concentration(
    connection: sqlite3.Connection, season_id: int
) -> dict[str, Any]:
    town_categories = Counter(
        str(row[0])
        for row in connection.execute(
            "SELECT category FROM town_events WHERE season_id=?", (season_id,)
        )
    )
    town_slugs = [
        str(row[0])
        for row in connection.execute(
            "SELECT slug FROM town_events WHERE season_id=? ORDER BY tick,id",
            (season_id,),
        )
    ]
    life_types = Counter(
        str(row[0])
        for row in connection.execute(
            "SELECT event_type FROM life_events WHERE season_id=?", (season_id,)
        )
    )

    def concentration(counts: Counter[str]) -> dict[str, Any]:
        total = sum(counts.values())
        return {
            "counts": _sorted_counts(counts),
            "unique": len(counts),
            "dominantShare": _ratio(max(counts.values(), default=0), total),
            "herfindahlIndex": round(
                sum((count / total) ** 2 for count in counts.values()), 6
            )
            if total
            else 0.0,
        }

    longest, _ = _longest_streak(town_slugs)
    return {
        "townEvents": len(town_slugs),
        "townEventCategories": concentration(town_categories),
        "uniqueTownEventSlugs": len(set(town_slugs)),
        "longestRepeatedTownEventStreak": longest,
        "lifeEvents": sum(life_types.values()),
        "lifeEventTypes": concentration(life_types),
    }


def _lifecycle(
    connection: sqlite3.Connection,
    season_id: int,
    initial_stages: dict[str, int],
    observed: dict[str, Any],
    status: str,
    tick: int,
) -> dict[str, Any]:
    return {
        "seasonStatus": status,
        "tickReached": tick,
        "initialLiving": sum(initial_stages.values()),
        "finalLiving": int(
            connection.execute(
                "SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1"
            ).fetchone()[0]
        ),
        "initialLifeStages": initial_stages,
        "finalLifeStages": _stage_counts(connection),
        "minimumLiving": int(observed["population_min"]),
        "maximumLiving": int(observed["population_max"]),
        "minimumAdults": int(observed["adult_min"]),
        "maximumAdults": int(observed["adult_max"]),
        "births": int(
            connection.execute(
                "SELECT COUNT(*) FROM life_events WHERE season_id=? AND event_type='birth'",
                (season_id,),
            ).fetchone()[0]
        ),
        "deaths": int(
            connection.execute(
                "SELECT COUNT(*) FROM life_events WHERE season_id=? AND event_type='death'",
                (season_id,),
            ).fetchone()[0]
        ),
        "duplicateBirthEvents": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM (
                  SELECT subject_resident_id FROM life_events
                  WHERE season_id=? AND event_type='birth' AND subject_resident_id IS NOT NULL
                  GROUP BY subject_resident_id HAVING COUNT(*)>1
                )
                """,
                (season_id,),
            ).fetchone()[0]
        ),
        "livingWithoutHousehold": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM resident_lifecycle lifecycle
                WHERE lifecycle.alive=1 AND NOT EXISTS (
                  SELECT 1 FROM household_members member
                  WHERE member.resident_id=lifecycle.resident_id
                    AND member.ended_season_id IS NULL
                )
                """
            ).fetchone()[0]
        ),
        "livingWithoutOccupiedHome": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM resident_lifecycle lifecycle
                WHERE lifecycle.alive=1 AND NOT EXISTS (
                  SELECT 1 FROM household_members member
                  JOIN property_occupancy occupancy
                    ON occupancy.household_id=member.household_id
                   AND occupancy.ended_season_id IS NULL
                  WHERE member.resident_id=lifecycle.resident_id
                    AND member.ended_season_id IS NULL
                )
                """
            ).fetchone()[0]
        ),
        "propertyCapacityOverflows": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM (
                  SELECT occupancy.property_id,property.resident_capacity,
                         COUNT(DISTINCT member.resident_id) occupants
                  FROM property_occupancy occupancy
                  JOIN properties property ON property.id=occupancy.property_id
                  JOIN household_members member
                    ON member.household_id=occupancy.household_id
                   AND member.ended_season_id IS NULL
                  JOIN resident_lifecycle lifecycle
                    ON lifecycle.resident_id=member.resident_id AND lifecycle.alive=1
                  WHERE occupancy.ended_season_id IS NULL
                  GROUP BY occupancy.property_id
                  HAVING property.resident_capacity>0
                     AND COUNT(DISTINCT member.resident_id)>property.resident_capacity
                )
                """
            ).fetchone()[0]
        ),
        "postDeathActivities": int(
            connection.execute(
                """
                SELECT COUNT(*) FROM activities activity
                JOIN resident_lifecycle lifecycle
                  ON lifecycle.resident_id=activity.resident_id
                WHERE lifecycle.death_season_id=? AND lifecycle.death_tick IS NOT NULL
                  AND activity.season_id=? AND activity.tick>lifecycle.death_tick
                """,
                (season_id, season_id),
            ).fetchone()[0]
        ),
        "populationCapExceeded": int(observed["population_max"]) > MAX_LIVING,
        "adultCapExceeded": int(observed["adult_max"]) > MAX_ADULTS,
    }


def _narrative_evidence(
    connection: sqlite3.Connection, season_id: int
) -> dict[str, Any]:
    claims, linked = connection.execute(
        """
        SELECT COUNT(*),COALESCE(SUM(
          life_event_id IS NOT NULL OR town_event_id IS NOT NULL OR
          decision_id IS NOT NULL OR transaction_id IS NOT NULL OR fact_id IS NOT NULL
        ),0) FROM story_ledger WHERE season_id=?
        """,
        (season_id,),
    ).fetchone()
    decisions, explained = connection.execute(
        """
        SELECT COUNT(DISTINCT decision.id),COUNT(DISTINCT factor.decision_id)
        FROM decision_history decision
        LEFT JOIN decision_factors factor ON factor.decision_id=decision.id
        WHERE decision.season_id=?
        """,
        (season_id,),
    ).fetchone()
    chronicles, verified = connection.execute(
        """
        SELECT COUNT(*),COALESCE(SUM(verified=1 AND ledger_ids_json<>'[]'),0)
        FROM daily_chronicles WHERE season_id=?
        """,
        (season_id,),
    ).fetchone()
    return {
        "storyClaims": int(claims),
        "storyClaimsWithLedgerReference": int(linked),
        "storyClaimEvidenceShare": _ratio(linked, claims),
        "decisions": int(decisions),
        "decisionsWithFactors": int(explained),
        "decisionFactorCoverageShare": _ratio(explained, decisions),
        "chronicles": int(chronicles),
        "verifiedChroniclesWithSources": int(verified),
        "modelAttempts": int(
            connection.execute(
                "SELECT COUNT(*) FROM model_usage WHERE season_id=?", (season_id,)
            ).fetchone()[0]
        ),
    }


def _stable_digest(connection: sqlite3.Connection, season_id: int) -> str:
    queries = {
        "season": """
            SELECT number,status,current_tick,current_day,world_minutes,model_locked,
                   model_degraded,seed_revealed,completion_reason,weather_json
            FROM seasons WHERE id=?
        """,
        "population": """
            SELECT resident.slug,lifecycle.current_stage,lifecycle.seasons_in_stage,
                   lifecycle.alive,lifecycle.birth_season_id,lifecycle.birth_tick,
                   lifecycle.death_season_id,lifecycle.death_tick,lifecycle.death_cause
            FROM residents resident
            JOIN resident_lifecycle lifecycle ON lifecycle.resident_id=resident.id
            ORDER BY resident.slug
        """,
        "state": """
            SELECT resident.slug,state.location,state.activity,state.public_thought,
                   state.intention,state.reflection,state.mood,state.needs_json,state.path_json,
                   state.action_until_tick,state.updated_tick
            FROM resident_state state JOIN residents resident ON resident.id=state.resident_id
            WHERE state.season_id=? ORDER BY resident.slug
        """,
        "decisions": """
            SELECT resident.slug,decision.tick,decision.phase,decision.chosen_action,
                   decision.chosen_destination,decision.utility_score,decision.committed_tick,
                   decision.resolved_tick,decision.interruption_reason
            FROM decision_history decision
            JOIN residents resident ON resident.id=decision.resident_id
            WHERE decision.season_id=? ORDER BY decision.tick,resident.slug,decision.id
        """,
        "options": """
            SELECT resident.slug,decision.tick,option.option_rank,option.action,
                   option.destination,option.utility_score,option.selected
            FROM decision_options option
            JOIN decision_history decision ON decision.id=option.decision_id
            JOIN residents resident ON resident.id=decision.resident_id
            WHERE decision.season_id=?
            ORDER BY decision.tick,resident.slug,option.option_rank
        """,
        "relationships": """
            SELECT a.slug,b.slug,relationship.affinity,relationship.trust,
                   relationship.tension,relationship.familiarity,relationship.attraction,
                   relationship.affection,relationship.respect,relationship.commitment,
                   relationship.resentment,relationship.interactions
            FROM relationships relationship
            JOIN residents a ON a.id=relationship.resident_a
            JOIN residents b ON b.id=relationship.resident_b
            WHERE relationship.season_id=? ORDER BY a.slug,b.slug
        """,
        "economy": """
            SELECT transaction_record.tick,transaction_record.category,
                   transaction_record.external_key,account.account_type,
                   COALESCE(owner.slug,household.slug,business.slug),entry.amount_cents,entry.memo
            FROM financial_transactions transaction_record
            JOIN transaction_entries entry ON entry.transaction_id=transaction_record.id
            JOIN financial_accounts account ON account.id=entry.account_id
            LEFT JOIN residents owner ON owner.id=account.resident_id
            LEFT JOIN households household ON household.id=account.household_id
            LEFT JOIN businesses business ON business.id=account.business_id
            WHERE transaction_record.season_id=?
            ORDER BY transaction_record.tick,transaction_record.external_key,entry.id
        """,
        "inventory": """
            SELECT movement.tick,item.sku,movement.quantity,movement.movement_type,
                   movement.from_kind,movement.from_id,movement.to_kind,movement.to_id,
                   movement.unit_price_cents
            FROM inventory_movements movement
            JOIN item_catalog item ON item.id=movement.item_id
            WHERE movement.season_id=? ORDER BY movement.tick,movement.id
        """,
        "events": """
            SELECT tick,event_type,subject_resident_id,related_resident_id,household_id,
                   business_id,property_id,title,summary,outcome,severity,permanent
            FROM life_events WHERE season_id=? ORDER BY tick,id
        """,
        "care": """
            SELECT child.slug,arrangement.arrangement_type,caregiver.slug,business.slug,
                   arrangement.cost_per_day_cents,arrangement.status,arrangement.started_tick,
                   arrangement.ended_tick
            FROM childcare_arrangements arrangement
            JOIN residents child ON child.id=arrangement.child_resident_id
            LEFT JOIN residents caregiver ON caregiver.id=arrangement.caregiver_resident_id
            LEFT JOIN businesses business ON business.id=arrangement.provider_business_id
            WHERE arrangement.started_season_id<=?
              AND (arrangement.ended_season_id IS NULL OR arrangement.ended_season_id>=?)
            ORDER BY child.slug,arrangement.id
        """,
        "goals": """
            SELECT resident.slug,goal.scope,goal.description,goal.status,goal.progress,
                   goal.created_tick,goal.completed_tick
            FROM goals goal JOIN residents resident ON resident.id=goal.resident_id
            WHERE goal.season_id=? ORDER BY resident.slug,goal.scope,goal.id
        """,
    }
    payload: dict[str, list[tuple[Any, ...]]] = {}
    for name, query in queries.items():
        parameter_count = query.count("?")
        payload[name] = [
            tuple(row)
            for row in connection.execute(query, (season_id,) * parameter_count)
        ]
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode()
    ).hexdigest()


def _run_once(seed: str, ticks: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="krabville-quality-") as raw_root:
        connection = initialize(_settings(Path(raw_root)))
        try:
            season_id = int(start_season(connection, seed_hex=seed)["seasonId"])
            initial_stages = _stage_counts(connection)
            initial_relationships = _relationship_snapshot(connection, season_id)
            initial_finances = _financial_totals(connection)
            observed = _observer(connection)
            result: dict[str, Any] = {"status": "running", "tick": 0}
            for _ in range(ticks):
                result = advance_tick(connection)
                _observe_tick(connection, season_id, observed)
                if result["status"] != "running":
                    break

            behaviour = _behaviour(connection, season_id, observed)
            social = _social(connection, season_id, initial_relationships)
            economy = _economy(connection, season_id, initial_finances)
            care = _care(connection, season_id, observed)
            lifecycle = _lifecycle(
                connection,
                season_id,
                initial_stages,
                observed,
                str(result["status"]),
                int(result["tick"]),
            )
            narrative = _narrative_evidence(connection, season_id)
            quick_check = str(connection.execute("PRAGMA quick_check").fetchone()[0])
            foreign_keys = len(list(connection.execute("PRAGMA foreign_key_check")))
            invariants = {
                "quickCheck": quick_check == "ok",
                "foreignKeys": foreign_keys == 0,
                "accountingBalanced": economy["unbalancedTransactions"] == 0
                and economy["aggregateEntryBalanceCents"] == 0
                and economy["totalDebitsCents"] == economy["totalCreditsCents"],
                "dependentCareStructureValid": care[
                    "dependentsWithoutActiveArrangement"
                ]
                == 0
                and care["dependentsWithoutLegalGuardian"] == 0,
                "populationWithinCaps": not lifecycle["populationCapExceeded"]
                and not lifecycle["adultCapExceeded"],
                "housingWithinCapacity": lifecycle["livingWithoutHousehold"] == 0
                and lifecycle["livingWithoutOccupiedHome"] == 0
                and lifecycle["propertyCapacityOverflows"] == 0,
                "lifecycleConsistent": lifecycle["duplicateBirthEvents"] == 0
                and lifecycle["postDeathActivities"] == 0,
                "requestedTicksReached": int(result["tick"]) == ticks,
                "providerUnused": narrative["modelAttempts"] == 0,
            }
            if ticks == TARGET_TICKS:
                season = connection.execute(
                    "SELECT status,seed_revealed FROM seasons WHERE id=?", (season_id,)
                ).fetchone()
                invariants["seasonCompleted"] = (
                    season["status"] == "complete" and int(season["seed_revealed"]) == 1
                )
            return {
                "digest": _stable_digest(connection, season_id),
                "behaviour": behaviour,
                "social": social,
                "economy": economy,
                "careAndHealth": care,
                "eventConcentration": _event_concentration(connection, season_id),
                "lifecycleAndPopulation": lifecycle,
                "narrativeEvidence": narrative,
                "invariants": invariants,
                "invariantsPass": all(invariants.values()),
            }
        finally:
            connection.close()


def _validate_inputs(seeds: Sequence[str], ticks: int, replays: int) -> tuple[str, ...]:
    normalized = tuple(seed.strip().lower() for seed in seeds)
    if len(normalized) < 2:
        raise ValueError("at least two seeds are required")
    if len(set(normalized)) != len(normalized):
        raise ValueError("seeds must be unique")
    if any(
        len(seed) != 64
        or any(character not in "0123456789abcdef" for character in seed)
        for seed in normalized
    ):
        raise ValueError("each seed must be exactly 64 hexadecimal characters")
    if not 1 <= ticks <= TARGET_TICKS:
        raise ValueError(f"ticks must be between 1 and {TARGET_TICKS}")
    if replays < 2:
        raise ValueError("at least two replays are required")
    return normalized


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    category_counts: Counter[str] = Counter()
    for run in runs:
        category_counts.update(
            run["eventConcentration"]["townEventCategories"]["counts"]
        )
    total_categories = sum(category_counts.values())
    return {
        "seedCount": len(runs),
        "allInvariantsPass": all(run["invariantsPass"] for run in runs),
        "allReplaysMatch": all(run["reproducibility"]["matches"] for run in runs),
        "totalDecisions": sum(run["behaviour"]["decisionCount"] for run in runs),
        "uniqueActionsAcrossSeeds": len(
            {
                action
                for run in runs
                for action in run["behaviour"]["actionDistribution"]
            }
        ),
        "maximumRepeatedActionStreak": max(
            (run["behaviour"]["longestRepeatedActionStreak"] for run in runs),
            default=0,
        ),
        "relationshipPairsMoved": sum(run["social"]["movedPairs"] for run in runs),
        "totalSocialInteractions": sum(
            run["social"]["totalInteractionDelta"] for run in runs
        ),
        "postedTransactions": sum(run["economy"]["postedTransactions"] for run in runs),
        "meanProductTurnoverShare": round(
            sum(run["economy"]["productTurnoverShare"] for run in runs) / len(runs),
            6,
        ),
        "minimumDependentCoverageShare": min(
            (run["careAndHealth"]["observedCoverageShare"] for run in runs),
            default=0.0,
        ),
        "townEventCategories": _sorted_counts(category_counts),
        "dominantTownEventCategoryShare": _ratio(
            max(category_counts.values(), default=0), total_categories
        ),
        "minimumLiving": min(
            (run["lifecycleAndPopulation"]["minimumLiving"] for run in runs),
            default=0,
        ),
        "maximumLiving": max(
            (run["lifecycleAndPopulation"]["maximumLiving"] for run in runs),
            default=0,
        ),
    }


def run_quality_baseline(
    *,
    seeds: Sequence[str] = DEFAULT_SEEDS,
    ticks: int = TARGET_TICKS,
    replays: int = 2,
) -> dict[str, Any]:
    normalized = _validate_inputs(seeds, ticks, replays)
    runs: list[dict[str, Any]] = []
    for index, seed in enumerate(normalized, start=1):
        attempts = [_run_once(seed, ticks) for _ in range(replays)]
        primary = attempts[0]
        digests = [attempt["digest"] for attempt in attempts]
        metrics_match = all(attempt == primary for attempt in attempts[1:])
        primary["seedId"] = f"seed-{index:02d}"
        primary["seed"] = seed
        primary["reproducibility"] = {
            "replays": replays,
            "digests": digests,
            "matches": len(set(digests)) == 1 and metrics_match,
        }
        runs.append(primary)

    aggregate = _aggregate(runs)
    status = (
        "pass"
        if aggregate["allInvariantsPass"] and aggregate["allReplaysMatch"]
        else "fail"
    )
    return {
        "reportSchemaVersion": REPORT_SCHEMA_VERSION,
        "simulationVersion": __version__,
        "databaseSchemaVersion": required_schema_version(),
        "status": status,
        "runMode": "full-season" if ticks == TARGET_TICKS else "partial",
        "configuration": {
            "seeds": list(normalized),
            "ticksPerSeed": ticks,
            "replaysPerSeed": replays,
            "providerMode": "disabled",
            "minutesPerTick": MINUTES_PER_TICK,
            "criticalNeedThreshold": CRITICAL_NEED_THRESHOLD,
        },
        "summary": aggregate,
        "runs": runs,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# KVsim deterministic simulation-quality baseline",
        "",
        f"**Status:** {str(report['status']).upper()}",
        "",
        (
            f"KVsim {report['simulationVersion']}; database schema "
            f"{report['databaseSchemaVersion']}; {summary['seedCount']} fixed seeds; "
            f"{report['configuration']['ticksPerSeed']} ticks per seed; "
            f"{report['configuration']['replaysPerSeed']} replays per seed; provider disabled."
        ),
        "",
        "| Seed | Decisions | Actions | Max loop | Moved pairs | Transactions | Product turnover | Care coverage | Living range | Replay |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for run in report["runs"]:
        lines.append(
            "| {seed} | {decisions} | {actions} | {loop} | {pairs} | {transactions} | "
            "{turnover:.1%} | {coverage:.1%} | {low}-{high} | {replay} |".format(
                seed=run["seedId"],
                decisions=run["behaviour"]["decisionCount"],
                actions=run["behaviour"]["uniqueActions"],
                loop=run["behaviour"]["longestRepeatedActionStreak"],
                pairs=run["social"]["movedPairs"],
                transactions=run["economy"]["postedTransactions"],
                turnover=run["economy"]["productTurnoverShare"],
                coverage=run["careAndHealth"]["observedCoverageShare"],
                low=run["lifecycleAndPopulation"]["minimumLiving"],
                high=run["lifecycleAndPopulation"]["maximumLiving"],
                replay="yes" if run["reproducibility"]["matches"] else "NO",
            )
        )
    lines.extend(
        [
            "",
            "## Aggregate observations",
            "",
            f"- {summary['totalDecisions']} decisions used {summary['uniqueActionsAcrossSeeds']} distinct actions.",
            f"- The longest repeated-action streak was {summary['maximumRepeatedActionStreak']} decision(s).",
            f"- {summary['relationshipPairsMoved']} relationship pairs moved across {summary['totalSocialInteractions']} interactions.",
            f"- {summary['postedTransactions']} posted transactions averaged {summary['meanProductTurnoverShare']:.1%} catalog turnover.",
            f"- Minimum observed dependent coverage was {summary['minimumDependentCoverageShare']:.1%}.",
            f"- The dominant town-event category represented {summary['dominantTownEventCategoryShare']:.1%} of events.",
            f"- Living population ranged from {summary['minimumLiving']} to {summary['maximumLiving']}.",
            "",
            "## Correctness invariants",
            "",
        ]
    )
    for run in report["runs"]:
        failed = sorted(
            name for name, passed in run["invariants"].items() if not passed
        )
        lines.append(
            f"- **{run['seedId']}**: "
            + ("pass" if not failed else f"FAIL ({', '.join(failed)})")
        )
    lines.extend(
        [
            "",
            "This report is observational. It records a stable baseline for later balance work and does not change simulation scoring or outcomes.",
            "",
        ]
    )
    return "\n".join(lines)


def write_evidence(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "simulation-quality.json"
    markdown_path = output_dir / "simulation-quality.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path
