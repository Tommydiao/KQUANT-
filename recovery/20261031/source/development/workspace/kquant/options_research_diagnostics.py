"""Descriptive option friction and fixed-horizon stock labels, never trade fills."""
from datetime import timedelta
from math import ceil

from . import options_one_minute as common
from . import options_opening_trend as trend


def option_cost(quote, *, now, fees=None):
    result = {"role": "DIAGNOSTIC_ONLY", "state": "UNAVAILABLE", "reasons": [],
        **dict.fromkeys(("spread", "spread_pct_mid", "spread_pct_ask", "premium_cash_reference",
            "spread_cash_reference", "spread_equivalent_underlying_move", "round_trip_cost_per_unit",
            "cost_equivalent_underlying_move")),
        "interpretation": "DELTA_LOCAL_FRICTION_EQUIVALENT_NOT_TARGET",
        "quote_received_at": quote.get("bbo_received_at"), "currency": quote.get("currency")}
    bid, ask, delta, multiplier = (quote.get(k) for k in ("bid", "ask", "delta", "multiplier"))
    try:
        age = (now - common.timestamp(quote["bbo_received_at"])).total_seconds()
        fresh = 0 <= age <= 3
    except (KeyError, TypeError, ValueError):
        fresh = False
        age = None
    result["receipt_age_seconds"] = age
    result["source_freshness"] = quote.get("source_freshness", "UNVERIFIED")
    if not fresh:
        result["reasons"].append("BBO_RECEIPT_STALE_OR_FUTURE")
    if not all(common.finite(x) for x in (bid, ask)) or not 0 <= bid <= ask or ask + bid <= 0:
        result["reasons"].append("BBO_INVALID")
        return result
    if not fresh:
        return result
    spread = ask - bid
    result.update(state="PARTIAL", spread=spread, spread_pct_mid=spread / ((bid + ask) / 2),
                  spread_pct_ask=spread / ask)
    amount_ok = (quote.get("multiplier_verified") is True and quote.get("price_unit_verified") is True
        and quote.get("currency_verified") is True and isinstance(quote.get("currency"), str)
        and common.finite(multiplier) and multiplier > 0)
    if amount_ok:
        result.update(premium_cash_reference=ask * multiplier, spread_cash_reference=spread * multiplier)
    else:
        result["reasons"].append("AMOUNT_BASIS_UNVERIFIED")
    try:
        greek_age = (now - common.timestamp(quote["greeks_received_at"])).total_seconds()
        greek_ok = common.finite(delta) and delta != 0 and 0 <= greek_age <= 60
    except (KeyError, TypeError, ValueError):
        greek_ok = False
    if greek_ok:
        result["spread_equivalent_underlying_move"] = spread / abs(delta)
    else:
        result["reasons"].append("DELTA_MISSING_ZERO_OR_STALE")
    fees = fees or {}
    names = ("fee_in", "fee_out", "slippage_in", "slippage_out")
    fee_ok = amount_ok and fees.get("currency") == quote.get("currency") and bool(fees.get("source_hash")) and all(
        common.finite(fees.get(k)) and fees[k] >= 0 for k in names)
    if fee_ok:
        total = spread + fees["slippage_in"] + fees["slippage_out"] + (fees["fee_in"] + fees["fee_out"]) / multiplier
        result["round_trip_cost_per_unit"] = total
        result["cost_equivalent_underlying_move"] = total / abs(delta) if greek_ok else None
        result["state"] = "COMPLETE_COST_REFERENCE" if greek_ok else "PARTIAL"
    else:
        result["reasons"].append("FEES_OR_SLIPPAGE_UNKNOWN")
    return result


