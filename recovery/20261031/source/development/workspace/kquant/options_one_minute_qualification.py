"""Minute-specific reference contract eligibility; never an execution permission."""
from datetime import date

from . import options_one_minute as rules


def age_ok(value, now, seconds):
    try:
        age = (now - rules.timestamp(value)).total_seconds()
        return 0 <= age <= seconds
    except (ValueError, TypeError, AttributeError):
        return False


def select_contract(original, contracts, *, now, policy):
    limits = policy["contracts"]
    eligible, rejected = [], []
    for raw in contracts:
        row = dict(raw)
        snapshot = row.get("snapshot") or {}
        reasons = []
        try:
            dte = (date.fromisoformat(row["expiry_date"]) - date.fromisoformat(original["session"])).days
        except (KeyError, ValueError, TypeError):
            dte = None
        if dte not in limits["allowed_calendar_dtes"]:
            reasons.append("NO_MATCHING_CALENDAR_DTE")
        if row.get("underlying") != original["symbol"] or row.get("right") != original["right"] or not row.get("contract_id"):
            reasons.append("CONTRACT_IDENTITY_MISMATCH")
        if row.get("deliverable") != "STANDARD" or row.get("adjusted") is not False:
            reasons.append("STANDARD_CONTRACT_NOT_VERIFIED")
        multiplier = row.get("multiplier")
        if not rules.finite(multiplier) or float(multiplier) <= 0 or float(multiplier) != int(float(multiplier)):
            reasons.append("MULTIPLIER_NOT_VERIFIED")
        if snapshot.get("contract_validity") != "UNEXPIRED":
            reasons.append("CONTRACT_TRADING_STATUS_NOT_VALID")
        delta = row.get("delta")
        if not rules.finite(delta) or not limits["delta_abs_min"] <= abs(float(delta)) <= limits["delta_abs_max"]:
            reasons.append("DELTA_OUT_OF_RANGE")
        if not age_ok(snapshot.get("calc_received_at"), now, limits["greeks_age_seconds"]):
            reasons.append("GREEKS_TIME_UNAVAILABLE_OR_STALE")
        if not age_ok(snapshot.get("bbo_received_at"), now, limits["quote_age_seconds"]):
            reasons.append("BBO_TIME_UNAVAILABLE_OR_STALE")
        if snapshot.get("depth_status") != "available":
            reasons.append("DEPTH_NOT_AVAILABLE")
        bid, ask = row.get("bid"), row.get("ask")
        spread = None
        if not rules.finite(bid) or not rules.finite(ask) or not 0 < float(bid) <= float(ask):
            reasons.append("INVALID_TWO_SIDED_QUOTE")
        else:
            spread = (float(ask) - float(bid)) / ((float(ask) + float(bid)) / 2)
            if spread > limits["spread_mid_max"]:
                reasons.append("SPREAD_TOO_WIDE")
        if row.get("size_unit_status") != "VERIFIED_CONTRACTS":
            reasons.append("CONTRACT_QUANTITY_UNIT_UNVERIFIED")
        for side in ("bid", "ask"):
            size = row.get(side + "_size")
            if not rules.finite(size) or float(size) < limits["minimum_" + side + "_size"] or float(size) != int(float(size)):
                reasons.append(side.upper() + "_SIZE_INSUFFICIENT")
        if reasons:
            rejected.append({"contract_id": row.get("contract_id"), "reasons": reasons})
        else:
            eligible.append({**row, "dte": dte, "spread_mid_fraction": spread})
    eligible.sort(key=lambda row: (
        limits["preferred_calendar_dtes"].index(row["dte"]),
        abs(abs(float(row["delta"])) - limits["delta_abs_target"]),
        row["spread_mid_fraction"], row["contract_id"]))
    return {"status": "PASS" if eligible else "BLOCKED", "selected": eligible[0] if eligible else None,
            "rejected": rejected, "checked_at": now.isoformat(),
            "strict_fill_eligible": False, "paper_enabled": False, "real_orders_enabled": False}


def publication_blockers(original, *, now, policy, scope_hash, event, selection, spot, spot_received_at):
    reasons = []
    if now >= rules.timestamp(original["deadline_at"]):
        reasons.append("ORIGINAL_DEADLINE_EXCEEDED")
    if original["policy_hash"] != policy["policy_hash"] or original["scope_hash"] != scope_hash:
        reasons.append("POLICY_OR_SCOPE_CHANGED")
    if not event.get("trade_eligible"):
        reasons.append("EVENT_COVERAGE_NOT_ELIGIBLE")
    if selection.get("status") != "PASS":
        reasons.append("CONTRACT_NOT_QUALIFIED")
    bar = original["bar_evidence"]
    if not rules.finite(spot) or not age_ok(spot_received_at, now, policy["contracts"]["quote_age_seconds"]):
        reasons.append("UNDERLYING_QUOTE_UNAVAILABLE_OR_STALE")
    else:
        direction = 1 if original["right"] == "CALL" else -1
        displacement = direction * (float(spot) - float(bar["close"]))
        if displacement > (float(bar["high"]) - float(bar["low"])) * policy["max_chase_bar_fraction"]:
            reasons.append("CHASE_LIMIT_EXCEEDED")
        if (direction == 1 and float(spot) <= float(bar["low"])) or (direction == -1 and float(spot) >= float(bar["high"])):
            reasons.append("STRUCTURE_INVALIDATED")
        distance = original.get("factor_evidence", {}).get("breakout_distance")
        if rules.finite(distance) and displacement + float(distance) <= 0:
            reasons.append("LOCAL_BREAKOUT_INVALIDATED")
    return reasons
