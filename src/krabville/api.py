from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Cookie, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .content import LOCATION_POINTS
from .db import connect, dumps, initialize, loads, now_iso, transaction
from .security import VoteSecurity, new_csrf
from .runtime_v2 import account_balance


class VoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choiceId: str = Field(min_length=1, max_length=8, pattern=r"^[A-Z0-9_-]+$")
    csrfToken: str = Field(min_length=20, max_length=128)


def _season(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM seasons ORDER BY number DESC LIMIT 1").fetchone()


def _usage(
    connection: sqlite3.Connection,
    season_id: int,
    settings: Settings,
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT COUNT(*) calls,COALESCE(SUM(total_tokens),0) total,
          COALESCE(SUM(input_tokens),0) input,COALESCE(SUM(cached_input_tokens),0) cached,
          COALESCE(SUM(output_tokens),0) output,COALESCE(SUM(reasoning_tokens),0) reasoning
        FROM model_usage WHERE season_id=?
        """,
        (season_id,),
    ).fetchone()
    models = {
        item["model"]: {"calls": int(item["calls"]), "tokens": int(item["tokens"])}
        for item in connection.execute(
            "SELECT model,COUNT(*) calls,COALESCE(SUM(total_tokens),0) tokens FROM model_usage WHERE season_id=? GROUP BY model",
            (season_id,),
        )
    }
    return {
        "calls": int(row["calls"]),
        "callLimit": settings.call_limit,
        "totalTokens": int(row["total"]),
        "tokenGuard": settings.token_guard,
        "inputTokens": int(row["input"]),
        "cachedInputTokens": int(row["cached"]),
        "outputTokens": int(row["output"]),
        "reasoningTokens": int(row["reasoning"]),
        "models": models,
    }


def _poll_payload(connection: sqlite3.Connection, season_id: int) -> dict[str, Any] | None:
    poll = connection.execute(
        "SELECT * FROM polls WHERE season_id=? ORDER BY day DESC LIMIT 1", (season_id,)
    ).fetchone()
    if not poll:
        return None
    options = [
        {
            "choiceId": row["choice_id"],
            "title": row["title"],
            "category": row["category"],
            "preview": row["preview"],
            "votes": int(row["votes"]),
            "winner": int(row["id"]) == int(poll["winner_option_id"] or 0),
        }
        for row in connection.execute(
            "SELECT * FROM poll_options WHERE poll_id=? ORDER BY choice_id", (poll["id"],)
        )
    ]
    return {
        "id": int(poll["id"]),
        "day": int(poll["day"]),
        "status": poll["status"],
        "opensTick": int(poll["opens_tick"]),
        "closesTick": int(poll["closes_tick"]),
        "options": options,
    }


def _resident_live_v2(
    connection: sqlite3.Connection,
    season_id: int,
    resident_id: int,
    row: sqlite3.Row,
) -> dict[str, Any]:
    wants = [
        {
            "title": item["kind"].replace("_", " ").title(),
            "text": item["description"],
            "status": item["status"],
            "confidence": int(item["priority"]),
        }
        for item in connection.execute(
            """
            SELECT kind,description,status,priority FROM resident_wants
            WHERE season_id=? AND resident_id=? AND status IN ('active','pursuing')
            ORDER BY priority DESC,id LIMIT 8
            """,
            (season_id, resident_id),
        )
    ]
    decision_id = int(row["current_decision_id"] or 0)
    candidates = [
        {
            "activity": item["action"],
            "destination": item["destination"],
            "score": round(float(item["utility_score"]), 1),
            "confidence": "chosen" if item["selected"] else f"option {item['option_rank']}",
            "reason": "Need, schedule, weather, relationships, and current goals",
        }
        for item in connection.execute(
            """
            SELECT option_rank,action,destination,utility_score,selected
            FROM decision_options WHERE decision_id=? ORDER BY option_rank
            """,
            (decision_id,),
        )
    ] if decision_id else []
    urgent = [
        str(item["need_key"])
        for item in connection.execute(
            """
            SELECT need_key FROM resident_needs
            WHERE season_id=? AND resident_id=? AND satisfaction<35
            ORDER BY satisfaction,need_key LIMIT 3
            """,
            (season_id, resident_id),
        )
    ]
    stage = str(row["life_stage"] or "adult")
    stage_index = int(row["stage_season_index"] or 0)
    stage_span = {"baby": 1, "child": 1, "teen": 1, "adult": 4, "senior": 2}.get(stage)
    age_label = f"{stage.title()}, season {stage_index + 1} of {stage_span}" if stage_span else stage.title()
    return {
        "needsHighIsGood": True,
        "lifeStage": stage,
        "ageLabel": age_label,
        "household": row["household_name"],
        "householdId": row["household_id"],
        "wants": [item for item in wants if item["title"] != "Aspiration"],
        "aspirations": [item for item in wants if item["title"] == "Aspiration"],
        "decisionCandidates": candidates,
        "pondering": {
            "active": row["decision_state"] == "pondering",
            "thought": row["public_thought"],
            "urgentNeeds": urgent,
            "untilTick": int(row["action_until_tick"]),
        },
        "urgentNeeds": urgent,
        "spriteVariant": resident_id % 12,
    }


def _resident_base_v2(
    connection: sqlite3.Connection,
    season_id: int,
    row: sqlite3.Row,
    indoor_locations: set[str],
) -> dict[str, Any]:
    path = loads(row["path_json"], [])
    activity = str(row["activity"])
    location = str(row["location"])
    outdoors = any(word in activity.casefold() for word in ("walk", "explor", "outside", "garden"))
    indoors = not path and location in indoor_locations and not outdoors
    return {
        "slug": row["slug"],
        "name": row["name"],
        "role": row["role"],
        "routine": row["routine"],
        "about": row["about"],
        "home": row["home"],
        "workplace": row["workplace"],
        "color": row["color"],
        "traits": loads(row["traits_json"], {}),
        "possessions": loads(row["possessions_json"], []),
        "x": float(row["x"]),
        "y": float(row["y"]),
        "destinationX": float(row["destination_x"]),
        "destinationY": float(row["destination_y"]),
        "location": location,
        "activity": activity,
        "publicThought": row["public_thought"],
        "intention": row["intention"],
        "reflection": row["reflection"],
        "mood": row["mood"],
        "needs": loads(row["needs_json"], {}),
        "path": path,
        "indoors": indoors,
        "building": location if indoors else None,
        "updatedTick": int(row["updated_tick"]),
        "care": {
            "state": str(row["care_state"] or "independent"),
            "caregiver": row["caregiver_name"] or row["care_provider_name"],
        },
        **_resident_live_v2(connection, season_id, int(row["id"]), row),
    }


def _resident_detail_v2(
    connection: sqlite3.Connection,
    season_id: int,
    resident_id: int,
) -> dict[str, Any]:
    family = [
        {
            "slug": item["slug"],
            "name": item["name"],
            "relation": item["relation_type"].replace("_", " "),
            "lifeStage": item["current_stage"],
            "household": item["household_name"],
        }
        for item in connection.execute(
            """
            SELECT other.slug,other.name,f.relation_type,l.current_stage,h.name household_name
            FROM family_links f JOIN residents other ON other.id=f.relative_resident_id
            JOIN resident_lifecycle l ON l.resident_id=other.id
            LEFT JOIN household_members hm ON hm.resident_id=other.id AND hm.ended_season_id IS NULL
            LEFT JOIN households h ON h.id=hm.household_id
            WHERE f.resident_id=? AND f.ended_season_id IS NULL ORDER BY f.relation_type,other.name
            """,
            (resident_id,),
        )
    ]
    beliefs = [
        {
            "title": item["stance"].title(),
            "text": item["statement"],
            "status": f"{item['confidence']}% confidence",
            "confidence": int(item["confidence"]),
        }
        for item in connection.execute(
            """
            SELECT b.stance,b.confidence,f.statement FROM resident_beliefs b
            JOIN facts f ON f.id=b.fact_id WHERE b.resident_id=?
            ORDER BY b.updated_tick DESC LIMIT 16
            """,
            (resident_id,),
        )
    ]
    secrets = [
        {
            "title": item["status"].replace("_", " ").title(),
            "text": item["statement"],
            "status": f"Sensitivity {item['sensitivity']}",
            "revealed": item["status"] == "public",
        }
        for item in connection.execute(
            """
            SELECT s.status,s.sensitivity,f.statement FROM secrets s JOIN facts f ON f.id=s.fact_id
            WHERE s.owner_resident_id=? ORDER BY s.created_tick DESC LIMIT 12
            """,
            (resident_id,),
        )
    ]
    conditions = [
        str(item["name"])
        for item in connection.execute(
            "SELECT name FROM health_conditions WHERE resident_id=? AND status IN ('latent','active','recovering') ORDER BY severity DESC",
            (resident_id,),
        )
    ]
    care = list(connection.execute(
        """
        SELECT c.arrangement_type,c.cost_per_day_cents,r.name caregiver_name,b.name provider_name
        FROM childcare_arrangements c LEFT JOIN residents r ON r.id=c.caregiver_resident_id
        LEFT JOIN businesses b ON b.id=c.provider_business_id
        WHERE c.child_resident_id=? AND c.status='active'
        """,
        (resident_id,),
    ))
    current_care = connection.execute(
        """
        SELECT v.care_state,r.name caregiver_name,b.name provider_name
        FROM resident_season_state v
        LEFT JOIN residents r ON r.id=v.current_caregiver_id
        LEFT JOIN businesses b ON b.id=v.current_care_provider_id
        WHERE v.season_id=? AND v.resident_id=?
        """,
        (season_id, resident_id),
    ).fetchone()
    job = connection.execute(
        """
        SELECT j.title,b.name employer,e.status,e.performance,e.scheduled_minutes_per_day,e.wage_cents
        FROM employment e JOIN jobs j ON j.id=e.job_id LEFT JOIN businesses b ON b.id=j.business_id
        WHERE e.resident_id=? AND e.status IN ('active','leave','suspended') ORDER BY e.id DESC LIMIT 1
        """,
        (resident_id,),
    ).fetchone()
    balances: dict[str, int] = {}
    for account in connection.execute(
        "SELECT id,account_type FROM financial_accounts WHERE resident_id=? AND status='open'",
        (resident_id,),
    ):
        balances[str(account["account_type"])] = balances.get(str(account["account_type"]), 0) + account_balance(connection, int(account["id"]))
    investments = int(connection.execute(
        """
        SELECT COALESCE(SUM(i.market_value_cents),0) FROM investments i
        JOIN financial_accounts a ON a.id=i.account_id WHERE a.resident_id=?
        """,
        (resident_id,),
    ).fetchone()[0])
    debt = int(connection.execute(
        """
        SELECT COALESCE(SUM(d.outstanding_cents),0) FROM debts d
        JOIN financial_accounts a ON a.id=d.borrower_account_id
        WHERE a.resident_id=? AND d.status IN ('current','late','defaulted')
        """,
        (resident_id,),
    ).fetchone()[0])
    properties = [
        {
            "id": int(item["id"]), "slug": item["slug"],
            "name": item["name"], "type": item["property_type"],
            "address": item["address"], "mapLocation": item["map_location"],
            "interiorVariant": int(item["interior_variant"]),
            "value": int(item["market_value_cents"]) / 100,
            "status": item["status"], "interiorAvailable": bool(item["interior_key"]),
        }
        for item in connection.execute(
            """
            SELECT DISTINCT p.* FROM properties p
            LEFT JOIN property_ownership own ON own.property_id=p.id
            LEFT JOIN household_members hm ON hm.household_id=own.household_id
            WHERE own.resident_id=? OR hm.resident_id=?
            """,
            (resident_id, resident_id),
        )
    ]
    life_ledger = [
        {
            "id": item["id"], "tick": int(item["tick"]),
            "category": item["event_type"], "title": item["title"], "summary": item["summary"],
        }
        for item in connection.execute(
            """
            SELECT id,tick,event_type,title,summary FROM life_events
            WHERE subject_resident_id=? OR related_resident_id=? ORDER BY season_id DESC,tick DESC LIMIT 30
            """,
            (resident_id, resident_id),
        )
    ]
    phone = connection.execute(
        "SELECT phone_number,device_name,active FROM resident_phones WHERE resident_id=?",
        (resident_id,),
    ).fetchone()
    calls = [
        {
            "tick": int(item["tick"]),
            "direction": "outgoing" if int(item["caller_resident_id"]) == resident_id else "incoming",
            "otherSlug": item["other_slug"],
            "otherName": item["other_name"],
            "purpose": item["purpose"],
            "summary": item["summary"],
            "visibility": item["visibility"],
            "durationMinutes": int(item["duration_minutes"]),
        }
        for item in connection.execute(
            """
            SELECT c.*,
              CASE WHEN c.caller_resident_id=? THEN recipient.slug ELSE caller.slug END other_slug,
              CASE WHEN c.caller_resident_id=? THEN recipient.name ELSE caller.name END other_name
            FROM communications c JOIN residents caller ON caller.id=c.caller_resident_id
            JOIN residents recipient ON recipient.id=c.recipient_resident_id
            WHERE c.season_id=? AND (c.caller_resident_id=? OR c.recipient_resident_id=?)
            ORDER BY c.tick DESC,c.id DESC LIMIT 30
            """,
            (resident_id, resident_id, season_id, resident_id, resident_id),
        )
    ]
    on_person = [
        {
            "name": item["name"], "category": item["category"],
            "quantity": float(item["quantity"]), "condition": int(item["condition_score"]),
            "assetKey": item["asset_key"], "assetIndex": (int(item["item_id"]) - 1) % 182,
        }
        for item in connection.execute(
            """
            SELECT i.id item_id,i.name,i.category,i.asset_key,ri.quantity,ri.condition_score
            FROM resident_inventory ri JOIN item_catalog i ON i.id=ri.item_id
            WHERE ri.resident_id=? AND ri.quantity>0 ORDER BY i.category,i.name
            """,
            (resident_id,),
        )
    ]
    household = connection.execute(
        "SELECT household_id FROM household_members WHERE resident_id=? AND ended_season_id IS NULL",
        (resident_id,),
    ).fetchone()
    home_inventory = [
        {
            "name": item["name"], "category": item["category"],
            "quantity": float(item["quantity"]), "condition": int(item["condition_score"]),
            "assetKey": item["asset_key"], "assetIndex": (int(item["item_id"]) - 1) % 182,
        }
        for item in connection.execute(
            """
            SELECT i.id item_id,i.name,i.category,i.asset_key,hi.quantity,hi.condition_score
            FROM household_inventory hi JOIN item_catalog i ON i.id=hi.item_id
            WHERE hi.household_id=? AND hi.quantity>0 ORDER BY i.category,i.name
            """,
            (household[0] if household else -1,),
        )
    ]
    account_rows = []
    for account in connection.execute(
        "SELECT id,name,account_type,status FROM financial_accounts WHERE resident_id=? ORDER BY id",
        (resident_id,),
    ):
        account_rows.append({
            "name": account["name"], "type": account["account_type"],
            "status": account["status"], "balance": account_balance(connection, int(account["id"])) / 100,
        })
    finance_history = [
        {
            "season": int(item["season_number"]), "day": int(item["day"]),
            "cash": int(item["cash_cents"]) / 100, "debt": int(item["debt_cents"]) / 100,
            "investments": int(item["investments_cents"]) / 100,
            "netWorth": int(item["net_worth_cents"]) / 100,
        }
        for item in connection.execute(
            """
            SELECT fs.*,s.number season_number FROM financial_snapshots fs
            JOIN seasons s ON s.id=fs.season_id
            WHERE fs.owner_kind='resident' AND fs.owner_id=? ORDER BY s.number,fs.day LIMIT 140
            """,
            (resident_id,),
        )
    ]
    transactions = [
        {
            "id": int(item["id"]), "tick": int(item["tick"]),
            "category": item["category"], "description": item["description"],
            "amount": int(item["resident_amount"]) / 100,
        }
        for item in connection.execute(
            """
            SELECT t.id,t.tick,t.category,t.description,SUM(e.amount_cents) resident_amount
            FROM financial_transactions t JOIN transaction_entries e ON e.transaction_id=t.id
            JOIN financial_accounts a ON a.id=e.account_id
            WHERE t.season_id=? AND a.resident_id=? AND t.status='posted'
            GROUP BY t.id ORDER BY t.tick DESC,t.id DESC LIMIT 40
            """,
            (season_id, resident_id),
        )
    ]
    liquid = sum(balances.get(name, 0) for name in ("cash", "chequing", "savings"))
    return {
        "family": family,
        "secrets": secrets,
        "beliefs": beliefs,
        "health": {
            "status": (
                "Care covered" if current_care and current_care["care_state"] in {"covered", "institutional"}
                else "Care gap" if current_care and current_care["care_state"] == "uncovered"
                else "Needs care" if care else "Independent"
            ),
            "conditions": conditions,
            "care": [str(item["arrangement_type"]) for item in care],
            "caregiver": (
                str(current_care["caregiver_name"] or current_care["provider_name"])
                if current_care and (current_care["caregiver_name"] or current_care["provider_name"])
                else str(care[0]["caregiver_name"] or care[0]["provider_name"]) if care else None
            ),
        },
        "career": ({
            "title": job["title"], "employer": job["employer"], "status": job["status"],
            "performance": int(job["performance"]),
            "schedule": f"{int(job['scheduled_minutes_per_day']) // 60}h {int(job['scheduled_minutes_per_day']) % 60:02d}m per workday",
            "income": int(job["wage_cents"]) * int(job["scheduled_minutes_per_day"]) / 6000,
        } if job else {"status": "dependent or between jobs"}),
        "finances": {
            "cash": balances.get("cash", 0) / 100,
            "chequing": balances.get("chequing", 0) / 100,
            "savings": balances.get("savings", 0) / 100,
            "investments": investments / 100,
            "debt": debt / 100,
            "netWorth": (liquid + investments - debt) / 100,
            "accounts": account_rows,
            "history": finance_history,
        },
        "phone": ({
            "number": phone["phone_number"], "device": phone["device_name"],
            "active": bool(phone["active"]),
        } if phone else None),
        "communications": calls,
        "onPersonInventory": on_person,
        "homeInventory": home_inventory,
        "transactions": transactions,
        "properties": properties,
        "lifeLedger": life_ledger,
    }


def _town_v2(connection: sqlite3.Connection, season_id: int) -> dict[str, Any]:
    ledger = [
        {
            "id": row["id"], "tick": int(row["tick"]), "day": int(row["day"]),
            "category": row["entry_type"], "title": row["headline"], "summary": row["summary"],
        }
        for row in connection.execute(
            "SELECT id,tick,day,entry_type,headline,summary FROM story_ledger WHERE season_id=? ORDER BY tick DESC,id DESC LIMIT 120",
            (season_id,),
        )
    ]
    households = []
    families = []
    for household in connection.execute("SELECT * FROM households WHERE status='active' ORDER BY id"):
        members = list(connection.execute(
            """
            SELECT r.slug,r.name,r.home,l.current_stage,hm.role FROM household_members hm
            JOIN residents r ON r.id=hm.resident_id JOIN resident_lifecycle l ON l.resident_id=r.id
            WHERE hm.household_id=? AND hm.ended_season_id IS NULL AND l.alive=1 ORDER BY r.id
            """,
            (household["id"],),
        ))
        account = connection.execute(
            "SELECT id FROM financial_accounts WHERE household_id=? AND name='Household chequing'",
            (household["id"],),
        ).fetchone()
        cash = account_balance(connection, int(account[0])) / 100 if account else 0
        home = str(members[0]["home"]) if members else "No current home"
        inventory = connection.execute(
            """
            SELECT COUNT(*),COALESCE(SUM(hi.quantity*i.base_price_cents),0)
            FROM household_inventory hi JOIN item_catalog i ON i.id=hi.item_id
            WHERE hi.household_id=? AND hi.quantity>0
            """,
            (household["id"],),
        ).fetchone()
        households.append({
            "id": household["id"], "name": household["name"], "home": home,
            "memberSlugs": [row["slug"] for row in members],
            "memberNames": [row["name"] for row in members], "cash": cash,
            "inventoryItems": int(inventory[0]), "inventoryValue": int(inventory[1]) / 100,
            "status": household["status"],
        })
        families.append({
            "id": household["id"], "name": household["name"],
            "members": [
                {"slug": row["slug"], "name": row["name"], "relation": row["role"], "lifeStage": row["current_stage"], "household": household["name"]}
                for row in members
            ],
            "summary": f"{len(members)} living residents share {home}.",
        })
    property_rows = []
    for prop in connection.execute("SELECT * FROM properties WHERE status<>'demolished' ORDER BY id"):
        map_location = str(prop["map_location"] or prop["address"])
        point = LOCATION_POINTS.get(map_location)
        household_occupants = [
            {"slug": item["slug"], "name": item["name"], "lifeStage": item["current_stage"]}
            for item in connection.execute(
                """
                SELECT DISTINCT r.slug,r.name,l.current_stage FROM property_occupancy po
                JOIN household_members hm ON hm.household_id=po.household_id AND hm.ended_season_id IS NULL
                JOIN residents r ON r.id=hm.resident_id JOIN resident_lifecycle l ON l.resident_id=r.id AND l.alive=1
                WHERE po.property_id=? AND po.ended_season_id IS NULL ORDER BY r.id
                """,
                (prop["id"],),
            )
        ]
        inside = [
            {"slug": item["slug"], "name": item["name"], "activity": item["activity"]}
            for item in connection.execute(
                """
                SELECT r.slug,r.name,s.activity FROM resident_state s JOIN residents r ON r.id=s.resident_id
                WHERE s.season_id=? AND s.location=? AND s.path_json='[]' ORDER BY r.id
                """,
                (season_id, map_location),
            )
        ]
        owners = [
            str(item[0])
            for item in connection.execute(
                """
                SELECT COALESCE(r.name,h.name,b.name) FROM property_ownership own
                LEFT JOIN residents r ON r.id=own.resident_id LEFT JOIN households h ON h.id=own.household_id
                LEFT JOIN businesses b ON b.id=own.business_id
                WHERE own.property_id=? AND own.disposed_season_id IS NULL
                """,
                (prop["id"],),
            )
        ]
        business = connection.execute("SELECT id,slug,name,status FROM businesses WHERE property_id=? ORDER BY id DESC LIMIT 1", (prop["id"],)).fetchone()
        if business:
            inventory_summary = connection.execute(
                "SELECT COUNT(*),COALESCE(SUM(quantity),0) FROM business_inventory WHERE business_id=? AND quantity>0",
                (business["id"],),
            ).fetchone()
        else:
            inventory_summary = connection.execute(
                """
                SELECT COUNT(DISTINCT hi.item_id),COALESCE(SUM(hi.quantity),0)
                FROM property_occupancy po JOIN household_inventory hi ON hi.household_id=po.household_id
                WHERE po.property_id=? AND po.ended_season_id IS NULL AND hi.quantity>0
                """,
                (prop["id"],),
            ).fetchone()
        property_rows.append({
            "id": int(prop["id"]), "slug": prop["slug"], "name": prop["name"],
            "type": prop["property_type"], "address": prop["address"],
            "mapLocation": map_location, "owner": ", ".join(owners) or None,
            "occupants": household_occupants, "inside": inside,
            "value": int(prop["market_value_cents"]) / 100, "status": prop["status"],
            "condition": int(prop["condition_score"]),
            "interiorAvailable": bool(prop["interior_key"]),
            "interiorVariant": int(prop["interior_variant"]),
            "inventoryItems": int(inventory_summary[0] or 0),
            "inventoryUnits": float(inventory_summary[1] or 0),
            "x": float(point[0]) if point else None, "y": float(point[1]) if point else None,
            "business": dict(business) if business else None,
        })
    personal_accounts = [int(row[0]) for row in connection.execute("SELECT id FROM financial_accounts WHERE resident_id IS NOT NULL AND status='open'")]
    total_cash_cents = sum(account_balance(connection, account_id) for account_id in personal_accounts)
    total_debt_cents = int(connection.execute("SELECT COALESCE(SUM(outstanding_cents),0) FROM debts WHERE status IN ('current','late','defaulted')").fetchone()[0])
    total_investments_cents = int(connection.execute("SELECT COALESCE(SUM(market_value_cents),0) FROM investments").fetchone()[0])
    business_rows = []
    for business in connection.execute("SELECT * FROM businesses ORDER BY name"):
        account = connection.execute("SELECT id FROM financial_accounts WHERE business_id=? AND name='Operating'", (business["id"],)).fetchone()
        employees = int(connection.execute("SELECT COUNT(*) FROM employment e JOIN jobs j ON j.id=e.job_id WHERE j.business_id=? AND e.status='active'", (business["id"],)).fetchone()[0])
        inventory = connection.execute(
            "SELECT COALESCE(SUM(quantity),0),SUM(CASE WHEN quantity<=reorder_point THEN 1 ELSE 0 END),COUNT(*) FROM business_inventory WHERE business_id=?",
            (business["id"],),
        ).fetchone()
        sales = connection.execute(
            """
            SELECT COALESCE(SUM(e.amount_cents),0) FROM transaction_entries e
            JOIN financial_transactions t ON t.id=e.transaction_id
            JOIN financial_accounts a ON a.id=e.account_id
            WHERE a.business_id=? AND t.season_id=? AND t.category='retail_purchase'
            """,
            (business["id"], season_id),
        ).fetchone()[0]
        prop = connection.execute("SELECT slug,map_location FROM properties WHERE id=?", (business["property_id"],)).fetchone() if business["property_id"] else None
        owner = connection.execute(
            """
            SELECT COALESCE(r.name,h.name) FROM business_owners own
            LEFT JOIN residents r ON r.id=own.resident_id LEFT JOIN households h ON h.id=own.household_id
            WHERE own.business_id=? AND own.disposed_season_id IS NULL ORDER BY own.id LIMIT 1
            """,
            (business["id"],),
        ).fetchone()
        business_rows.append({
            "id": int(business["id"]), "slug": business["slug"], "name": business["name"],
            "industry": business["industry"], "owner": owner[0] if owner else None,
            "employees": employees, "propertySlug": prop["slug"] if prop else None,
            "location": prop["map_location"] if prop else None,
            "cash": account_balance(connection, int(account[0])) / 100 if account else 0,
            "status": business["status"], "inventoryUnits": float(inventory[0] or 0),
            "lowStockItems": int(inventory[1] or 0), "inventoryItems": int(inventory[2] or 0),
            "sales": int(sales) / 100,
        })
    resident_net_worth = []
    for resident in connection.execute("SELECT id FROM residents"):
        accounts = [int(row[0]) for row in connection.execute("SELECT id FROM financial_accounts WHERE resident_id=? AND status='open'", (resident["id"],))]
        liquid = sum(account_balance(connection, account_id) for account_id in accounts)
        investments = int(connection.execute(
            "SELECT COALESCE(SUM(i.market_value_cents),0) FROM investments i JOIN financial_accounts a ON a.id=i.account_id WHERE a.resident_id=?",
            (resident["id"],),
        ).fetchone()[0])
        debt = int(connection.execute(
            "SELECT COALESCE(SUM(d.outstanding_cents),0) FROM debts d JOIN financial_accounts a ON a.id=d.borrower_account_id WHERE a.resident_id=? AND d.status IN ('current','late','defaulted')",
            (resident["id"],),
        ).fetchone()[0])
        resident_net_worth.append(liquid + investments - debt)
    ordered_net_worth = sorted(resident_net_worth)
    median_net_worth = ordered_net_worth[len(ordered_net_worth) // 2] if ordered_net_worth else 0
    recent_transactions = [
        {
            "id": int(row["id"]), "tick": int(row["tick"]), "category": row["category"],
            "description": row["description"], "amount": int(row["volume"]) / 200,
        }
        for row in connection.execute(
            """
            SELECT t.id,t.tick,t.category,t.description,SUM(ABS(e.amount_cents)) volume
            FROM financial_transactions t JOIN transaction_entries e ON e.transaction_id=t.id
            WHERE t.season_id=? AND t.status='posted' GROUP BY t.id ORDER BY t.tick DESC,t.id DESC LIMIT 60
            """,
            (season_id,),
        )
    ]
    economy_history = [
        {
            "season": int(row["season_number"]), "day": int(row["day"]),
            "cash": int(row["cash"]) / 100, "debt": int(row["debt"]) / 100,
            "investments": int(row["investments"]) / 100, "netWorth": int(row["net_worth"]) / 100,
        }
        for row in connection.execute(
            """
            SELECT s.number season_number,fs.day,SUM(fs.cash_cents) cash,SUM(fs.debt_cents) debt,
              SUM(fs.investments_cents) investments,SUM(fs.net_worth_cents) net_worth
            FROM financial_snapshots fs JOIN seasons s ON s.id=fs.season_id
            WHERE fs.owner_kind='resident' GROUP BY fs.season_id,fs.day ORDER BY s.number,fs.day LIMIT 140
            """
        )
    ]
    communications = [
        {
            "tick": int(row["tick"]), "caller": row["caller_slug"],
            "callerName": row["caller_name"], "recipient": row["recipient_slug"],
            "recipientName": row["recipient_name"], "purpose": row["purpose"],
            "visibility": row["visibility"], "durationMinutes": int(row["duration_minutes"]),
            "summary": row["summary"] if row["visibility"] == "public" else "Private call",
        }
        for row in connection.execute(
            """
            SELECT c.*,caller.slug caller_slug,caller.name caller_name,
              recipient.slug recipient_slug,recipient.name recipient_name
            FROM communications c JOIN residents caller ON caller.id=c.caller_resident_id
            JOIN residents recipient ON recipient.id=c.recipient_resident_id
            WHERE c.season_id=? ORDER BY c.tick DESC,c.id DESC LIMIT 60
            """,
            (season_id,),
        )
    ]
    accounts = [
        {
            "ownerKind": "resident" if row["resident_id"] else "household" if row["household_id"] else "business",
            "owner": row["owner_name"], "residentSlug": row["resident_slug"],
            "name": row["name"], "type": row["account_type"], "status": row["status"],
            "balance": account_balance(connection, int(row["id"])) / 100,
        }
        for row in connection.execute(
            """
            SELECT a.*,COALESCE(r.name,h.name,b.name) owner_name,r.slug resident_slug
            FROM financial_accounts a
            LEFT JOIN residents r ON r.id=a.resident_id
            LEFT JOIN households h ON h.id=a.household_id
            LEFT JOIN businesses b ON b.id=a.business_id
            ORDER BY CASE WHEN a.resident_id IS NOT NULL THEN 0 WHEN a.household_id IS NOT NULL THEN 1 ELSE 2 END,
              owner_name,a.name
            """
        )
    ]
    relationship_summary = connection.execute(
        """
        SELECT COUNT(*) pairs,COALESCE(SUM(interactions),0) interactions,
          COALESCE(AVG(affinity),0) affinity,COALESCE(AVG(trust),0) trust,
          COALESCE(AVG(tension),0) tension,COALESCE(AVG(familiarity),0) familiarity
        FROM relationships WHERE season_id=?
        """,
        (season_id,),
    ).fetchone()
    strongest_connections = [
        {
            "residentA": row["resident_a_name"], "residentB": row["resident_b_name"],
            "affinity": int(row["affinity"]), "trust": int(row["trust"]),
            "tension": int(row["tension"]), "interactions": int(row["interactions"]),
        }
        for row in connection.execute(
            """
            SELECT a.name resident_a_name,b.name resident_b_name,r.affinity,r.trust,r.tension,r.interactions
            FROM relationships r JOIN residents a ON a.id=r.resident_a JOIN residents b ON b.id=r.resident_b
            WHERE r.season_id=? ORDER BY (r.affinity+r.trust+r.tension) DESC,r.interactions DESC LIMIT 12
            """,
            (season_id,),
        )
    ]
    inventory_by_category = [
        {"category": row["category"], "units": float(row["units"] or 0), "items": int(row["items"] or 0)}
        for row in connection.execute(
            """
            SELECT category,SUM(quantity) units,COUNT(DISTINCT item_id) items FROM (
              SELECT i.category,bi.item_id,bi.quantity FROM business_inventory bi JOIN item_catalog i ON i.id=bi.item_id
              UNION ALL
              SELECT i.category,hi.item_id,hi.quantity FROM household_inventory hi JOIN item_catalog i ON i.id=hi.item_id
              UNION ALL
              SELECT i.category,ri.item_id,ri.quantity FROM resident_inventory ri JOIN item_catalog i ON i.id=ri.item_id
            ) GROUP BY category ORDER BY units DESC
            """
        )
    ]
    movement_summary = [
        {"type": row["movement_type"], "units": float(row["units"] or 0), "events": int(row["events"] or 0)}
        for row in connection.execute(
            """
            SELECT movement_type,SUM(quantity) units,COUNT(*) events FROM inventory_movements
            WHERE season_id=? GROUP BY movement_type ORDER BY units DESC
            """,
            (season_id,),
        )
    ]
    price_history = [
        {"day": int(row["day"]), "averagePrice": int(row["average_price"] or 0) / 100, "unitsSold": float(row["units_sold"] or 0)}
        for row in connection.execute(
            """
            SELECT day,AVG(average_price_cents) average_price,SUM(units_sold) units_sold
            FROM price_history WHERE season_id=? GROUP BY day ORDER BY day
            """,
            (season_id,),
        )
    ]
    return {
        "world": {
            "width": 3072, "height": 2048, "coordinateSpace": "legacy",
            "mapAsset": "/assets/kvsim-town-v2.webp",
            "interiorsAsset": "/assets/interiors-v3.png",
            "weatherAsset": "/assets/weather-seasons-v1.png",
            "inventoryAsset": "/assets/inventory-items-v1.png",
        },
        "ledger": ledger,
        "townEvents": ledger,
        "households": households,
        "families": families,
        "properties": property_rows,
        "buildings": property_rows,
        "communications": communications,
        "analytics": {
            "relationships": {
                "pairs": int(relationship_summary["pairs"] or 0),
                "interactions": int(relationship_summary["interactions"] or 0),
                "affinity": round(float(relationship_summary["affinity"] or 0), 1),
                "trust": round(float(relationship_summary["trust"] or 0), 1),
                "tension": round(float(relationship_summary["tension"] or 0), 1),
                "familiarity": round(float(relationship_summary["familiarity"] or 0), 1),
            },
            "strongestConnections": strongest_connections,
            "inventoryByCategory": inventory_by_category,
            "movements": movement_summary,
            "prices": price_history,
        },
        "economy": {
            "currency": "CAD", "totalCash": total_cash_cents / 100,
            "totalDebt": total_debt_cents / 100, "totalInvestments": total_investments_cents / 100,
            "medianNetWorth": median_net_worth / 100,
            "employed": int(connection.execute("SELECT COUNT(*) FROM employment WHERE status='active'").fetchone()[0]),
            "unemployed": int(connection.execute("SELECT COUNT(*) FROM resident_lifecycle WHERE alive=1 AND current_stage='adult'").fetchone()[0]) - int(connection.execute("SELECT COUNT(*) FROM employment WHERE status='active'").fetchone()[0]),
            "businesses": business_rows,
            "accounts": accounts,
            "transactions": recent_transactions,
            "history": economy_history,
            "catalogItems": int(connection.execute("SELECT COUNT(*) FROM item_catalog WHERE active=1").fetchone()[0]),
            "stockUnits": float(connection.execute("SELECT COALESCE(SUM(quantity),0) FROM business_inventory").fetchone()[0]),
            "barters": int(connection.execute("SELECT COUNT(*) FROM barter_transactions WHERE season_id=?", (season_id,)).fetchone()[0]),
            "phoneCalls": int(connection.execute("SELECT COUNT(*) FROM communications WHERE season_id=?", (season_id,)).fetchone()[0]),
        },
        "seasonSummaries": [
            {
                "id": row["id"], "number": row["number"], "status": row["status"],
                "progressPercent": round(100 * int(row["current_tick"]) / max(1, int(row["target_ticks"])), 2),
            }
            for row in connection.execute("SELECT id,number,status,current_tick,target_ticks FROM seasons ORDER BY number DESC LIMIT 20")
        ],
    }


def _state(connection: sqlite3.Connection, settings: Settings) -> dict[str, Any]:
    season = _season(connection)
    if not season:
        return {
            "schemaVersion": 3,
            "ok": True,
            "season": None,
            "models": {
                "primary": settings.primary_model,
                "primaryReasoning": settings.primary_reasoning,
                "fallback": settings.fallback_model,
                "fallbackReasoning": settings.fallback_reasoning,
            },
            "currentEvent": None,
            "residents": [],
            "poll": None,
            "usage": {
                "calls": 0,
                "callLimit": settings.call_limit,
                "totalTokens": 0,
                "tokenGuard": settings.token_guard,
                "inputTokens": 0,
                "cachedInputTokens": 0,
                "outputTokens": 0,
                "reasoningTokens": 0,
                "models": {},
            },
            "events": [],
            "conversations": [],
            "goals": [],
            "props": [],
            "chronicles": [],
            "report": None,
            "world": {
                "width": 3072,
                "height": 2048,
                "coordinateSpace": "legacy",
                "mapAsset": "/assets/kvsim-town-v2.webp",
                "interiorsAsset": "/assets/interiors-v3.png",
            },
            "updatedAt": now_iso(),
        }
    season_id = int(season["id"])
    residents = []
    indoor_locations = {
        str(value)
        for row in connection.execute(
            "SELECT name,address,map_location FROM properties WHERE interior_key<>'' AND status NOT IN ('closed','demolished')"
        )
        for value in row
        if value
    }
    for row in connection.execute(
        """
        SELECT r.*,s.x,s.y,s.destination_x,s.destination_y,s.location,s.activity,
          s.public_thought,s.intention,s.reflection,s.mood,s.needs_json,s.path_json,
          s.action_until_tick,s.updated_tick,v.life_stage,v.stage_season_index,
          v.decision_state,v.current_decision_id,v.household_id,v.care_state,
          v.current_caregiver_id,v.current_care_provider_id,
          caregiver.name caregiver_name,care_provider.name care_provider_name,
          h.name household_name
        FROM residents r JOIN resident_state s ON s.resident_id=r.id
        LEFT JOIN resident_season_state v
          ON v.resident_id=r.id AND v.season_id=s.season_id
        LEFT JOIN residents caregiver ON caregiver.id=v.current_caregiver_id
        LEFT JOIN businesses care_provider ON care_provider.id=v.current_care_provider_id
        LEFT JOIN households h ON h.id=v.household_id
        WHERE s.season_id=? ORDER BY r.id
        """,
        (season_id,),
    ):
        residents.append(_resident_base_v2(connection, season_id, row, indoor_locations))
    recent = [
        {
            "seq": int(row["seq"]),
            "tick": int(row["tick"]),
            "type": row["event_type"],
            "payload": loads(row["payload_json"], {}),
            "createdAt": row["created_at"],
        }
        for row in connection.execute(
            "SELECT * FROM event_stream WHERE season_id=? ORDER BY seq DESC LIMIT 60", (season_id,)
        )
    ][::-1]
    report = connection.execute("SELECT * FROM reports WHERE season_id=?", (season_id,)).fetchone()
    current_event = connection.execute(
        "SELECT * FROM town_events WHERE season_id=? ORDER BY day DESC,id DESC LIMIT 1", (season_id,)
    ).fetchone()
    conversations = [
        {
            "tick": int(row["tick"]),
            "residentA": row["a_slug"],
            "residentAName": row["a_name"],
            "residentB": row["b_slug"],
            "residentBName": row["b_name"],
            "location": row["location"],
            "dialogue": loads(row["dialogue_json"], []),
            "summary": row["summary"],
        }
        for row in connection.execute(
            """
            SELECT c.*,a.slug a_slug,a.name a_name,b.slug b_slug,b.name b_name
            FROM conversations c JOIN residents a ON a.id=c.resident_a
            JOIN residents b ON b.id=c.resident_b
            WHERE c.season_id=? ORDER BY c.id DESC LIMIT 12
            """,
            (season_id,),
        )
    ][::-1]
    goals = [
        {
            "resident": row["slug"],
            "residentName": row["name"],
            "scope": row["scope"],
            "description": row["description"],
            "status": row["status"],
            "progress": int(row["progress"]),
        }
        for row in connection.execute(
            """
            SELECT g.*,r.slug,r.name FROM goals g JOIN residents r ON r.id=g.resident_id
            WHERE g.season_id=? ORDER BY g.status,g.scope,g.id LIMIT 36
            """,
            (season_id,),
        )
    ]
    props = [
        {
            "location": row["location"],
            "prop": row["prop"],
            "status": row["status"],
            "createdTick": int(row["created_tick"]),
        }
        for row in connection.execute(
            "SELECT * FROM world_props WHERE season_id=? AND status='present' ORDER BY id",
            (season_id,),
        )
    ]
    chronicles = [
        {"day": int(row["day"]), "title": row["title"], "narrative": row["narrative"]}
        for row in connection.execute(
            "SELECT day,title,narrative FROM daily_chronicles WHERE season_id=? ORDER BY day",
            (season_id,),
        )
    ]
    complete = season["status"] == "complete"
    return {
        "schemaVersion": 3,
        "ok": True,
        "season": {
            "id": season_id,
            "number": int(season["number"]),
            "status": season["status"],
            "tick": int(season["current_tick"]),
            "targetTicks": int(season["target_ticks"]),
            "day": int(season["current_day"]),
            "worldMinutes": int(season["world_minutes"]),
            "progressPercent": 100.0 if complete else round(
                100 * int(season["current_tick"]) / max(1, int(season["target_ticks"])), 2
            ),
            "seedCommitment": season["seed_commitment"],
            "revealedSeed": season["seed_hex"] if season["seed_revealed"] else None,
            "modelLocked": bool(season["model_locked"]),
            "modelDegraded": bool(season["model_degraded"]),
            "weather": loads(season["weather_json"], {}),
            "startedAt": season["started_at"],
            "completedAt": season["completed_at"],
            "completionReason": season["completion_reason"],
        },
        "models": {
            "primary": settings.primary_model,
            "primaryReasoning": settings.primary_reasoning,
            "fallback": settings.fallback_model,
            "fallbackReasoning": settings.fallback_reasoning,
        },
        "currentEvent": (
            {
                "day": int(current_event["day"]),
                "slug": current_event["slug"],
                "title": current_event["title"],
                "category": current_event["category"],
                "summary": current_event["summary"],
                "prop": current_event["prop"],
                "strange": bool(current_event["strange"]),
                "participants": loads(current_event["participants_json"], []),
            }
            if current_event else None
        ),
        "residents": residents,
        "poll": _poll_payload(connection, season_id),
        "usage": _usage(connection, season_id, settings),
        "events": recent,
        "conversations": conversations,
        "goals": goals,
        "props": props,
        "chronicles": chronicles,
        "report": (
            {
                "headline": report["headline"],
                "narrative": report["narrative"],
                "poster": f"/reports/season-{int(season['number']):03d}.png",
                "statistics": loads(report["statistics_json"], {}),
            }
            if report else None
        ),
        **_town_v2(connection, season_id),
        "updatedAt": now_iso(),
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_directories()
    bootstrap = initialize(settings)
    bootstrap.close()
    security = VoteSecurity(settings.voter_secret)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        yield

    app = FastAPI(title="Krabville Public API", version="2.0.1", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["krab.canadaverse.org", "127.0.0.1", "localhost", "testserver"],
    )

    @app.middleware("http")
    async def harden(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Robots-Tag"] = "noindex, noarchive"
        if response.headers.get("Content-Type", "").lower().startswith("text/html"):
            response.headers["Cache-Control"] = "no-store, no-transform"
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        if not security.voter_key(request.cookies.get("kv_voter")):
            response.set_cookie("kv_voter", security.new_voter_cookie(), httponly=True, secure=secure, samesite="lax", max_age=7776000)
        if not request.cookies.get("kv_csrf"):
            response.set_cookie("kv_csrf", new_csrf(), httponly=False, secure=secure, samesite="lax", max_age=86400)
        return response

    @app.get("/healthz")
    def healthz():
        connection = connect(settings.database_path, readonly=True)
        try:
            quick = connection.execute("PRAGMA quick_check").fetchone()[0]
            season = _season(connection)
            season_payload = (
                {
                    "number": int(season["number"]),
                    "status": season["status"],
                    "day": int(season["current_day"]),
                    "progressPercent": round(
                        (int(season["current_tick"]) / int(season["target_ticks"])) * 100,
                        2,
                    ),
                    "modelLocked": bool(season["model_locked"]),
                    "modelDegraded": bool(season["model_degraded"]),
                }
                if season
                else None
            )
            return {
                "ok": quick == "ok",
                "database": quick,
                "seasonStatus": season["status"] if season else "draft",
                "season": season_payload,
                "models": {
                    "primary": settings.primary_model,
                    "primaryReasoning": settings.primary_reasoning,
                    "fallback": settings.fallback_model,
                    "fallbackReasoning": settings.fallback_reasoning,
                },
                "usage": _usage(connection, int(season["id"]), settings) if season else None,
                "residentCount": int(connection.execute("SELECT COUNT(*) FROM residents").fetchone()[0]),
                "updatedAt": now_iso(),
            }
        finally:
            connection.close()

    @app.get("/readyz")
    def readyz():
        return healthz()

    @app.get("/api/v3/state")
    @app.get("/api/v2/state")
    def state():
        connection = connect(settings.database_path, readonly=True)
        try:
            return _state(connection, settings)
        finally:
            connection.close()

    @app.get("/api/krabville/state")
    def compatibility_state():
        value = state()
        season = value.get("season") or {}
        return {
            "ok": value["ok"],
            "simulation": "krabville-v2",
            "step": season.get("tick", 0),
            "run": {
                "status": season.get("status", "draft"),
                "current_step": season.get("tick", 0),
                "target_step": season.get("targetTicks", 2016),
                "run_progress_percent": season.get("progressPercent", 0),
                "day": season.get("day", 0),
                "residents": len(value.get("residents", [])),
            },
            "residents": value.get("residents", []),
            "world": {"weather": season.get("weather"), "today_event": value.get("currentEvent"), "week_report": value.get("report")},
            "tokens": value.get("usage", {}),
        }

    @app.get("/api/v3/events")
    @app.get("/api/v2/events")
    def events(after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500)):
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            if not season:
                return {"events": [], "next": after}
            rows = list(
                connection.execute(
                    "SELECT * FROM event_stream WHERE season_id=? AND seq>? ORDER BY seq LIMIT ?",
                    (season["id"], after, limit),
                )
            )
            items = [{"seq": int(row["seq"]), "tick": int(row["tick"]), "type": row["event_type"], "payload": loads(row["payload_json"], {}), "createdAt": row["created_at"]} for row in rows]
            return {"events": items, "next": items[-1]["seq"] if items else after}
        finally:
            connection.close()

    @app.get("/api/v3/events/stream")
    @app.get("/api/v2/events/stream")
    async def event_stream(request: Request, last_event_id: str | None = Header(None, alias="Last-Event-ID")):
        start = int(last_event_id or request.query_params.get("after") or 0)

        async def stream():
            cursor = start
            while not await request.is_disconnected():
                connection = connect(settings.database_path, readonly=True)
                try:
                    season = _season(connection)
                    rows = list(
                        connection.execute(
                            "SELECT * FROM event_stream WHERE season_id=? AND seq>? ORDER BY seq LIMIT 100",
                            (season["id"], cursor),
                        ) if season else []
                    )
                finally:
                    connection.close()
                if rows:
                    for row in rows:
                        cursor = int(row["seq"])
                        data = json.dumps({"tick": int(row["tick"]), "payload": loads(row["payload_json"], {}), "createdAt": row["created_at"]}, separators=(",", ":"))
                        yield f"id: {cursor}\nevent: {row['event_type']}\ndata: {data}\n\n"
                else:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.get("/api/v3/economy")
    def economy():
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            if not season:
                return {"economy": {}, "households": [], "properties": []}
            town = _town_v2(connection, int(season["id"]))
            return {
                "economy": town["economy"], "households": town["households"],
                "properties": town["properties"], "updatedAt": now_iso(),
            }
        finally:
            connection.close()

    @app.get("/api/v3/properties/{slug}")
    @app.get("/api/v3/buildings/{slug}")
    def property_detail(slug: str):
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            prop = connection.execute("SELECT * FROM properties WHERE slug=?", (slug,)).fetchone()
            if not prop:
                raise HTTPException(404, "property not found")
            season_id = int(season["id"]) if season else 0
            map_location = str(prop["map_location"] or prop["address"])
            residents = [
                {"slug": row["slug"], "name": row["name"], "activity": row["activity"], "mood": row["mood"]}
                for row in connection.execute(
                    """
                    SELECT r.slug,r.name,s.activity,s.mood FROM resident_state s
                    JOIN residents r ON r.id=s.resident_id
                    WHERE s.season_id=? AND s.location=? AND s.path_json='[]' ORDER BY r.id
                    """,
                    (season_id, map_location),
                )
            ]
            households = [
                {"id": int(row["id"]), "name": row["name"]}
                for row in connection.execute(
                    """
                    SELECT h.id,h.name FROM property_occupancy po JOIN households h ON h.id=po.household_id
                    WHERE po.property_id=? AND po.ended_season_id IS NULL
                    """,
                    (prop["id"],),
                )
            ]
            business = connection.execute("SELECT * FROM businesses WHERE property_id=? ORDER BY id DESC LIMIT 1", (prop["id"],)).fetchone()
            stock = []
            transactions = []
            if business:
                stock = [
                    {
                        "name": row["name"], "category": row["category"],
                        "quantity": float(row["quantity"]), "price": int(row["price_cents"]) / 100,
                        "lowStock": float(row["quantity"]) <= float(row["reorder_point"]),
                        "assetKey": row["asset_key"], "assetIndex": (int(row["item_id"]) - 1) % 182,
                    }
                    for row in connection.execute(
                        """
                        SELECT i.id item_id,i.name,i.category,i.asset_key,bi.quantity,bi.price_cents,bi.reorder_point
                        FROM business_inventory bi JOIN item_catalog i ON i.id=bi.item_id
                        WHERE bi.business_id=? ORDER BY i.category,i.name
                        """,
                        (business["id"],),
                    )
                ]
                transactions = [
                    {
                        "id": int(row["id"]), "tick": int(row["tick"]),
                        "category": row["category"], "description": row["description"],
                        "amount": int(row["amount"]) / 100,
                    }
                    for row in connection.execute(
                        """
                        SELECT t.id,t.tick,t.category,t.description,SUM(e.amount_cents) amount
                        FROM financial_transactions t JOIN transaction_entries e ON e.transaction_id=t.id
                        JOIN financial_accounts a ON a.id=e.account_id
                        WHERE a.business_id=? AND t.status='posted' GROUP BY t.id
                        ORDER BY t.tick DESC,t.id DESC LIMIT 40
                        """,
                        (business["id"],),
                    )
                ]
            home_stock = []
            for household in households:
                home_stock.extend(
                    {
                        "name": row["name"], "category": row["category"],
                        "quantity": float(row["quantity"]), "assetKey": row["asset_key"],
                        "assetIndex": (int(row["item_id"]) - 1) % 182,
                    }
                    for row in connection.execute(
                        """
                        SELECT i.id item_id,i.name,i.category,i.asset_key,hi.quantity FROM household_inventory hi
                        JOIN item_catalog i ON i.id=hi.item_id
                        WHERE hi.household_id=? AND hi.quantity>0 ORDER BY i.category,i.name
                        """,
                        (household["id"],),
                    )
                )
            return {
                "id": int(prop["id"]), "slug": prop["slug"], "name": prop["name"],
                "type": prop["property_type"], "address": prop["address"],
                "mapLocation": map_location, "status": prop["status"],
                "condition": int(prop["condition_score"]), "value": int(prop["market_value_cents"]) / 100,
                "interiorVariant": int(prop["interior_variant"]), "residents": residents,
                "households": households, "business": dict(business) if business else None,
                "inventory": stock or home_stock, "transactions": transactions,
            }
        finally:
            connection.close()

    @app.get("/api/v3/residents/{slug}")
    @app.get("/api/v2/residents/{slug}")
    def resident(slug: str):
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            if not season:
                raise HTTPException(404, "season not found")
            resident_row = connection.execute(
                """
                SELECT r.*,s.x,s.y,s.destination_x,s.destination_y,s.location,s.activity,
                  s.public_thought,s.intention,s.reflection,s.mood,s.needs_json,s.path_json,
                  s.action_until_tick,s.updated_tick,v.life_stage,v.stage_season_index,
                  v.decision_state,v.current_decision_id,v.household_id,v.care_state,
                  v.current_caregiver_id,v.current_care_provider_id,
                  caregiver.name caregiver_name,care_provider.name care_provider_name,
                  h.name household_name
                FROM residents r JOIN resident_state s ON s.resident_id=r.id
                LEFT JOIN resident_season_state v
                  ON v.resident_id=r.id AND v.season_id=s.season_id
                LEFT JOIN residents caregiver ON caregiver.id=v.current_caregiver_id
                LEFT JOIN businesses care_provider ON care_provider.id=v.current_care_provider_id
                LEFT JOIN households h ON h.id=v.household_id
                WHERE s.season_id=? AND r.slug=?
                """,
                (season["id"], slug),
            ).fetchone()
            if not resident_row:
                raise HTTPException(404, "resident not found")
            resident_id = int(resident_row["id"])
            indoor_locations = {
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT map_location FROM properties WHERE interior_key<>'' AND status NOT IN ('closed','demolished')"
                )
                if row[0]
            }
            base = _resident_base_v2(
                connection, int(season["id"]), resident_row, indoor_locations
            )
            goals = [dict(item) for item in connection.execute("SELECT scope,description,status,progress FROM goals WHERE season_id=? AND resident_id=? ORDER BY id DESC LIMIT 12", (season["id"], resident_id))]
            memories = [dict(item) for item in connection.execute("SELECT kind,content,tags,valence,salience,location,created_tick FROM memories WHERE season_id=? AND resident_id=? ORDER BY created_tick DESC,id DESC LIMIT 20", (season["id"], resident_id))]
            relationships = [dict(item) for item in connection.execute("""
                SELECT CASE WHEN rel.resident_a=? THEN b.slug ELSE a.slug END otherSlug,
                  CASE WHEN rel.resident_a=? THEN b.name ELSE a.name END otherName,
                  rel.affinity,rel.trust,rel.tension,rel.familiarity,rel.interactions,
                  rel.attraction,rel.affection,rel.respect,rel.commitment,rel.resentment
                FROM relationships rel JOIN residents a ON a.id=rel.resident_a JOIN residents b ON b.id=rel.resident_b
                WHERE rel.season_id=? AND (rel.resident_a=? OR rel.resident_b=?)
                ORDER BY (rel.affinity+rel.trust-rel.tension) DESC
                """, (resident_id, resident_id, season["id"], resident_id, resident_id))]
            return {
                **base,
                "goals": goals, "memories": memories, "relationships": relationships,
                **_resident_detail_v2(connection, int(season["id"]), resident_id),
            }
        finally:
            connection.close()

    @app.get("/api/v3/relationships")
    @app.get("/api/v2/relationships")
    def relationships():
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            if not season:
                return {"relationships": []}
            rows = connection.execute("""
                SELECT a.slug aSlug,a.name aName,b.slug bSlug,b.name bName,
                  r.affinity,r.trust,r.tension,r.familiarity,r.interactions,r.last_interaction_tick lastInteractionTick
                FROM relationships r JOIN residents a ON a.id=r.resident_a JOIN residents b ON b.id=r.resident_b
                WHERE r.season_id=? ORDER BY (r.affinity+r.trust-r.tension) DESC
                """, (season["id"],))
            return {"relationships": [dict(row) for row in rows]}
        finally:
            connection.close()

    @app.get("/api/v3/polls/current")
    @app.get("/api/v2/polls/current")
    def current_poll():
        connection = connect(settings.database_path, readonly=True)
        try:
            season = _season(connection)
            return {"poll": _poll_payload(connection, int(season["id"])) if season else None}
        finally:
            connection.close()

    @app.post("/api/v3/polls/{poll_id}/vote")
    @app.post("/api/v2/polls/{poll_id}/vote")
    def vote(poll_id: int, body: VoteRequest, request: Request, kv_voter: str | None = Cookie(None), kv_csrf: str | None = Cookie(None)):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in {settings.public_origin.rstrip("/"), "http://127.0.0.1:18889", "http://127.0.0.1:18890", "http://testserver"}:
            raise HTTPException(403, "origin rejected")
        if not kv_csrf or not secrets_compare(kv_csrf, body.csrfToken):
            raise HTTPException(403, "csrf rejected")
        voter_key = security.voter_key(kv_voter)
        if not voter_key:
            raise HTTPException(401, "voter cookie required")
        address = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
        network_key = security.network_key(address)
        if not security.check_rate(network_key):
            raise HTTPException(429, "vote rate limit reached")
        connection = connect(settings.database_path)
        try:
            with transaction(connection, immediate=True):
                poll = connection.execute("SELECT * FROM polls WHERE id=?", (poll_id,)).fetchone()
                if not poll or poll["status"] != "open":
                    raise HTTPException(409, "poll is not open")
                option = connection.execute("SELECT * FROM poll_options WHERE poll_id=? AND choice_id=?", (poll_id, body.choiceId)).fetchone()
                if not option:
                    raise HTTPException(422, "invalid choice")
                connection.execute("""
                    INSERT INTO votes(poll_id,voter_key,network_key,option_id,updated_at)
                    VALUES(?,?,?,?,?) ON CONFLICT(poll_id,voter_key) DO UPDATE SET
                      network_key=excluded.network_key,option_id=excluded.option_id,updated_at=excluded.updated_at
                    """, (poll_id, voter_key, network_key, option["id"], now_iso()))
                connection.execute("""
                    UPDATE poll_options SET votes=(SELECT COUNT(*) FROM votes WHERE votes.option_id=poll_options.id)
                    WHERE poll_id=?
                    """, (poll_id,))
            return {"ok": True, "poll": _poll_payload(connection, int(poll["season_id"]))}
        finally:
            connection.close()

    @app.get("/api/v3/seasons")
    @app.get("/api/v2/seasons")
    def seasons():
        connection = connect(settings.database_path, readonly=True)
        try:
            rows = connection.execute("SELECT id,number,status,created_at,started_at,completed_at,seed_commitment,seed_hex,seed_revealed,current_tick,target_ticks FROM seasons ORDER BY number DESC LIMIT 104")
            return {"seasons": [{"id": row["id"], "number": row["number"], "status": row["status"], "createdAt": row["created_at"], "startedAt": row["started_at"], "completedAt": row["completed_at"], "seedCommitment": row["seed_commitment"], "revealedSeed": row["seed_hex"] if row["seed_revealed"] else None, "progressPercent": round(100 * row["current_tick"] / max(1, row["target_ticks"]), 2)} for row in rows]}
        finally:
            connection.close()

    @app.get("/api/v3/seasons/{season_id}")
    @app.get("/api/v2/seasons/{season_id}")
    def season_detail(season_id: int):
        connection = connect(settings.database_path, readonly=True)
        try:
            season = connection.execute("SELECT * FROM seasons WHERE id=?", (season_id,)).fetchone()
            if not season:
                raise HTTPException(404, "season not found")
            chronicles = [dict(row) for row in connection.execute("SELECT day,title,narrative,statistics_json FROM daily_chronicles WHERE season_id=? ORDER BY day", (season_id,))]
            report = connection.execute("SELECT * FROM reports WHERE season_id=?", (season_id,)).fetchone()
            public_season = {
                "id": int(season["id"]),
                "number": int(season["number"]),
                "status": season["status"],
                "createdAt": season["created_at"],
                "startedAt": season["started_at"],
                "completedAt": season["completed_at"],
                "seedCommitment": season["seed_commitment"],
                "revealedSeed": season["seed_hex"] if season["seed_revealed"] else None,
                "currentTick": int(season["current_tick"]),
                "targetTicks": int(season["target_ticks"]),
                "completionReason": season["completion_reason"],
                "weather": loads(season["weather_json"], {}),
            }
            public_chronicles = []
            for row in chronicles:
                statistics = loads(row.pop("statistics_json"), {})
                public_chronicles.append({**row, "statistics": statistics})
            public_report = None
            if report:
                public_report = {
                    "headline": report["headline"],
                    "narrative": report["narrative"],
                    "poster": f"/reports/season-{int(season['number']):03d}.png",
                    "statistics": loads(report["statistics_json"], {}),
                    "createdAt": report["created_at"],
                }
            return {
                "season": public_season,
                "chronicles": public_chronicles,
                "report": public_report,
            }
        finally:
            connection.close()

    @app.get("/reports/{filename}")
    def report_file(filename: str):
        if not re_report_name(filename):
            raise HTTPException(404, "report not found")
        path = settings.report_dir / filename
        if not path.exists():
            raise HTTPException(404, "report not found")
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public,max-age=3600"})

    if settings.frontend_dir.exists():
        asset_path = settings.frontend_dir / "assets"
        if asset_path.exists():
            app.mount("/assets", StaticFiles(directory=asset_path), name="assets")

        @app.get("/{path:path}", response_class=HTMLResponse)
        def frontend(path: str):
            candidate = (settings.frontend_dir / path).resolve()
            if path and candidate.is_file() and settings.frontend_dir in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(settings.frontend_dir / "index.html")

    return app


def secrets_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a, b)


def re_report_name(value: str) -> bool:
    import re
    return bool(re.fullmatch(r"season-\d{3}\.png", value))


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.port, workers=1, proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
