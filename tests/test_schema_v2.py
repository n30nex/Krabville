from __future__ import annotations

import sqlite3

import pytest

from krabville.db import initialize
from krabville.world import diagnose, start_season


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _foreign_keys(connection: sqlite3.Connection, table: str) -> set[tuple[str, str, str]]:
    return {
        (str(row["from"]), str(row["table"]), str(row["to"]))
        for row in connection.execute(f"PRAGMA foreign_key_list({table})")
    }


def test_kvsim_v2_schema_is_complete_and_enforces_foreign_keys(settings_factory) -> None:
    connection = initialize(settings_factory())

    required_columns = {
        "resident_identities": {"resident_id", "generation_seed", "display_name", "appearance_key"},
        "resident_lifecycle": {"resident_id", "current_stage", "seasons_in_stage", "death_season_id"},
        "households": {"id", "household_type", "status", "financial_policy"},
        "household_members": {"household_id", "resident_id", "role", "legal_guardian"},
        "family_links": {"resident_id", "relative_resident_id", "relation_type", "biological", "legal"},
        "resident_season_state": {
            "season_id", "resident_id", "life_stage", "mood_label", "health_score",
            "care_state", "decision_state", "current_decision_id", "preferred_action",
            "preference_tags_json",
        },
        "resident_needs": {"season_id", "resident_id", "need_key", "satisfaction", "trend"},
        "resident_wants": {
            "season_id", "resident_id", "kind", "status", "priority", "progress",
            "source_need", "action_key", "expires_tick",
        },
        "life_goals": {"resident_id", "description", "category", "status", "progress", "evidence_json"},
        "housing_recovery": {
            "season_id", "household_id", "status", "stage", "arrears_days",
            "failed_attempts", "stable_days", "next_step",
        },
        "facts": {"season_id", "canonical_key", "statement", "truth_value"},
        "secrets": {"fact_id", "owner_resident_id", "sensitivity", "status"},
        "resident_beliefs": {"resident_id", "fact_id", "stance", "confidence", "source_resident_id"},
        "businesses": {"id", "name", "industry", "property_id", "status"},
        "jobs": {"id", "business_id", "title", "hourly_wage_cents"},
        "employment": {"resident_id", "job_id", "status", "wage_cents"},
        "financial_accounts": {"resident_id", "household_id", "business_id", "account_type"},
        "financial_transactions": {"season_id", "tick", "category", "status"},
        "transaction_entries": {"transaction_id", "account_id", "amount_cents"},
        "assets": {"resident_id", "household_id", "business_id", "value_cents"},
        "debts": {"borrower_account_id", "principal_cents", "outstanding_cents", "status"},
        "investments": {"account_id", "symbol", "units", "market_value_cents"},
        "properties": {"id", "property_type", "resident_capacity", "market_value_cents"},
        "property_occupancy": {"property_id", "household_id", "occupancy_type"},
        "childcare_arrangements": {"child_resident_id", "caregiver_resident_id", "provider_business_id"},
        "health_conditions": {"resident_id", "condition_type", "severity", "status"},
        "life_events": {"season_id", "tick", "event_type", "subject_resident_id", "summary"},
        "decision_history": {"season_id", "resident_id", "phase", "chosen_action", "public_thought"},
        "decision_options": {"decision_id", "option_rank", "utility_score", "selected"},
        "decision_factors": {"decision_id", "option_rank", "factor_kind", "factor_key", "weight"},
        "story_ledger": {"season_id", "tick", "headline", "significance", "visibility"},
    }
    tables = {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert required_columns.keys() <= tables
    for table, columns in required_columns.items():
        assert columns <= _columns(connection, table), table

    assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert not list(connection.execute("PRAGMA foreign_key_check"))
    assert {
        ("household_id", "households", "id"),
        ("resident_id", "residents", "id"),
    } <= _foreign_keys(connection, "household_members")
    assert {
        ("season_id", "seasons", "id"),
        ("resident_id", "residents", "id"),
        ("current_decision_id", "decision_history", "id"),
    } <= _foreign_keys(connection, "resident_season_state")
    assert {
        ("transaction_id", "financial_transactions", "id"),
        ("account_id", "financial_accounts", "id"),
    } <= _foreign_keys(connection, "transaction_entries")
    assert ("child_resident_id", "residents", "id") in _foreign_keys(
        connection, "childcare_arrangements"
    )
    assert ("life_event_id", "life_events", "id") in _foreign_keys(
        connection, "story_ledger"
    )

    resident_count = connection.execute("SELECT COUNT(*) FROM residents").fetchone()[0]
    assert connection.execute("SELECT COUNT(*) FROM resident_identities").fetchone()[0] == resident_count
    assert connection.execute("SELECT COUNT(*) FROM resident_lifecycle").fetchone()[0] == resident_count
    assert connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=13"
    ).fetchone()

    household_id = connection.execute(
        """
        INSERT INTO households(slug,name,household_type,created_at)
        VALUES('schema-test','Schema Test','family','2026-01-01T00:00:00Z')
        RETURNING id
        """
    ).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO household_members(household_id,resident_id,role)
            VALUES(?,999999,'child')
            """,
            (household_id,),
        )

    connection.close()


def test_reopening_v2_database_does_not_restore_the_legacy_cast(settings_factory) -> None:
    settings = settings_factory()
    connection = initialize(settings)
    start_season(connection, seed_hex="a5" * 32)
    assert connection.execute("SELECT COUNT(*) FROM residents").fetchone()[0] == 12
    connection.close()

    connection = initialize(settings)
    assert connection.execute("SELECT COUNT(*) FROM residents").fetchone()[0] == 12
    assert connection.execute("SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1").fetchone()[0] == 12
    assert connection.execute("SELECT COUNT(*) FROM resident_state").fetchone()[0] == 12
    assert connection.execute(
        "SELECT COUNT(*) FROM resident_identities WHERE generation_seed LIKE 'legacy:%'"
    ).fetchone()[0] == 0
    assert diagnose(connection)["residents"] == 12
    connection.close()
