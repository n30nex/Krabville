from __future__ import annotations

from copy import deepcopy

import pytest

from krabville.economy_v2 import (
    MAX_BALANCE_CENTS,
    MAX_DAILY_FLOW_CENTS,
    SETTLEMENT_MINUTE,
    categorized_flow_totals,
    ledger_is_balanced,
    settle_day,
    settle_household_costs,
)


def test_default_workday_and_expenses_settle_at_0400() -> None:
    result = settle_day(
        {
            "balances": {"cash_cents": 10_000, "bank_cents": 100_000},
            "employment": {"active": True},
        }
    )

    assert result["settled_minute"] == 240
    assert result["totals"]["wages_cents"] == 20_800
    assert result["totals"]["expenses_cents"] == 8_800
    assert result["balances"] == {
        "cash_cents": 10_000,
        "bank_cents": 112_000,
        "debt_cents": 0,
        "investments_cents": 0,
    }
    assert ledger_is_balanced(result["ledger"])


def test_childcare_shortfall_becomes_bounded_debt() -> None:
    result = settle_day(
        {
            "balances": {"cash_cents": 500, "bank_cents": 1_000},
            "expenses": {},
            "childcare": {"active": True},
        }
    )

    assert result["totals"]["childcare_cents"] == 6_500
    assert result["balances"]["cash_cents"] == 0
    assert result["balances"]["bank_cents"] == 0
    assert result["balances"]["debt_cents"] == 5_000
    assert ledger_is_balanced(result["ledger"])


def test_debt_accrues_interest_then_pays_daily_share() -> None:
    result = settle_day(
        {
            "balances": {"bank_cents": 100_000, "debt_cents": 100_000},
            "expenses": {},
            "debt": {
                "annual_rate_basis_points": 730,
                "minimum_payment_cents": 3_000,
            },
            "liquid_reserve_cents": 0,
        }
    )

    assert result["totals"]["debt_interest_cents"] == 20
    assert result["totals"]["debt_payment_cents"] == 100
    assert result["balances"]["debt_cents"] == 99_920
    assert result["balances"]["bank_cents"] == 99_900


def test_investment_return_is_deterministic_and_bounded() -> None:
    state = {
        "balances": {"investments_cents": 999_500_000},
        "expenses": {},
        "investment_return_bps": 10_000,
    }

    first = settle_day(state)
    second = settle_day(state)

    assert first == second
    assert first["balances"]["investments_cents"] == MAX_BALANCE_CENTS
    assert first["totals"]["investment_change_cents"] == 500_000


def test_input_is_unchanged_and_every_transaction_balances() -> None:
    state = {
        "balances": {
            "cash_cents": 40_000,
            "bank_cents": 80_000,
            "debt_cents": 25_000,
            "investments_cents": 10_000,
        },
        "employment": {"hourly_wage_cents": 3_000, "worked_minutes": 420},
        "expenses": {"food": 2_000},
        "childcare": {"cost_per_day_cents": 4_500},
        "investment_return_bps": -25,
    }
    original = deepcopy(state)

    result = settle_day(state)

    assert state == original
    assert result["ledger"]
    assert all(sum(entry["amount_cents"] for entry in tx["entries"]) == 0 for tx in result["ledger"])


def test_extreme_inputs_stay_inside_stable_caps() -> None:
    huge = 10**30
    result = settle_day(
        {
            "balances": {
                "cash_cents": huge,
                "bank_cents": huge,
                "debt_cents": huge,
                "investments_cents": huge,
            },
            "employment": {"hourly_wage_cents": huge, "worked_minutes": huge},
            "expenses": {f"expense-{index}": huge for index in range(20)},
            "childcare": {"cost_per_day_cents": huge},
            "investment_return_bps": huge,
            "debt": {"annual_rate_basis_points": huge, "daily_payment_cents": huge},
        }
    )

    assert all(0 <= value <= MAX_BALANCE_CENTS for value in result["balances"].values())
    assert result["totals"]["wages_cents"] <= MAX_DAILY_FLOW_CENTS
    assert result["totals"]["expenses_cents"] <= MAX_DAILY_FLOW_CENTS
    assert abs(result["totals"]["investment_change_cents"]) <= MAX_DAILY_FLOW_CENTS
    assert not result["ledger"] or ledger_is_balanced(result["ledger"])


@pytest.mark.parametrize("minute", [0, 239, 241, 1_439])
def test_settlement_rejects_any_time_except_0400(minute: int) -> None:
    with pytest.raises(ValueError, match="04:00"):
        settle_day({}, minute_of_day=minute)


def test_empty_settlement_is_valid_without_fake_entries() -> None:
    result = settle_day({"balances": {}, "expenses": {}})

    assert result["ledger"] == []
    assert result["balances"] == {
        "cash_cents": 0,
        "bank_cents": 0,
        "debt_cents": 0,
        "investments_cents": 0,
    }
    assert result["settled_minute"] == SETTLEMENT_MINUTE


def test_settlement_exposes_balanced_categorized_flows() -> None:
    result = settle_day(
        {
            "balances": {"bank_cents": 50_000},
            "employment": {"hourly_wage_cents": 3_000, "worked_minutes": 60},
            "expenses": {"housing": 5_500, "utilities": 700},
        }
    )

    assert result["flow_totals_cents"] == categorized_flow_totals(result["ledger"])
    assert result["flow_totals_cents"]["wages"] == 3_000
    assert result["flow_totals_cents"]["housing"] == 5_500
    assert result["flow_totals_cents"]["utilities"] == 700
    assert ledger_is_balanced(result["ledger"])


def test_shared_costs_settle_once_from_household_funds() -> None:
    balances = {"cash_cents": 2_000, "bank_cents": 20_000}
    costs = {"housing": 8_000, "utilities": 1_200, "food": 2_500}
    original_balances = deepcopy(balances)
    original_costs = deepcopy(costs)

    result = settle_household_costs(balances, costs, childcare_cents=1_500)

    assert balances == original_balances
    assert costs == original_costs
    assert result["payer"] == "household"
    assert result["totals"]["expenses_cents"] == 11_700
    assert result["totals"]["childcare_cents"] == 1_500
    assert result["balances"]["bank_cents"] == 6_800
    assert result["balances"]["cash_cents"] == 2_000
    assert result["flow_totals_cents"]["housing"] == 8_000
    assert ledger_is_balanced(result["ledger"])