def greek_scenario(greeks, *, now, underlying_change, iv_percentage_points, elapsed_calendar_days):
    """No probability, execution, or bid forecast is attached to this local expansion."""
    names = ("delta", "gamma", "vega", "theta")
    result = {"kind": "LOCAL_APPROXIMATION_NOT_EXECUTION_PRICE", "value_change": None}
    try:
        valid = (all(common.finite(greeks.get(k)) for k in names)
            and all(common.finite(v) for v in (underlying_change, iv_percentage_points, elapsed_calendar_days))
            and elapsed_calendar_days >= 0
            and greeks.get("vega_unit") == "PER_IV_PERCENTAGE_POINT"
            and greeks.get("theta_unit") == "PER_CALENDAR_DAY"
            and 0 <= (now - common.timestamp(greeks["received_at"])).total_seconds() <= 60)
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        return {**result, "reason": "GREEKS_UNITS_OR_FRESHNESS_UNVERIFIED"}
    return {**result, "value_change": greeks["delta"] * underlying_change + .5 * greeks["gamma"] * underlying_change ** 2
        + greeks["vega"] * iv_percentage_points + greeks["theta"] * elapsed_calendar_days,
        "assumptions": {"underlying_change": underlying_change, "iv_percentage_points": iv_percentage_points,
                        "elapsed_calendar_days": elapsed_calendar_days}}


def path_label(event, bars, *, ready_at, as_of, delay_seconds=60):
    if delay_seconds not in (30, 60, 120):
        raise ValueError("UNREGISTERED_REACTION_DELAY")
    result = {"kind": "FIXED_HORIZON_UNDERLYING_RESEARCH_NOT_OPTION_PNL", "delay_seconds": delay_seconds,
              "state": "MISSING", "y60_pct": None, "y60_structure_units": None, "mfe60": None, "mae60": None,
              "path_order": "PATH_ORDER_UNKNOWN", "is_realized_pnl": False}
    if event.get("state") != "NUMERIC_PASS" or not common.finite(event.get("initial_r")) or event["initial_r"] <= 0:
        return {**result, "state": "NOT_A_TECHNICAL_EVENT"}
    target = common.timestamp(ready_at) + timedelta(seconds=delay_seconds)
    # A minute that straddles the target cannot serve as a fill proxy.
    minute = target.replace(second=0, microsecond=0) + (timedelta(minutes=1) if target.second or target.microsecond else timedelta())
    deadline = common.timestamp(event["deadline_at"])
    if minute >= deadline:
        return {**result, "state": "MISSED_REFERENCE_WINDOW"}
    eligible = sorted({common.timestamp(row["open_at"]) for row in bars
        if minute <= common.timestamp(row["open_at"]) < deadline
        and common.timestamp(row["received_at"]) <= as_of})
    observation = None
    for start in eligible:
        checked = {}
        rows, missing = trend.complete_minutes(bars, symbol=event["symbol"], opening=start,
            until=start + timedelta(minutes=1), now=as_of, diagnostics=checked, price_only=True)
        if not missing:
            observation = (start, rows[0])
            break
    if observation is None:
        return {**result, "state": "REFERENCE_OBSERVATION_MISSING"}
    start, row = observation
    p0 = row["open"]
    lower, upper = event["entry_range"]
    if not lower <= p0 <= upper:
        return {**result, "state": "MISSED_REFERENCE_WINDOW", "reason": "ORIGINAL_ENTRY_RANGE_EXCEEDED"}
    end = start + timedelta(minutes=60)
    result.update(reference_time_target=target.isoformat(), reference_at=start.isoformat(), reference_price=p0,
                  proxy="PRICE_OBSERVATION_PROXY", horizon_at=end.isoformat())
    if end > common.timestamp(event["planned_exit_at"]):
        return {**result, "state": "HORIZON_TRUNCATED"}
    if end > as_of:
        return {**result, "state": "NOT_MATURE"}
    rows, missing = trend.complete_minutes(bars, symbol=event["symbol"], opening=start, until=end,
                                          now=as_of, price_only=True)
    if missing:
        return {**result, "state": "PATH_INCOMPLETE", "missing_minutes": missing}
    direction = 1 if event["right"] == "CALL" else -1
    risk = event["initial_r"]
    move = direction * (rows[-1]["close"] - p0)
    favorable = [direction * (r["high" if direction == 1 else "low"] - p0) for r in rows]
    adverse = [-direction * (r["low" if direction == 1 else "high"] - p0) for r in rows]
    breached = next((r["open_at"] for r in rows if direction * (
        r["low" if direction == 1 else "high"] - event["structure_line"]) <= 0), None)
    return {**result, "state": "COMPLETE", "y60_pct": move / p0, "y60_structure_units": move / risk,
            "mfe60": max(0, *favorable) / risk, "mae60": max(0, *adverse) / risk,
            "first_structure_touch_minute": breached, "review_below_half_r": move / risk < .5}
