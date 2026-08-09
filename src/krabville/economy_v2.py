"""Pure daily financial settlement for KVsim 2.0."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SETTLEMENT_MINUTE = 4 * 60
MAX_BALANCE_CENTS = 1_000_000_000
MAX_DAILY_FLOW_CENTS = 1_000_000
MAX_EXPENSE_ITEM_CENTS = 500_000
DEFAULT_HOURLY_WAGE_CENTS = 2_600
DEFAULT_CHILDCARE_CENTS = 6_500
DEFAULT_DEBT_RATE_BPS = 750
DEFAULT_LIQUID_RESERVE_CENTS = 25_000
DEFAULT_DAILY_EXPENSES = {
    "housing": 5_500,
    "food": 1_800,
    "utilities": 500,
    "transport": 600,
    "essentials": 400,
}


def _integer(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp(value: Any, low: int, high: int, default: int = 0) -> int:
    return max(low, min(high, _integer(value, default)))


def _rounded_ratio(value: int, numerator: int, denominator: int) -> int:
    product = value * numerator
    if product >= 0:
        return (product + denominator // 2) // denominator
    return -((-product + denominator // 2) // denominator)


def _entry(account: str, amount_cents: int) -> dict[str, Any]:
    return {"account": account, "amount_cents": amount_cents}


def _transaction(category: str, description: str, *entries: tuple[str, int]) -> dict[str, Any]:
    posted = [_entry(account, amount) for account, amount in entries if amount]
    if not posted or sum(item["amount_cents"] for item in posted) != 0:
        raise ValueError("financial transaction is not balanced")
    return {"category": category, "description": description, "entries": posted}


def ledger_is_balanced(ledger: list[dict[str, Any]]) -> bool:
    """Return true when every transaction has non-zero entries summing to zero."""

    return bool(ledger) and all(
        transaction.get("entries")
        and all(_integer(entry.get("amount_cents")) != 0 for entry in transaction["entries"])
        and sum(_integer(entry.get("amount_cents")) for entry in transaction["entries"]) == 0
        for transaction in ledger
    )


def categorized_flow_totals(ledger: list[dict[str, Any]]) -> dict[str, int]:
    """Return gross posted cents by transaction category.

    Each transaction is balanced, so its positive side is the gross flow without
    double-counting the matching credits. Unknown or malformed rows are ignored.
    """

    totals: dict[str, int] = {}
    for transaction in ledger:
        entries = transaction.get("entries")
        if not isinstance(entries, list):
            continue
        amount = sum(max(0, _integer(entry.get("amount_cents"))) for entry in entries)
        if not amount:
            continue
        category = _expense_name(transaction.get("category"))
        totals[category] = totals.get(category, 0) + amount
    return totals


def _expense_name(value: Any) -> str:
    name = "_".join(str(value).casefold().split())
    return "".join(character for character in name if character.isalnum() or character == "_")[:32] or "other"


def _pay_expense(
    balances: dict[str, int], ledger: list[dict[str, Any]], category: str, amount: int
) -> int:
    funded = min(
        amount,
        balances["bank_cents"]
        + balances["cash_cents"]
        + MAX_BALANCE_CENTS
        - balances["debt_cents"],
    )
    bank = min(balances["bank_cents"], funded)
    cash = min(balances["cash_cents"], funded - bank)
    borrowed = funded - bank - cash
    if not funded:
        return 0

    balances["bank_cents"] -= bank
    balances["cash_cents"] -= cash
    balances["debt_cents"] += borrowed
    name = _expense_name(category)
    ledger.append(
        _transaction(
            name,
            f"Daily {name.replace('_', ' ')}",
            (f"expense:{name}", funded),
            ("asset:bank", -bank),
            ("asset:cash", -cash),
            ("liability:debt", -borrowed),
        )
    )
    return funded


def settle_day(state: Mapping[str, Any], *, minute_of_day: int = SETTLEMENT_MINUTE) -> dict[str, Any]:
    """Settle one day at 04:00 and return new JSON-shaped financial state."""

    if minute_of_day != SETTLEMENT_MINUTE:
        raise ValueError("daily settlement must run at 04:00")

    source_balances = state.get("balances") if isinstance(state.get("balances"), Mapping) else {}
    balances = {
        name: _clamp(source_balances.get(name), 0, MAX_BALANCE_CENTS)
        for name in ("cash_cents", "bank_cents", "debt_cents", "investments_cents")
    }
    ledger: list[dict[str, Any]] = []
    totals = {
        "wages_cents": 0,
        "expenses_cents": 0,
        "childcare_cents": 0,
        "debt_interest_cents": 0,
        "debt_payment_cents": 0,
        "investment_change_cents": 0,
        "unfunded_cents": 0,
    }

    employment = state.get("employment") if isinstance(state.get("employment"), Mapping) else {}
    if employment and employment.get("active", True):
        hourly = _clamp(employment.get("hourly_wage_cents"), 0, 50_000, DEFAULT_HOURLY_WAGE_CENTS)
        minutes = _clamp(employment.get("worked_minutes"), 0, 16 * 60, 8 * 60)
        wage = min(MAX_DAILY_FLOW_CENTS, hourly * minutes // 60)
        bank = min(wage, MAX_BALANCE_CENTS - balances["bank_cents"])
        cash = min(wage - bank, MAX_BALANCE_CENTS - balances["cash_cents"])
        credited = bank + cash
        if credited:
            balances["bank_cents"] += bank
            balances["cash_cents"] += cash
            ledger.append(
                _transaction(
                    "wages",
                    "Daily wages",
                    ("asset:bank", bank),
                    ("asset:cash", cash),
                    ("income:wages", -credited),
                )
            )
        totals["wages_cents"] = credited
        totals["unfunded_cents"] += wage - credited

    return_bps = _clamp(state.get("investment_return_bps"), -200, 200)
    investment_change = _rounded_ratio(balances["investments_cents"], return_bps, 10_000)
    investment_change = max(
        -min(MAX_DAILY_FLOW_CENTS, balances["investments_cents"]),
        min(MAX_DAILY_FLOW_CENTS, MAX_BALANCE_CENTS - balances["investments_cents"], investment_change),
    )
    if investment_change:
        balances["investments_cents"] += investment_change
        offset = "income:investment" if investment_change > 0 else "expense:investment_loss"
        ledger.append(
            _transaction(
                "investment_return",
                "Daily investment valuation",
                ("asset:investments", investment_change),
                (offset, -investment_change),
            )
        )
    totals["investment_change_cents"] = investment_change

    debt = state.get("debt") if isinstance(state.get("debt"), Mapping) else {}
    annual_rate = _clamp(debt.get("annual_rate_basis_points"), 0, 5_000, DEFAULT_DEBT_RATE_BPS)
    interest = min(
        MAX_DAILY_FLOW_CENTS,
        MAX_BALANCE_CENTS - balances["debt_cents"],
        (balances["debt_cents"] * annual_rate + 3_650_000 - 1) // 3_650_000,
    )
    if interest:
        balances["debt_cents"] += interest
        ledger.append(
            _transaction(
                "debt_interest",
                "Daily debt interest",
                ("expense:debt_interest", interest),
                ("liability:debt", -interest),
            )
        )
    totals["debt_interest_cents"] = interest

    raw_expenses = state.get("expenses", DEFAULT_DAILY_EXPENSES)
    expenses = raw_expenses if isinstance(raw_expenses, Mapping) else {}
    remaining_expense_cap = MAX_DAILY_FLOW_CENTS
    for category, raw_amount in sorted(expenses.items(), key=lambda item: str(item[0])):
        requested = _clamp(raw_amount, 0, MAX_BALANCE_CENTS)
        amount = min(requested, MAX_EXPENSE_ITEM_CENTS, remaining_expense_cap)
        funded = _pay_expense(balances, ledger, str(category), amount)
        totals["expenses_cents"] += funded
        totals["unfunded_cents"] += requested - funded
        remaining_expense_cap -= amount

    childcare = state.get("childcare") if isinstance(state.get("childcare"), Mapping) else {}
    if childcare and childcare.get("active", True):
        requested = _clamp(
            childcare.get("cost_per_day_cents"),
            0,
            MAX_BALANCE_CENTS,
            DEFAULT_CHILDCARE_CENTS,
        )
        amount = min(requested, MAX_EXPENSE_ITEM_CENTS, remaining_expense_cap)
        funded = _pay_expense(balances, ledger, "childcare", amount)
        totals["childcare_cents"] = funded
        totals["unfunded_cents"] += requested - funded

    if balances["debt_cents"]:
        default_monthly = max(2_500, balances["debt_cents"] * 2 // 100)
        monthly_payment = _clamp(
            debt.get("minimum_payment_cents"), 0, MAX_DAILY_FLOW_CENTS * 30, default_monthly
        )
        requested_payment = _clamp(
            debt.get("daily_payment_cents"),
            0,
            MAX_DAILY_FLOW_CENTS,
            (monthly_payment + 29) // 30,
        )
        reserve = _clamp(
            state.get("liquid_reserve_cents"),
            0,
            MAX_BALANCE_CENTS,
            DEFAULT_LIQUID_RESERVE_CENTS,
        )
        available = max(0, balances["bank_cents"] + balances["cash_cents"] - reserve)
        payment = min(requested_payment, available, balances["debt_cents"])
        bank = min(balances["bank_cents"], payment)
        cash = payment - bank
        if payment:
            balances["bank_cents"] -= bank
            balances["cash_cents"] -= cash
            balances["debt_cents"] -= payment
            ledger.append(
                _transaction(
                    "debt_payment",
                    "Daily debt payment",
                    ("liability:debt", payment),
                    ("asset:bank", -bank),
                    ("asset:cash", -cash),
                )
            )
        totals["debt_payment_cents"] = payment

    if ledger and not ledger_is_balanced(ledger):
        raise AssertionError("settlement produced an unbalanced ledger")
    return {
        "settled_minute": SETTLEMENT_MINUTE,
        "balances": balances,
        "totals": totals,
        "ledger": ledger,
        "flow_totals_cents": categorized_flow_totals(ledger),
    }


def settle_household_costs(
    balances: Mapping[str, Any],
    shared_costs: Mapping[str, Any],
    *,
    childcare_cents: int = 0,
    debt: Mapping[str, Any] | None = None,
    liquid_reserve_cents: int = 0,
    minute_of_day: int = SETTLEMENT_MINUTE,
) -> dict[str, Any]:
    """Settle shared costs once against a household balance.

    This deliberately stays separate from resident settlement so rent, utilities,
    food, and care are not charged once per adult. Callers may keep using
    ``settle_day`` unchanged and adopt this helper household by household.
    """

    result = settle_day(
        {
            "balances": balances,
            "expenses": shared_costs,
            "childcare": {
                "active": _integer(childcare_cents) > 0,
                "cost_per_day_cents": childcare_cents,
            },
            "debt": debt or {},
            "liquid_reserve_cents": liquid_reserve_cents,
        },
        minute_of_day=minute_of_day,
    )
    result["payer"] = "household"
    return result
