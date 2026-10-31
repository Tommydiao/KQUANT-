"""Five-minute structure and fixed bedtime reviews for reported positions."""
from datetime import timedelta

from . import options_one_minute as common
from . import options_opening_trend as trend
from .market_clock import session_bounds_utc


def exit_reasons(position, bars, *, now, underlying_quote=None, monitor_updates=None):
    now = common.timestamp(now)
    if position.get("open_quantity", 0) <= 0:
        return []
    p = position["policy_snapshot"]
    if common.digest({k: v for k, v in p.items() if k != "policy_hash"}) != position["strategy_hash"]:
        return [{"reason": "POSITION_POLICY_HASH_MISMATCH", "at": now.isoformat()}]
    entered = common.timestamp(position["reported_execution_at"])
    day = entered.astimezone(common.NY).date()
    opening, closing = session_bounds_utc(day)
    times = trend.exit_times(opening, closing, entered, p)
    result = []
    if now >= common.timestamp(times["wind_down_at"]):
        result.append({"reason": "BEDTIME_WIND_DOWN_REVIEW", "at": now.isoformat(), **times})
    if now >= common.timestamp(times["planned_exit_at"]):
        result.append({"reason": "MAX_HOLD_OR_BEDTIME_EXIT", "at": now.isoformat(), **times})
    if now.astimezone(common.NY).date() > day:
        return result + [{"reason": "UNCONFIRMED_OVERNIGHT_POSITION", "at": now.isoformat()}]
    # Align to market bars, but never let a pre-entry completed group move a stop.
    groups = {}
    for b in bars:
        try:
            start = common.timestamp(b["open_at"])
            end = start + timedelta(minutes=1)
            if (b.get("symbol") != position["symbol"] or b.get("interval") != "1m" or not b.get("closed")
                    or not opening <= start < closing or start.second or start.microsecond
                    or common.timestamp(b["available_at"]) != end
                    or not end <= common.timestamp(b["received_at"]) <= now
                    or not all(common.finite(b.get(k)) for k in ("open", "high", "low", "close"))
                    or not 0 < b["low"] <= min(b["open"], b["close"]) <= max(b["open"], b["close"]) <= b["high"]):
                continue
            group = opening + timedelta(minutes=int((start - opening).total_seconds() // 300) * 5)
            old = groups.setdefault(group, {}).get(start)
            if old is None or common.timestamp(b["received_at"]) > common.timestamp(old["received_at"]):
                groups[group][start] = b
        except (KeyError, ValueError, TypeError):
            continue
    completed = []
    for start, rows in sorted(groups.items()):
        expected = [start + timedelta(minutes=i) for i in range(5)]
        if any(t not in rows for t in expected) or start + timedelta(minutes=5) <= entered:
            continue
        completed.append({"end": start + timedelta(minutes=5), "close": rows[expected[-1]]["close"],
                          "low": min(b["low"] for b in rows.values()), "high": max(b["high"] for b in rows.values())})
    latest = completed[-1] if completed else None
    fresh = latest is not None and timedelta(0) <= now - latest["end"] <= timedelta(minutes=6)
    if not fresh:
        result.append({"reason": "UNDERLYING_BAR_STALE_EXIT_UNVERIFIED", "at": now.isoformat()})
    d = 1 if position["right"] == "CALL" else -1
    entry = position.get("underlying_entry_price")
    line = position.get("trigger_low" if d == 1 else "trigger_high")
    risk = d * (entry - line) if common.finite(entry) and common.finite(line) else None
    if risk is None or risk <= 0:
        return result + [{"reason": "STRUCTURE_R_UNAVAILABLE", "at": now.isoformat()}]
    saved = position.get("trend_monitor") or {}
    initial_line = line
    if common.finite(saved.get("structure_line")):
        line = max(line, saved["structure_line"]) if d == 1 else min(line, saved["structure_line"])
    activated = common.timestamp(saved["activated_at"]) if saved.get("activated_at") else None
    previous = None
    for b in completed:
        # Check the old line first; new trailing levels only affect later bars.
        if fresh and b is latest and d * (b["close"] - line) < 0:
            result.append({"reason": "FIVE_MINUTE_STRUCTURE_BREAK", "at": b["end"].isoformat(),
                           "line": line, "close": b["close"], "r": risk})
        if activated is not None and previous and previous["end"] - timedelta(minutes=5) >= activated and b["end"] - previous["end"] == timedelta(minutes=5):
            line = max(line, min(previous["low"], b["low"])) if d == 1 else min(line, max(previous["high"], b["high"]))
        if activated is None and d * (b["close"] - entry) >= risk:
            activated = b["end"]
        previous = b
    if fresh and now >= entered + timedelta(minutes=p["holding_review_minutes"]) and d * (latest["close"] - entry) < .5 * risk:
        result.append({"reason": "SIXTY_MINUTE_PROGRESS_BELOW_HALF_R", "at": now.isoformat(), "r": risk})
    try:
        q = underlying_quote or {}
        quote_valid = (q.get("symbol") == position["symbol"] and common.finite(q.get("last"))
                       and 0 <= (now - common.timestamp(q["received_at"])).total_seconds() <= 3)
    except (KeyError, ValueError, TypeError):
        quote_valid = False
    if not quote_valid:
        result.append({"reason": "UNDERLYING_QUOTE_STALE_TOUCH_UNVERIFIED", "at": now.isoformat()})
    elif d * (q["last"] - line) <= 0:
        result.append({"reason": "STRUCTURE_TOUCH_RISK", "at": now.isoformat(), "line": line,
                       "initial_line": initial_line, "last": q["last"], "r": risk})
    if quote_valid and activated is None and d * (q["last"] - entry) >= risk:
        activated = common.timestamp(q["received_at"])
    updated = {"activated_at": activated.isoformat() if activated else None, "structure_line": line}
    if monitor_updates is not None and any(updated[k] != saved.get(k) for k in updated):
        monitor_updates.append({**updated, "checked_at": now.isoformat(),
                                "policy_hash": position["strategy_hash"]})
    return result
