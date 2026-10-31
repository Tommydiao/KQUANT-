"""Bounded Longbridge-only prewarm for the independent one-minute study."""
from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from . import options_one_minute as rules
from .market_clock import session_bounds_utc
from .options_two_hour_data import classify_failure, sessions_before, universe


def seed(day: date, manifest: dict, path: Path = rules.STORE) -> None:
    rules.initialize(path)
    with sqlite3.connect(path) as connection:
        for item in manifest["items"]:
            valid = item["identity_status"] == "verified" and bool(item["provider_symbol"])
            connection.execute("INSERT OR IGNORE INTO one_minute_prewarm VALUES (?,?,?,?,?,?)", (
                day.isoformat(), item["symbol"], "PENDING" if valid else "IDENTITY_UNRESOLVED",
                None if valid else "IDENTITY_UNRESOLVED", None, rules.canonical(item)))
    with sqlite3.connect(path) as connection:
        incomplete = connection.execute("SELECT symbol FROM one_minute_prewarm WHERE session=? AND state='DATA_INSUFFICIENT'",
                                        (day.isoformat(),)).fetchall()
    for (symbol,) in incomplete:
        if _progress(symbol, day, path)["next_session"] is not None:
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE one_minute_prewarm SET state='PENDING',reason='CACHED_HISTORY_REPAIR_PENDING' WHERE session=? AND symbol=? AND state='DATA_INSUFFICIENT'",
                                   (day.isoformat(), symbol))


def required_slots(day: date, policy: dict | None = None) -> list[str]:
    policy = policy or rules.load_policy()
    opening, closing = session_bounds_utc(day)
    cutoff = closing - timedelta(minutes=policy["entry_cutoff_minutes_before_close"])
    result = []
    current = opening
    while current < cutoff:
        result.append(current.astimezone(rules.NY).strftime("%H:%M"))
        current += timedelta(minutes=1)
    return result


def history_context(symbol: str, day: date, path: Path = rules.STORE, *, slot: str | None = None) -> dict:
    prior = sessions_before(day, 20)
    slots = {session: {} for session in prior}
    with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True) as connection:
        for session, row_slot, payload_json in connection.execute(
                "SELECT session,slot,payload_json FROM one_minute_history WHERE symbol=? AND session>=? AND session<?"
                + (" AND slot=?" if slot is not None else ""),
                (symbol, prior[0], day.isoformat(), slot) if slot is not None else
                (symbol, prior[0], day.isoformat())):
            if session in slots:
                row = json.loads(payload_json)
                slots[session][row_slot] = {"turnover": row.get("turnover"),
                                        "range": row.get("range"), "source_hash": row.get("source_hash"),
                                        "adjustment": row.get("adjustment"), "received_at": row.get("received_at")}
    return {"symbol": symbol, "session": day.isoformat(), "prior_sessions": prior, "slots": slots}


