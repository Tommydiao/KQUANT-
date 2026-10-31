"""Separate declared watch scope from evidence of an active session owner."""
from datetime import datetime
from .market_clock import NEW_YORK, is_trading_day, next_trading_day


def apply(payload, worker, *, now):
    day = now.astimezone(NEW_YORK).date()
    scope = worker.get("scope_hash") if worker.get("session") == day.isoformat() else None
    payload["scope_observation"] = dict(observed_at=now.isoformat(),
        declared_scope_hash=payload.get("scope_hash"), running_scope_hash=scope,
        current_market_date=day.isoformat())
    if not is_trading_day(day):
        payload["candidates"] = []
        payload["scope_observation"].update(state="NON_TRADING_DAY",
            next_session=next_trading_day(day).isoformat(), active_scope_confirmed=False)
        payload["session_state"] = "NON_TRADING_DAY"
        return payload
    if not scope or payload.get("scope_hash") != scope:
        payload["candidates"] = []
        payload.setdefault("snapshot", {}).update(state="STALE", error_type="RUNNING_SCOPE_NOT_CONFIRMED")
        payload["scope_observation"].update(state="UNCONFIRMED", active_scope_confirmed=False)
    else:
        payload["scope_observation"].update(state="CONFIRMED", active_scope_confirmed=True)
    return payload
