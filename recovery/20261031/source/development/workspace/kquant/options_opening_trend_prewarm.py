"""Trend-only historical gaps, using the existing minute cache and shared SDK."""
from datetime import UTC, date, datetime, timedelta
import json
import sqlite3
import statistics

from . import options_one_minute as common
from . import options_one_minute_data as minute_data
from .bounded_sqlite import read_connection
from .market_clock import session_bounds_utc
from .options_two_hour_data import classify_failure, sessions_before


SCOPE = "OPENING_TREND_20D_0940_0950_AND_PRIOR_CLOSE"
META = "opening_trend_prewarm"
REPAIR_REQUEST = common.ROOT / "config/options_opening_trend_prewarm_request.json"


def repair_request(day, manifest, now, *, path=REPAIR_REQUEST, root=common.ROOT):
    """An expiring data-only request can start the existing owner before 08:30 ET."""
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        audit_path = (root / row["expiry_audit_path"]).resolve()
        raw = audit_path.read_bytes() if audit_path.is_relative_to(root.resolve()) else b""
        audit = json.loads(raw)
        if (row.get("session") != day.isoformat() or row.get("scope_hash") != manifest["scope_hash"]
                or not row.get("data_only") or not row.get("request_id")
                or not common.timestamp(row["not_before"]) <= now < common.timestamp(row["expires_at"])
                or audit.get("session") != day.isoformat() or audit.get("scope_hash") != manifest["scope_hash"]
                or common.hashlib.sha256(raw).hexdigest() != row["expiry_audit_sha256"]
                or type(row.get("request_limit")) is not int or not 1 <= row["request_limit"] <= 256):
            return None
        preferred = [r["symbol"] for r in audit["items"] if r.get("identity_status") == "verified"
                     and r.get("matching", {}).get("extended")]
        return {"request_id": row["request_id"], "preferred_symbols": preferred,
                "request_limit": row["request_limit"], "expires_at": row["expires_at"]}
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _valid(row, symbol, session, slot, now):
    try:
        opened = datetime.combine(date.fromisoformat(session), datetime.strptime(slot, "%H:%M").time(),
                                  common.NY).astimezone(UTC)
        return (isinstance(row, dict) and row.get("symbol") == symbol and row.get("session") == session
                and row.get("slot") == slot and common.timestamp(row["open_at"]) == opened
                and row.get("source") == "LONGBRIDGE_HISTORY_MIN_1"
                and row.get("adjustment") == "NoAdjust" and row.get("currency") == "USD"
                and row.get("turnover_source") == "NATIVE"
                and opened + timedelta(minutes=1) <= common.timestamp(row["request_at"])
                <= common.timestamp(row["received_at"]) <= now
                and all(common.finite(row.get(k)) for k in ("open", "high", "low", "close", "turnover"))
                and 0 < row["low"] <= min(row["open"], row["close"])
                <= max(row["open"], row["close"]) <= row["high"] and row["turnover"] >= 0
                and common.digest({k: v for k, v in row.items() if k != "source_hash"}) == row.get("source_hash"))
    except (ValueError, TypeError, KeyError, ArithmeticError):
        return False


def coverage(history, now):
    symbol, day = history["symbol"], date.fromisoformat(history["session"])
    prior = sessions_before(day, 20)
    slots = history.get("slots", {})
    groups, missing_days = {}, set()
    invalid_count = 0
    for start in (40, 45):
        missing, invalid, totals = [], [], []
        for session in prior:
            total = 0
            complete = True
            for minute in range(start, start + 5):
                slot = f"09:{minute:02d}"
                row = slots.get(session, {}).get(slot)
                if row is None:
                    missing.append([session, slot])
                    missing_days.add(session)
                    complete = False
                elif not _valid(row, symbol, session, slot, now):
                    invalid.append([session, slot])
                    missing_days.add(session)
                    complete = False
                else:
                    total += row["turnover"]
            if complete:
                totals.append(total)
        median = statistics.median(totals) if len(totals) == 20 else None
        state = ("INVALID_CACHED_EVIDENCE" if invalid else "MISSING_MINUTES" if missing
                 else "BASELINE_ZERO" if median <= 0 else "READY")
        groups[f"09:{start:02d}"] = {"state": state, "required_minutes": 100,
            "valid_input_minutes": 100 - len(missing) - len(invalid), "missing_minutes": len(missing),
            "invalid_minutes": len(invalid), "missing": missing, "invalid": invalid,
            "complete": state == "READY", "turnover_median": median}
        invalid_count += len(invalid)
    previous = prior[-1]
    end = session_bounds_utc(date.fromisoformat(previous))[1]
    close_slot = (end - timedelta(minutes=1)).astimezone(common.NY).strftime("%H:%M")
    anchor = history.get("prior_close_bar")
    anchor_state = ("MISSING" if anchor is None else "READY"
                    if _valid(anchor, symbol, previous, close_slot, now) else "INVALID_CACHED_EVIDENCE")
    if anchor_state != "READY":
        missing_days.add(previous)
    ready = sum(g["complete"] for g in groups.values())
    return {"scope": SCOPE, "baseline_slots": groups, "ready_baseline_groups": ready,
            "prior_close": {"session": previous, "slot": close_slot, "state": anchor_state},
            "missing_sessions": sorted(missing_days, key=lambda d: (d != previous, d)),
            "invalid_minutes": invalid_count + int(anchor_state == "INVALID_CACHED_EVIDENCE"),
            "inputs_ready": ready == 2 and anchor_state == "READY",
            "full_rule_calculation_ready": False}