def _persist_page(symbol: str, session: str, rows: list, request_at: datetime,
                  received_at: datetime, path: Path, *, repair_invalid=None) -> tuple[int, int]:
    from .stock_signals import _parse_longbridge_time
    opening, closing = session_bounds_utc(date.fromisoformat(session))
    kept = 0
    with sqlite3.connect(path) as connection:
        previous = connection.execute("SELECT state FROM one_minute_history_pages WHERE symbol=? AND session=?",
                                      (symbol, session)).fetchone()
        for raw in rows:
            opened = _parse_longbridge_time(raw.timestamp)
            if (opened is None or opened.second or opened.microsecond
                    or not opening <= opened < closing or opened + timedelta(minutes=1) > request_at):
                continue
            try:
                values = {key: float(getattr(raw, key)) if getattr(raw, key, None) is not None else None
                          for key in ("open", "high", "low", "close", "volume", "turnover")}
            except (TypeError, ValueError, OverflowError):
                continue
            if not all(rules.finite(values[key]) for key in ("open", "high", "low", "close", "turnover")):
                continue
            if (not 0 < values["low"] <= min(values["open"], values["close"])
                    <= max(values["open"], values["close"]) <= values["high"]
                    or values["turnover"] < 0
                    or (values["volume"] is not None and
                        (not rules.finite(values["volume"]) or values["volume"] < 0))):
                continue
            payload = {"symbol": symbol, "session": session,
                       "slot": opened.astimezone(rules.NY).strftime("%H:%M"),
                       "open_at": opened.isoformat(), "raw_timestamp": str(raw.timestamp),
                       "timestamp_contract": "EXISTING_SDK_NAIVE_ASIA_SHANGHAI_ADAPTER",
                       "request_at": request_at.isoformat(), "received_at": received_at.isoformat(),
                       "source": "LONGBRIDGE_HISTORY_MIN_1", "adjustment": "NoAdjust",
                       "turnover_source": "NATIVE", "currency": "USD", **values,
                       "range": values["high"] - values["low"]}
            payload["source_hash"] = rules.digest(payload)
            if repair_invalid is not None:
                previous_row = connection.execute(
                    "SELECT payload_json FROM one_minute_history WHERE symbol=? AND session=? AND slot=?",
                    (symbol, session, payload["slot"])).fetchone()
                if previous_row:
                    try:
                        valid = repair_invalid(json.loads(previous_row[0]), symbol, session,
                                               payload["slot"], received_at)
                    except (ValueError, TypeError):
                        valid = False
                    if not valid and repair_invalid(payload, symbol, session, payload["slot"], received_at):
                        # Archive both versions before changing the cache projection, never the old evaluation.
                        archive = path.parent / "history_versions"
                        archive.mkdir(parents=True, exist_ok=True)
                        for content in (previous_row[0], rules.canonical(payload)):
                            raw_bytes = content.encode("utf-8")
                            target = archive / (rules.hashlib.sha256(raw_bytes).hexdigest() + ".json")
                            if target.exists() and target.read_bytes() != raw_bytes:
                                raise ValueError("HISTORY_VERSION_ARCHIVE_CHANGED")
                            if not target.exists():
                                target.write_bytes(raw_bytes)
                        kept += connection.execute(
                            "UPDATE one_minute_history SET payload_json=? WHERE symbol=? AND session=? AND slot=? AND payload_json=?",
                            (rules.canonical(payload), symbol, session, payload["slot"], previous_row[0])).rowcount
                        continue
            kept += connection.execute("INSERT OR IGNORE INTO one_minute_history VALUES (?,?,?,?)",
                (symbol, session, payload["slot"], rules.canonical(payload))).rowcount
        count = connection.execute("SELECT COUNT(*) FROM one_minute_history WHERE symbol=? AND session=?",
                                   (symbol, session)).fetchone()[0]
        expected = int((closing - opening).total_seconds() // 60)
        partial = 0 < count < expected
        retried = previous and previous[0] in {"FETCHED", "PARTIAL_RETRY", "PARTIAL_FINAL"}
        state = ("PARTIAL_FINAL" if retried else "PARTIAL_RETRY") if partial else "FETCHED" if count else "EMPTY"
        reason = (f"NATIVE_MINUTE_SLOTS_{count}_OF_{expected}" if partial else
                  None if count else "NO_VALID_NATIVE_ONE_MINUTE_BARS")
        connection.execute("INSERT OR REPLACE INTO one_minute_history_pages VALUES (?,?,?,?,?,?,?)",
                           (symbol, session, state, request_at.isoformat(), received_at.isoformat(), count, reason))
    return kept, count


def _progress(symbol: str, day: date, path: Path) -> dict:
    prior = sessions_before(day, 20)
    required = required_slots(day)
    with sqlite3.connect(path) as connection:
        page_rows = {row[0]: (row[1], row[2]) for row in connection.execute(
            "SELECT session,state,row_count FROM one_minute_history_pages WHERE symbol=? AND session>=? AND session<?",
            (symbol, prior[0], day.isoformat()))}
        page_states = {session: row[0] for session, row in page_rows.items()}
        pages = {session for session, state in page_states.items()
                 if state in {"FETCHED", "EMPTY", "PARTIAL_RETRY", "PARTIAL_FINAL"}}
        values = {(row[0], row[1]): (row[2], row[3]) for row in connection.execute(
            """SELECT session,slot,json_extract(payload_json,'$.turnover'),json_extract(payload_json,'$.range')
               FROM one_minute_history WHERE symbol=? AND session>=? AND session<?
                 AND json_extract(payload_json,'$.adjustment')='NoAdjust'""",
            (symbol, prior[0], day.isoformat()))}
    present_slots = ready_slots = 0
    for slot in required:
        sample = [values.get((session, slot)) for session in prior]
        if any(row is None for row in sample):
            continue
        present_slots += 1
        if (all(rules.finite(v) and v >= 0 for row in sample for v in row)
                and statistics.median(row[0] for row in sample) > 0
                and statistics.median(row[1] for row in sample) > 0):
            ready_slots += 1
    missing = [session for session in prior if session not in pages]
    repairs = []
    for session in prior:
        state, count = page_rows.get(session, (None, 0))
        opening, closing = session_bounds_utc(date.fromisoformat(session))
        expected = int((closing - opening).total_seconds() // 60)
        if state == "PARTIAL_RETRY" or (state == "FETCHED" and 0 < count < expected):
            repairs.append(session)
    next_sessions = (missing[:1 if page_states.get(missing[0]) == "SINGLE_DAY_REQUIRED" else 2]
                     if missing else repairs[:1])
    return {"fetched_days": len(pages), "required_days": len(prior),
            "ready_slots": ready_slots, "required_slots": len(required),
            "present_slots": present_slots, "unusable_baseline_slots": present_slots - ready_slots,
            "partial_retry_days": len(repairs),
            "partial_final_days": sum(state == "PARTIAL_FINAL" for state in page_states.values()),
            "next_session": next_sessions[0] if next_sessions else None,
            "next_sessions": next_sessions}


def finalize_progress(symbol: str, day: date, path: Path, now: datetime) -> dict:
    progress = _progress(symbol, day, path)
    if progress["next_session"] is not None:
        return {"state": "PENDING", **progress}
    state = "READY" if progress["ready_slots"] == progress["required_slots"] else "DATA_INSUFFICIENT"
    reason = None if state == "READY" else f"NATIVE_ONE_MINUTE_SLOTS_{progress['ready_slots']}_OF_{progress['required_slots']}"
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE one_minute_prewarm SET state=?,reason=?,checked_at=? WHERE session=? AND symbol=?",
                           (state, reason, now.isoformat(), day.isoformat(), symbol))
    return {"state": state, "reason": reason, **progress}


def reconcile_cached_prewarm(day: date, path: Path = rules.STORE, *, now=None) -> dict:
    """Reconcile existing prewarm rows from local evidence; no provider requests."""
    now = now or datetime.now(UTC)
    with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT symbol,state,reason FROM one_minute_prewarm WHERE session=? ORDER BY symbol",
                                  (day.isoformat(),)).fetchall()
    result = []
    for symbol, old_state, old_reason in rows:
        if old_state == "IDENTITY_UNRESOLVED":
            result.append({"symbol": symbol, "state": old_state, "reason": old_reason})
            continue
        progress = finalize_progress(symbol, day, path, now)
        if progress["state"] == "PENDING" and old_state == "QUOTA_DEFERRED":
            progress.update(state=old_state, reason=old_reason)
        result.append({"symbol": symbol, **progress})
    return {"session": day.isoformat(), "as_of": now.isoformat(), "provider_requests": 0,
            "scope": "EXISTING_PREWARM_ROWS", "items": result,
            "counts": {state: sum(r["state"] == state for r in result) for state in sorted({r["state"] for r in result})}}


