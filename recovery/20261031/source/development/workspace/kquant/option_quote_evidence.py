"""Display evidence only; this module never grants fill or strategy eligibility."""
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from .market_clock import is_trading_day, session_bounds_utc


def contract_validity(row, *, now=None):
    now = now or datetime.now(UTC)
    status = str(row.get("trade_status") or "").rsplit(".", 1)[-1].lower()
    if status in {"expired", "halted", "suspended", "suspend"}:
        return status.upper()
    try:
        expiry = date.fromisoformat(row["expiry_date"])
    except (KeyError, TypeError, ValueError):
        return "IDENTITY_INCOMPLETE"
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    if expiry < today:
        return "EXPIRED"
    if expiry == today:
        if not is_trading_day(expiry):
            return "EXPIRY_SESSION_UNKNOWN"
        # Conservative for stock options; no unsupported 16:15 extension is assumed.
        if now >= session_bounds_utc(expiry)[1]:
            return "EXPIRY_SESSION_ENDED"
    return "UNEXPIRED" if status == "normal" else "TRADE_STATUS_UNKNOWN"


def book_fields(*, bid, ask, bid_size, ask_size, received_at, status="available"):
    valid = status == "available" and bid is not None and ask is not None and 0 <= bid <= ask
    return {"bid": bid if valid else None, "ask": ask if valid else None,
            "bid_size": bid_size if valid else None, "ask_size": ask_size if valid else None,
            "bbo_snapshot": True, "bbo_observed_at": received_at,
            "bbo_received_at": received_at if valid else None, "bbo_event_time": None,
            "depth_status": "available" if valid else status if status != "available" else "unavailable",
            "field_times": {key: {"received_at": received_at if valid else None, "native_at": None}
                            for key in ("bid", "ask", "bid_size", "ask_size")}}


def classify_stream(events, valid_contracts):
    counts = dict.fromkeys(("ready", "underlying", "quote", "depth", "valid_bilateral_depth", "depth_with_sizes", "other"), 0)
    for event in events:
        kind = event.get("kind", "ready" if event.get("stream") else "other")
        counts[kind if kind in counts else "other"] += 1
        row = event.get("payload", {})
        if kind != "depth" or event.get("contract_symbol") not in valid_contracts:
            continue
        bid, ask = row.get("bid"), row.get("ask")
        if row.get("depth_status") == "available" and bid is not None and ask is not None and 0 < bid <= ask:
            counts["valid_bilateral_depth"] += 1
            if all(row.get(key) is not None and row[key] > 0 for key in ("bid_size", "ask_size")):
                counts["depth_with_sizes"] += 1
    return counts
