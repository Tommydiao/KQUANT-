"""Paired expiry research using identical observations and existing liquidity gates."""
from copy import deepcopy
from datetime import date

from .options_one_minute_qualification import select_contract
from . import options_one_minute as common


def reference_from_inspections(original, contracts, *, policy):
    """An explicitly unqualified native reference, never a liquidity fallback."""
    rows = []
    for row in contracts:
        try:
            dte = (date.fromisoformat(row["expiry_date"]) - date.fromisoformat(original["session"])).days
            if (row.get("underlying") != original["symbol"] or row.get("right") != original["right"]
                    or dte not in policy["expiry_comparison"]["extended"] or not row.get("contract_id")
                    or not common.finite(row.get("strike")) or row["strike"] <= 0
                    or not common.finite(row.get("delta"))):
                continue
            rows.append({**row, "dte": dte, "reference_only": True})
        except (KeyError, TypeError, ValueError):
            continue
    rows.sort(key=lambda row: (row["dte"], abs(abs(row["delta"]) - policy["contracts"]["delta_abs_target"]), row["contract_id"]))
    return rows[0] if rows else None


def preferred_from_inspections(original, contracts, *, group, policy):
    """Rank observed eligibility; the selected contract still needs a fresh check."""
    limits = policy["contracts"]
    allowed = policy["expiry_comparison"][group]
    priority = sorted(allowed, key=lambda d: (abs(d - 3), d))
    accepted = []
    for row in contracts:
        stamp = row.get("inspected_at")
        if not stamp:
            continue
        result = compare(original, [row], now=common.timestamp(stamp), policy=policy)["groups"][group]
        if result["selected"]:
            accepted.append(result["selected"])
    accepted.sort(key=lambda row: (priority.index(row["dte"]),
        abs(abs(row["delta"]) - limits["delta_abs_target"]), row["spread_mid_fraction"], row["contract_id"]))
    return accepted[0]["contract_id"] if accepted else None


def compare(original, contracts, *, now, policy):
    # A single snapshot per contract is shared between groups. Conflicting
    # duplicates are rejected instead of silently selecting a favourable row.
    unique, conflicting = {}, set()
    for row in contracts:
        key = row.get("contract_id")
        if not key:
            continue
        if key in unique and unique[key] != row:
            conflicting.add(key)
        else:
            unique[key] = row
    rows, incomplete = [], []
    for key, row in unique.items():
        if key in conflicting:
            continue
        strike = row.get("strike")
        if not common.finite(strike) or strike <= 0:
            incomplete.append({"contract_id": key, "reasons": ["CONTRACT_STRIKE_UNVERIFIED"]})
        elif (row.get("snapshot", {}).get("strike_price") is not None
              and row["snapshot"]["strike_price"] != strike):
            incomplete.append({"contract_id": key, "reasons": ["CONTRACT_IDENTITY_MISMATCH"]})
        elif row.get("quote_currency") != "USD":
            incomplete.append({"contract_id": key, "reasons": ["CONTRACT_CURRENCY_UNVERIFIED"]})
        else:
            rows.append(row)
    groups = {}
    for name, dtes in policy["expiry_comparison"].items():
        scoped = deepcopy(policy)
        scoped["contracts"].update(allowed_calendar_dtes=dtes,
                                    preferred_calendar_dtes=sorted(dtes, key=lambda d: (abs(d - 3), d)))
        groups[name] = select_contract(original, rows, now=now, policy=scoped)
        groups[name]["rejected"].extend(deepcopy(incomplete))
    selected = [group["selected"]["contract_id"] for group in groups.values() if group["selected"]]
    return {"groups": groups, "unique_selected_contracts": sorted(set(selected)),
            "overlapping_selected_contracts": sorted({key for key in selected if selected.count(key) > 1}),
            "conflicting_snapshot_contracts": sorted(conflicting),
            "checked_at": now.isoformat(), "selected_expiry_group": None,
            "research_only": True, "qualified_signal": False,
            "option_return": None, "return_status": "REAL_SAME_CONTRACT_HISTORY_REQUIRED"}