def prewarm_one(runtime, manifest: dict, day: date, *, path: Path = rules.STORE,
                now: datetime | None = None) -> dict:
    """One shared-connection history request per call, round-robin across symbols."""
    from longbridge.openapi import AdjustType, Period, TradeSessions
    now = rules.timestamp(now or datetime.now(UTC))
    with sqlite3.connect(path) as connection:
        rows = connection.execute("""SELECT symbol,payload_json,checked_at FROM one_minute_prewarm
            WHERE session=? AND state IN ('PENDING','RETRY') ORDER BY COALESCE(checked_at,''),symbol LIMIT 8""",
            (day.isoformat(),)).fetchall()
    selected = None
    for symbol, payload, checked_at in rows:
        if checked_at and now - rules.timestamp(checked_at) < timedelta(seconds=2):
            continue
        progress = _progress(symbol, day, path)
        if progress["next_session"] is None:
            state = "READY" if progress["ready_slots"] == progress["required_slots"] else "DATA_INSUFFICIENT"
            reason = None if state == "READY" else f"NATIVE_ONE_MINUTE_SLOTS_{progress['ready_slots']}_OF_{progress['required_slots']}"
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE one_minute_prewarm SET state=?,reason=?,checked_at=? WHERE session=? AND symbol=?",
                                   (state, reason, now.isoformat(), day.isoformat(), symbol))
            return {"symbol": symbol, "state": state, "reason": reason, **progress}
        selected = symbol, json.loads(payload), progress
        break
    if selected is None:
        return {"state": "NO_READY_PREWARM_REQUEST"}
    symbol, item, progress = selected
    targets = progress["next_sessions"]
    target = targets[0]
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE one_minute_prewarm SET checked_at=? WHERE session=? AND symbol=?",
                           (now.isoformat(), day.isoformat(), symbol))
    try:
        target_date = date.fromisoformat(target)
        end_date = date.fromisoformat(targets[-1])
        rows = list(runtime.history_candlesticks_by_date(item["provider_symbol"], Period.Min_1,
            AdjustType.NoAdjust, target_date, end_date, 10, trade_sessions=TradeSessions.Intraday))
        received = datetime.now(UTC)
        if len(rows) >= 1000:
            if len(targets) == 1:
                with sqlite3.connect(path) as connection:
                    connection.execute("UPDATE one_minute_prewarm SET state='DATA_INSUFFICIENT',reason=?,checked_at=? WHERE session=? AND symbol=?",
                                       ("PROVIDER_SINGLE_DAY_PAGE_AT_LIMIT", now.isoformat(), day.isoformat(), symbol))
                return {"symbol": symbol, "state": "DATA_INSUFFICIENT", "reason": "PROVIDER_SINGLE_DAY_PAGE_AT_LIMIT",
                        "session": target, "provider_rows": len(rows)}
            with sqlite3.connect(path) as connection:
                connection.execute("INSERT OR REPLACE INTO one_minute_history_pages VALUES (?,?,?,?,?,?,?)",
                    (symbol, target, "SINGLE_DAY_REQUIRED", now.isoformat(), received.isoformat(), 0,
                     "MULTIDAY_PAGE_AT_PROVIDER_LIMIT"))
            return {"symbol": symbol, "state": "RETRY", "reason": "MULTIDAY_PAGE_AT_PROVIDER_LIMIT",
                    "sessions": targets, "provider_rows": len(rows)}
        stored = [_persist_page(symbol, session, rows, now, received, path) for session in targets]
        progress_after = finalize_progress(symbol, day, path, received)
        return {"symbol": symbol, "state": "FETCHED" if any(count for _, count in stored) else "EMPTY",
                "sessions": targets, "rows_stored": sum(added for added, _ in stored), "provider_rows": len(rows),
                "coverage": progress_after}
    except Exception as exc:
        reason = classify_failure(exc)
        state = "QUOTA_DEFERRED" if reason == "PROVIDER_HISTORY_SYMBOL_QUOTA" else "RETRY"
        with sqlite3.connect(path) as connection:
            connection.execute("UPDATE one_minute_prewarm SET state=?,reason=?,checked_at=? WHERE session=? AND symbol=?",
                               (state, reason, now.isoformat(), day.isoformat(), symbol))
        return {"symbol": symbol, "state": state, "reason": reason, "session": target}