def history_context(symbol, day, path, now):
    prior = sessions_before(day, 20)
    result = {"symbol": symbol, "session": day.isoformat(), "prior_sessions": prior,
              "slots": {d: {} for d in prior}}
    end = session_bounds_utc(date.fromisoformat(prior[-1]))[1]
    close_slot = (end - timedelta(minutes=1)).astimezone(common.NY).strftime("%H:%M")
    with read_connection(path, seconds=.5) as db:
        for d, slot, raw in db.execute("""SELECT session,slot,payload_json FROM one_minute_history
            WHERE symbol=? AND session>=? AND session<? AND slot>=? AND slot<?""",
            (symbol, prior[0], day.isoformat(), "09:40", "09:50")):
            if d in result["slots"]:
                result["slots"][d][slot] = json.loads(raw)
        row = db.execute("SELECT payload_json FROM one_minute_history WHERE symbol=? AND session=? AND slot=?",
                         (symbol, prior[-1], close_slot)).fetchone()
        result["prior_close_bar"] = json.loads(row[0]) if row else None
    result["input_coverage"] = coverage(result, now)
    # Keep invalid immutable evidence in the DB, but never feed it to the rule model.
    for session, slots in result["slots"].items():
        result["slots"][session] = {slot: row for slot, row in slots.items()
                                   if _valid(row, symbol, session, slot, now)}
    if result["input_coverage"]["prior_close"]["state"] != "READY":
        result["prior_close_bar"] = None
    return result


def _record(path, symbol, day, now, metadata, *, quota=False):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=.1) as db:
        old = db.execute("SELECT payload_json FROM one_minute_prewarm WHERE session=? AND symbol=?",
                         (day.isoformat(), symbol)).fetchone()
        previous = json.loads(old[0]).get(META, {}) if old else {}
        metadata = {**previous, **metadata}
        db.execute("""UPDATE one_minute_prewarm SET checked_at=?,
            payload_json=json_set(payload_json, '$.opening_trend_prewarm', json(?))
            WHERE session=? AND symbol=?""",
            (now.isoformat(), common.canonical(metadata), day.isoformat(), symbol))
        if quota:
            db.execute("UPDATE one_minute_prewarm SET state='QUOTA_DEFERRED',reason=? WHERE session=? AND symbol=?",
                       (metadata["reason"], day.isoformat(), symbol))
        elif metadata.get("quota_month_probe"):
            db.execute("UPDATE one_minute_prewarm SET state='PENDING',reason='NEW_MONTH_QUOTA_PROBE' WHERE session=? AND symbol=? AND state='QUOTA_DEFERRED'",
                       (day.isoformat(), symbol))


def _summary(quality):
    return {"scope": SCOPE, "ready_baseline_groups": quality["ready_baseline_groups"],
            "prior_close_state": quality["prior_close"]["state"], "inputs_ready": quality["inputs_ready"],
            "missing_sessions": quality["missing_sessions"], "invalid_minutes": quality["invalid_minutes"]}


