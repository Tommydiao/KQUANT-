"""Pure research measurements; no signals, ledger writes, or policy mutation."""
from __future__ import annotations

import math
import hashlib
import json
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
VERSION = "opening-turnover-v0.2"


def factor_funnel(snapshot):
    """Pure pre-filter research classification; preserve unknown and failed rows."""
    def finite(name):
        value = snapshot.get(name)
        try:
            return float(value) if value is not None and not isinstance(value, bool) and math.isfinite(float(value)) else None
        except (ValueError, TypeError):
            return None
    def check(names, predicate):
        values = [finite(k) for k in names]
        return 'UNKNOWN' if any(v is None for v in values) else ('PASS' if predicate(*values) else 'FAIL')
    def conjunction(*states):
        return 'FAIL' if 'FAIL' in states else ('UNKNOWN' if 'UNKNOWN' in states else 'PASS')
    right = snapshot.get('right')
    price = market = 'UNKNOWN'
    if right == 'CALL':
        price = check(['first_5m_close','second_5m_close','prior_range_high'], lambda a,b,r: a>r and b>r)
        market = check(['spy_prior_close','spy_ema50'], lambda p,m: p>=m)
    elif right == 'PUT':
        price = check(['first_5m_close','second_5m_close','prior_range_low'], lambda a,b,r: a<r and b<r)
        market = check(['spy_prior_close','spy_ema20'], lambda p,m: p<m)
    compression = check(['compression_ratio'], lambda v: 0<=v<=.8)
    participation = check(['opening_participation'], lambda v: v>=1.5)
    base = conjunction(price,market)
    f1 = conjunction(base,compression)
    key = [snapshot.get('symbol'),right,snapshot.get('market_session_date')]
    return {'economic_event_id': hashlib.sha256(json.dumps(key).encode()).hexdigest(),
            'population': 'BASE_PRICE_BREAKOUT', 'price': price, 'market': market,
            'compression': {'value':finite('compression_ratio'),'threshold':.8,'state':compression},
            'participation': {'value':finite('opening_participation'),'threshold':1.5,'state':participation},
            'F0':base,'F1':f1,'F2':conjunction(f1,participation),
            'event_coverage':snapshot.get('event_status','UNKNOWN'), 'contract':'NOT_EVALUATED','capital':'NOT_EVALUATED',
            'not_a_signal':True, 'production_consumption':False}


def opening_participation(rows, *, session, prior_sessions, as_of, symbol):
    """Caller supplies the preceding 20 sessions from the product calendar.

    Rows must carry native turnover, currency, and a genuine availability time.
    Missing sessions are never replaced with older dates or synthetic bars.
    """
    now = datetime.fromisoformat(as_of)
    if now.tzinfo is None:
        raise ValueError("AS_OF_TIMEZONE_REQUIRED")
    dates = list(prior_sessions)
    result = {"formula_version": VERSION, "symbol": symbol, "session": session,
              "value": None, "status": "PARTIAL_HISTORY", "missing": [],
              "daily_turnover": {}, "baseline": None, "as_of": as_of}
    if len(dates) != 20 or len(set(dates)) != 20 or dates != sorted(dates) or any(d >= session for d in dates):
        result["missing"] = ["EXACT_PRECEDING_20_CALENDAR_SESSIONS_REQUIRED"]
        return result
    buckets = {}
    conflicts = set()
    for row in rows:
        if row.get("symbol") != symbol:
            continue
        try:
            opened = datetime.fromisoformat(row["open_time"])
            available = datetime.fromisoformat(row["available_at"])
            if opened.tzinfo is None or available.tzinfo is None:
                continue
            local = opened.astimezone(NY)
            key = (local.date().isoformat(), local.strftime("%H:%M"))
            if key[0] not in dates + [session] or key[1] not in {"09:30", "09:35"}:
                continue
            if local.second or local.microsecond or row.get("interval") != "5m":
                continue
            if available > now or available < opened + timedelta(minutes=5):
                continue
            if row.get("turnover_source") != "NATIVE" or row.get("currency") != "USD":
                continue
            amount = float(row["turnover"])
            if not math.isfinite(amount) or amount < 0:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        if key in buckets and buckets[key] != amount:
            conflicts.add(key)
        buckets[key] = amount
    for day in dates + [session]:
        keys = [(day, "09:30"), (day, "09:35")]
        if any(key not in buckets or key in conflicts for key in keys):
            result["missing"].append(day)
        else:
            result["daily_turnover"][day] = sum(buckets[key] for key in keys)
    if result["missing"]:
        result["status"] = "CONFLICTED" if conflicts else "PARTIAL_HISTORY"
        return result
    baseline = statistics.median(result["daily_turnover"][day] for day in dates)
    result["baseline"] = baseline
    if baseline == 0:
        result["status"] = "ZERO_BASELINE"
        return result
    result.update(status="AVAILABLE", value=result["daily_turnover"][session] / baseline)
    return result


def conditional_features(*, compression, participation, spot, breakout, atr, regular_open, previous_close, right):
    if right not in {"CALL", "PUT"}:
        raise ValueError("INVALID_RIGHT")
    values = [compression, participation, spot, breakout, atr, regular_open, previous_close]
    if any(v is None or not math.isfinite(float(v)) for v in values) or participation <= 0 or atr <= 0:
        return {"status": "MISSING_OR_INVALID_FEATURE", "values": None}
    direction = 1 if right == "CALL" else -1
    return {"status": "AVAILABLE", "values": {"C": compression, "V_log": math.log(participation),
            "B": direction * (spot - breakout) / atr,
            "G": direction * (regular_open - previous_close) / atr},
            "target_kind": "UNDERLYING_PROXY_NOT_OPTION_PNL", "production_consumption": False}