def prewarm_one(runtime, manifest, day, *, path=common.STORE, now=None, clock=None,
                preferred_symbols=(), request_limit=256):
    """At most one day request; legacy READY still means the old full-day scope."""
    from longbridge.openapi import AdjustType, Period, TradeSessions
    now = common.timestamp(now or datetime.now(UTC))
    clock = clock or (lambda: datetime.now(UTC))
    items = {r["symbol"]: r for r in manifest["items"]
             if r["identity_status"] == "verified" and r.get("provider_symbol")}
    with read_connection(path, seconds=.5) as db:
        jobs = db.execute("""SELECT symbol,state,payload_json,checked_at FROM one_minute_prewarm
            WHERE session=? AND state!='IDENTITY_UNRESOLVED'
            ORDER BY COALESCE(checked_at,''),symbol""", (day.isoformat(),)).fetchall()
    total_requests = sum(sum(a.get("count", 0) for a in json.loads(raw).get(META, {}).get("attempts", {}).values())
                         for _, _, raw, _ in jobs)
    if total_requests >= request_limit:
        return {"scope": SCOPE, "state": "LOCAL_REQUEST_BUDGET", "session": day.isoformat(),
                "provider_requests": 0, "requests_used": total_requests, "request_limit": request_limit}
    # Three preferred turns, then one full-universe turn. Last-check order survives restart.
    if preferred_symbols and total_requests % 4 != 3:
        preferred = set(preferred_symbols)
        jobs.sort(key=lambda row: row[0] not in preferred)
    checked = 0
    month = now.astimezone(common.NY).strftime("%Y-%m")
    for symbol, legacy_state, raw, checked_at in jobs:
        if symbol not in items:
            continue
        checked += 1
        try:
            metadata = json.loads(raw).get(META, {})
            if legacy_state == "QUOTA_DEFERRED":
                previous_month = metadata.get("quota_month") or str(checked_at or day.isoformat())[:7]
                if previous_month >= month:
                    checked -= 1
                    continue
                metadata.update(quota_month_probe=True, quota_previous_month=previous_month)
                _record(path, symbol, day, now, metadata)
            retry_at = metadata.get("retry_at")
            if retry_at and now < common.timestamp(retry_at) and not metadata.get("quota_month_probe"):
                checked -= 1
                continue
            quality = history_context(symbol, day, path, now)["input_coverage"]
        except (sqlite3.Error, TimeoutError, ValueError, TypeError, AttributeError) as exc:
            _record(path, symbol, day, now, {"state": "READ_UNAVAILABLE", "error_type": type(exc).__name__,
                    "checked_at": now.isoformat(), "retry_at": (now + timedelta(seconds=60)).isoformat()})
            if checked >= 8:
                break
            continue
        attempts = metadata.get("attempts", {})
        targets = [d for d in quality["missing_sessions"] if attempts.get(d, {}).get("count", 0) < 3]
        if not targets:
            state = ("INPUTS_READY" if quality["inputs_ready"] else "INVALID_CACHED_EVIDENCE"
                     if quality["invalid_minutes"] else "DATA_INSUFFICIENT")
            metadata = {"state": state, "checked_at": now.isoformat(),
                        "retry_at": (now + timedelta(seconds=60)).isoformat(), "coverage": _summary(quality),
                        "blocked_sessions": quality["missing_sessions"]}
            _record(path, symbol, day, now, metadata)
            if checked >= 8:
                break
            continue
        target = targets[0]
        attempts = {**attempts, target: {"count": attempts.get(target, {}).get("count", 0) + 1,
                                       "requested_at": now.isoformat()}}
        metadata = {"state": "REQUESTING", "target_session": target, "checked_at": now.isoformat(),
                    "attempts": attempts, "quota_month_probe": False,
                    "retry_at": (now + timedelta(seconds=20)).isoformat(), "coverage": _summary(quality)}
        _record(path, symbol, day, now, metadata)
        try:
            target_date = date.fromisoformat(target)
            rows = list(runtime.history_candlesticks_by_date(items[symbol]["provider_symbol"], Period.Min_1,
                AdjustType.NoAdjust, target_date, target_date, 10, trade_sessions=TradeSessions.Intraday))
            received = common.timestamp(clock())
            if len(rows) >= 1000:
                with sqlite3.connect(path.resolve().as_uri() + "?mode=rw", uri=True, timeout=.1) as db:
                    db.execute("INSERT OR REPLACE INTO one_minute_history_pages VALUES (?,?,?,?,?,?,?)",
                        (symbol, target, "PARTIAL_FINAL", now.isoformat(), received.isoformat(), 0,
                         "PROVIDER_SINGLE_DAY_PAGE_AT_LIMIT"))
                state, stored = "DATA_INSUFFICIENT", 0
            else:
                stored, count = minute_data._persist_page(symbol, target, rows, now, received, path,
                                                          repair_invalid=_valid)
                state = "FETCHED" if count else "EMPTY"
            after = history_context(symbol, day, path, received)["input_coverage"]
            missing_target = target in after["missing_sessions"]
            metadata = {"state": state, "target_session": target, "checked_at": received.isoformat(),
                        "retry_at": (received + timedelta(seconds=60 if missing_target else 2)).isoformat(),
                        "coverage": _summary(after), "quota_month": None,
                        "last_provider_success_at": received.isoformat()}
            _record(path, symbol, day, received, metadata)
            return {"scope": SCOPE, "symbol": symbol, "session": day.isoformat(), "state": state, "sessions": [target],
                    "provider_requests": 1, "rows_stored": stored, "provider_rows": len(rows),
                    "coverage": _summary(after), "legacy_state_preserved": legacy_state}
        except Exception as exc:
            reason = classify_failure(exc)
            quota = reason == "PROVIDER_HISTORY_SYMBOL_QUOTA"
            metadata = {"state": "QUOTA_DEFERRED" if quota else "RETRY", "reason": reason,
                "quota_month": month if quota else None,
                "target_session": target, "checked_at": now.isoformat(),
                "retry_at": (now + timedelta(seconds=300 if reason in {"PROVIDER_RATE_LIMIT", "SDK_THROTTLE"}
                                              else 60)).isoformat(), "coverage": _summary(quality)}
            _record(path, symbol, day, now, metadata, quota=quota)
            return {"scope": SCOPE, "symbol": symbol, "session": day.isoformat(), **metadata, "provider_requests": 1}
    return {"scope": SCOPE, "session": day.isoformat(), "state": "NO_READY_PREWARM_REQUEST", "checked_symbols": checked,
            "provider_requests": 0}
