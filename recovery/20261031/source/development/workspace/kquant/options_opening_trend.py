"""Opening trend/pullback research. Pure calculations, no orders or SDK calls."""
from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import options_one_minute as common
from .options_two_hour_data import sessions_before
from .market_clock import session_bounds_utc

CONFIG = Path(__file__).resolve().parents[1] / "config/options_opening_trend_v1.json"
POLICY_ID = "STRAT-OPENING-TREND-PULLBACK-5M-V1"


def load_policy() -> dict:
    p = json.loads(CONFIG.read_text(encoding="utf-8"))
    if p["policy_id"] != POLICY_ID or any(p[k] for k in (
            "qualified_publication_enabled", "paper_enabled", "automatic_paper_enabled",
            "real_orders_enabled", "llm_required")):
        raise ValueError("TREND_RESEARCH_BOUNDARY_CHANGED")
    p["policy_hash"] = common.digest(p)
    return p


def exit_times(opening: datetime, closing: datetime, entered: datetime | None = None,
               policy: dict | None = None) -> dict:
    p = policy or load_policy()
    zone = ZoneInfo(p["bedtime_timezone"])
    local_day = common.timestamp(opening).astimezone(zone).date() + timedelta(days=1)
    bedtime = datetime.combine(local_day, time.fromisoformat(p["bedtime_exit"]), zone).astimezone(UTC)
    reminder = datetime.combine(local_day, time.fromisoformat(p["bedtime_reminder"]), zone).astimezone(UTC)
    planned = min(bedtime, common.timestamp(closing) - timedelta(minutes=p["planned_exit_minutes_before_close"]))
    if entered is not None:
        planned = min(planned, common.timestamp(entered) + timedelta(minutes=p["holding_max_minutes"]))
    return {"planned_exit_at": planned.isoformat(),
            "wind_down_at": min(reminder, planned - timedelta(minutes=15)).isoformat()}


def complete_minutes(bars: list[dict], *, symbol: str, opening: datetime,
                     until: datetime, now: datetime, diagnostics: dict | None = None,
                     price_only: bool = False, source_decisions=None) -> tuple[list[dict], list[str]]:
    """Select only post-close evidence known at the requested as-of time."""
    from .options_minute_admission import classify
    by_start, rejected, versions, valid_versions, raw_versions = {}, {}, {}, {}, {}
    for b in bars:
        try:
            start = common.timestamp(b["open_at"])
            if not opening <= start < until:
                continue
            received = common.timestamp(b["received_at"])
            if received <= now:
                raw_versions.setdefault(start, []).append(b)
            _, reason = classify(b, symbol=symbol, opening=opening, until=until,
                                 now=now, price_only=price_only)
            if reason:
                if diagnostics is not None:
                    rejected.setdefault(start.isoformat(), set()).add(reason)
                continue
            if price_only:
                valid_versions.setdefault(start, []).append(b)
                interface = b.get("sdk_evidence", {}).get("interface")
                if interface:
                    versions.setdefault(start, {}).setdefault(interface, set()).add(
                        tuple(b[k] for k in ("open", "high", "low", "close")))
            old = by_start.get(start)
            if old is None or received > common.timestamp(old["received_at"]):
                by_start[start] = b
        except (ValueError, TypeError, KeyError, AttributeError):
            if diagnostics is not None:
                try:
                    malformed = common.timestamp(b["open_at"])
                    if opening <= malformed < until:
                        rejected.setdefault(malformed.isoformat(), set()).add("MINUTE_TIME_FIELDS_INVALID")
                except (ValueError, TypeError, KeyError, AttributeError):
                    pass
            continue
    if price_only:
        for start, interfaces in versions.items():
            if len(set().union(*interfaces.values())) > 1:
                from .options_minute_decisions import accepted
                decisions = []
                for decision in source_decisions or []:
                    try:
                        if (decision.get("open_at") == start.isoformat()
                                and common.timestamp(decision["known_at"]) <= now
                                and common.timestamp(decision["valid_from"]) <= now):
                            decisions.append(decision)
                    except (KeyError, TypeError, ValueError):
                        continue
                decisions.sort(key=lambda d: d.get("known_at", ""), reverse=True)
                selected = accepted(decisions[0], raw_versions[start], symbol=symbol, start=start, now=now) if decisions else None
                if selected is None:
                    by_start.pop(start, None)
                    rejected.setdefault(start.isoformat(), set()).add("SOURCE_CONFLICT")
                else:
                    by_start[start] = selected
    starts = [opening + timedelta(minutes=n) for n in range(int((until - opening).total_seconds() // 60))]
    missing = [s.isoformat() for s in starts if s not in by_start]
    if diagnostics is not None:
        diagnostics.update(state="INCOMPLETE" if missing else "COMPLETE", expected_minutes=len(starts),
                           valid_minutes=len(starts) - len(missing),
                           missing_slots=[{"open_at": stamp, "reasons": sorted(rejected.get(stamp, {"MINUTE_NOT_RECEIVED"}))}
                                          for stamp in missing])
    return [by_start[s] for s in starts if s in by_start], missing


def aggregate(bars: list[dict], minutes: int) -> list[dict]:
    """Do not emit partial groups; caller supplies session-aligned contiguous minutes."""
    result = []
    for offset in range(0, len(bars) - minutes + 1, minutes):
        rows = bars[offset:offset + minutes]
        start = common.timestamp(rows[0]["open_at"])
        if any(common.timestamp(row["open_at"]) != start + timedelta(minutes=i) for i, row in enumerate(rows)):
            continue
        result.append({"open_at": start.isoformat(), "available_at": (start + timedelta(minutes=minutes)).isoformat(),
                       "open": rows[0]["open"], "close": rows[-1]["close"],
                       "high": max(r["high"] for r in rows), "low": min(r["low"] for r in rows),
                       "turnover": sum(r["turnover"] for r in rows), "volume": sum(r["volume"] for r in rows),
                       "received_at": max(rows, key=lambda r: common.timestamp(r["received_at"]))["received_at"],
                       "minute_evidence_hashes": [common.digest(r) for r in rows]})
    return result


def _baseline(history: dict, opening: datetime, start: datetime, now: datetime,
              turnover_factor: float = 1) -> tuple[float | None, list]:
    prior = sessions_before(opening.astimezone(common.NY).date(), 20)
    if history.get("prior_sessions") != prior:
        return None, []
    slots = [(start + timedelta(minutes=i)).astimezone(common.NY).strftime("%H:%M") for i in range(5)]
    totals, hashes = [], []
    for day in prior:
        values = [history.get("slots", {}).get(day, {}).get(slot) for slot in slots]
        for row in values:
            if not isinstance(row, dict):
                return None, []
            try:
                valid = (common.finite(row.get("turnover")) and row["turnover"] >= 0
                         and row.get("adjustment") == "NoAdjust" and bool(row.get("source_hash"))
                         and common.timestamp(row["received_at"]) <= now)
            except (KeyError, ValueError, TypeError):
                valid = False
            if not valid:
                return None, []
        totals.append(sum(row["turnover"] for row in values) * turnover_factor)
        hashes.extend(row["source_hash"] for row in values)
    median = statistics.median(totals)
    return (median if median > 0 else None), hashes


def evaluate(*, symbol: str, right: str, bars: list[dict], history: dict, reference: dict,
             opening: datetime, closing: datetime, now: datetime, scope_hash: str,
             policy: dict | None = None) -> dict:
    p = policy or load_policy()
    opening, closing, now = map(common.timestamp, (opening, closing, now))
    if right not in {"CALL", "PUT"}:
        raise ValueError("INVALID_RIGHT")
    session = opening.astimezone(common.NY).date().isoformat()
    result = {"policy_id": p["policy_id"], "policy_hash": p["policy_hash"], "policy_snapshot": p,
              "scope_hash": scope_hash, "session": session, "symbol": symbol, "right": right,
              "evaluated_at": now.isoformat(), "qualified_signal": False,
              "runtime_mode": "SHADOW_RESEARCH", "paper_enabled": False, "real_orders_enabled": False,
              "event_id": common.digest([p["policy_hash"], scope_hash, session, symbol, right]),
              **exit_times(opening, closing, policy=p)}

    def finish(state: str, *reasons: str) -> dict:
        result.update(state=state, reasons=list(reasons))
        result["evaluation_id"] = common.digest([result["event_id"], result.get("bar_end"), now.isoformat(), state, reasons])
        if state == "NUMERIC_PASS":
            result["evaluation_id"] = common.digest([result["event_id"], result["confirmation_at"], state])
        return result

    cutoff = min(opening + timedelta(minutes=p["entry_window_minutes"]), closing)
    if now >= cutoff:
        return finish("ENTRY_WINDOW_CLOSED", "OPENING_ENTRY_WINDOW_CLOSED")
    elapsed = int((now - opening).total_seconds() // 300) * 5
    if elapsed < 15:
        return finish("WAIT_TREND", "WAIT_FIRST_COMPLETE_15_MINUTES")
    until = opening + timedelta(minutes=min(elapsed, p["last_confirmation_minutes"]))
    result["bar_end"] = until.isoformat()
    result["calculation_bar_end"] = until.isoformat()
    minute_check = {}
    rows, missing = complete_minutes(bars, symbol=symbol, opening=opening, until=until, now=now, diagnostics=minute_check)
    try:
        reference_valid = (reference.get("symbol") == symbol and reference.get("session") == session
                           and reference.get("volume_unit") == "SHARES" and bool(reference.get("volume_unit_evidence_hash"))
                           and reference.get("price_comparable") is True and bool(reference.get("price_basis_evidence_hash"))
                           and bool(reference.get("source_hash")) and common.timestamp(reference["received_at"]) <= now
                           and common.finite(reference.get("previous_close")) and reference["previous_close"] > 0)
    except (ValueError, TypeError, KeyError, AttributeError):
        reference_valid = False
    result["input_checks"] = {
        "current_minutes": minute_check,
        "reference": {"state": "VERIFIED" if reference_valid else "UNVERIFIED",
                      "reasons": (reference.get("reference_blockers") or ["REFERENCE_IDENTITY_OR_PROVENANCE_UNVERIFIED"]) if not reference_valid else [],
                      "volume_unit": reference.get("volume_unit", "UNKNOWN"),
                      "volume_unit_evidence_present": bool(reference.get("volume_unit_evidence_hash")),
                      "price_basis_evidence_present": bool(reference.get("price_basis_evidence_hash")),
                      "time_evidence": reference.get("time_evidence", {"state": "UNAVAILABLE"})},
        "history": {"identity_valid": history.get("symbol") == symbol and history.get("session") == session,
                    "baseline_status": "NOT_EVALUATED"}}
    if missing or not reference_valid:
        result["reference_evidence"] = reference
    if missing:
        result["missing_minutes"] = missing
        return finish("INCOMPLETE", "CONTIGUOUS_SESSION_MINUTES_MISSING")
    result["calculation_input_received_at"] = max(common.timestamp(r["received_at"]) for r in rows).isoformat()
    result["calculation_input_available_at"] = until.isoformat()
    if not reference_valid:
        result["reference_evidence"] = reference
        return finish("INCOMPLETE", "PREVIOUS_CLOSE_VOLUME_UNIT_OR_PRICE_BASIS_UNVERIFIED")
    from .options_opening_trend_reference import normalize_minutes
    try:
        rows, turnover_factor = normalize_minutes(rows, reference)
    except ValueError as exc:
        return finish("INCOMPLETE", str(exc))
    if sum(r["volume"] for r in rows) <= 0:
        return finish("INCOMPLETE", "ZERO_VWAP_DENOMINATOR")
    if history.get("symbol") != symbol or history.get("session") != session:
        return finish("INCOMPLETE", "HISTORY_IDENTITY_MISMATCH")
    five, fifteen = aggregate(rows, 5), aggregate(rows, 15)
    h0, l0 = max(r["high"] for r in rows[:10]), min(r["low"] for r in rows[:10])
    width = h0 - l0
    if width <= 0:
        return finish("INCOMPLETE", "ZERO_OPENING_RANGE")
    direction = 1 if right == "CALL" else -1
    boundary = h0 if right == "CALL" else l0

    def trend_at(index: int) -> bool:
        known = rows[:(index + 1) * 5]
        volume = sum(b["volume"] for b in known)
        if not volume:
            return False
        vwap = sum(b["turnover"] for b in known) / volume
        completed = aggregate(known, 15)
        return bool(completed and all(direction * (known[-1]["close"] - level) > 0
                    for level in (reference["previous_close"], rows[0]["open"], vwap))
                    and direction * (completed[-1]["close"] - completed[-1]["open"]) > 0)

    result["factor_evidence"] = {"opening_high": h0, "opening_low": l0, "opening_width": width,
        "day_open": rows[0]["open"], "previous_close": reference["previous_close"],
        "vwap": sum(r["turnover"] for r in rows) / sum(r["volume"] for r in rows),
        "trend_bar": fifteen[-1], "reference": reference, "price": rows[-1]["close"]}
    if not trend_at(len(five) - 1):
        return finish("NO_TRIGGER", "DAILY_TREND_CONFLICT")
    candidates, incomplete = [], False
    for i, b in enumerate(five):
        if (i + 1) * 5 not in p["breakout_end_minutes"] or not trend_at(i):
            continue
        baseline, hashes = _baseline(history, opening, common.timestamp(b["open_at"]), now, turnover_factor)
        result["input_checks"]["history"]["baseline_status"] = "EVALUATED_SLOTS_ONLY"
        result["input_checks"]["history"].setdefault("slots", []).append({
            "open_at": b["open_at"], "state": "COMPLETE" if baseline is not None else "INCOMPLETE"})
        if baseline is None:
            incomplete = True
            continue
        if direction * (b["close"] - boundary) > 0 and b["turnover"] / baseline >= p["participation_min"]:
            candidates.append((i, b, baseline, hashes))
    for index, breakout, baseline, hashes in candidates:
        for j in range(index + 1, min(index + 1 + p["retest_max_bars"], len(five))):
            pullback = five[j]
            extreme = pullback["low"] if right == "CALL" else pullback["high"]
            distance = direction * (extreme - boundary)
            if distance < -p["retest_tolerance_fraction"] * width:
                break
            if (abs(extreme - boundary) > p["retest_tolerance_fraction"] * width
                    or direction * (pullback["close"] - boundary) <= 0
                    or direction * (pullback["close"] - pullback["open"]) <= 0 or not trend_at(j)):
                continue
            risk = direction * (pullback["close"] - extreme)
            if risk <= 0:
                continue
            end = common.timestamp(pullback["available_at"])
            deadline = min(end + timedelta(seconds=p["signal_deadline_seconds"]), cutoff)
            entry = sorted([pullback["close"], pullback["close"] + direction * p["max_chase_r_fraction"] * risk])
            result.update(bar_end=end.isoformat(), deadline_at=deadline.isoformat(),
                          breakout_at=breakout["available_at"], confirmation_at=end.isoformat(),
                          entry_range=entry, structure_line=extreme, initial_r=risk, bar_evidence=pullback,
                          breakout_evidence=breakout)
            result["factor_evidence"].update(participation=breakout["turnover"] / baseline,
                history_turnover_median=baseline, history_source_hashes=hashes)
            if now >= deadline:
                return finish("EXPIRED", "ORIGINAL_DEADLINE_EXCEEDED")
            return finish("NUMERIC_PASS", "EVENT_CONTRACT_AND_EXACT_APPROVAL_REQUIRED")
    if candidates:
        result["breakout_at"] = candidates[0][1]["available_at"]
        return finish("WAIT_PULLBACK", "WAIT_SEPARATE_COMPLETE_PULLBACK_BAR")
    return finish("INCOMPLETE" if incomplete else "NO_TRIGGER",
                  "SAME_FIVE_MINUTE_HISTORY_MISSING" if incomplete else "OPENING_BREAKOUT_NOT_CONFIRMED")


def current_eligibility(evaluation: dict, *, quote: dict, now: datetime,
                        event_valid: bool, contract_valid: bool, policy_approved: bool,
                        previous_state: str | None = None, trend_evidence: dict | None = None,
                        event_decision: dict | None = None) -> dict:
    """A five-minute setup never grants five-minute-old quotes validity."""
    now = common.timestamp(now)
    reasons = []
    if previous_state in {"WITHDRAWN", "EXPIRED"}:
        return {"state": previous_state, "reasons": ["TERMINAL_QUALIFICATION"], "checked_at": now.isoformat()}
    if now >= common.timestamp(evaluation["deadline_at"]):
        return {"state": "EXPIRED", "reasons": ["ORIGINAL_DEADLINE_EXCEEDED"], "checked_at": now.isoformat()}
    warnings = []
    if event_decision is not None:
        try:
            decision_fresh = (common.timestamp(event_decision["checked_at"]) <= now
                              < common.timestamp(event_decision["valid_until"]))
        except (KeyError, TypeError, ValueError, AttributeError):
            decision_fresh = False
        if event_decision.get("decision") == "BLOCK":
            return {"state": "WITHDRAWN", "reasons": ["KNOWN_MAJOR_EVENT_IN_HOLDING_WINDOW"],
                    "checked_at": now.isoformat(), "event_decision": event_decision}
        event_valid = decision_fresh and event_decision.get("decision") in {"PASS", "WARN"}
        warnings = list(event_decision.get("warnings") or [])
        if event_decision.get("decision") == "REVIEW":
            reasons.append("IMPORTANT_EVENT_REQUIRES_REVIEW")
    try:
        fresh = (quote.get("symbol") == evaluation["symbol"] and common.finite(quote.get("last"))
                 and 0 <= (now - common.timestamp(quote["received_at"])).total_seconds() <= 3)
    except (ValueError, TypeError, KeyError):
        fresh = False
    if not fresh:
        reasons.append("UNDERLYING_QUOTE_STALE")
    else:
        price = quote["last"]
        lo, hi = evaluation["entry_range"]
        d = 1 if evaluation["right"] == "CALL" else -1
        if not lo <= price <= hi or d * (price - evaluation["structure_line"]) <= 0:
            return {"state": "WITHDRAWN", "reasons": ["PRICE_OR_TREND_INVALIDATED"], "checked_at": now.isoformat()}
    evidence = trend_evidence or {}
    try:
        opening, _ = session_bounds_utc(
            datetime.fromisoformat(evaluation['session']).date())
        until = opening + timedelta(minutes=int((now-opening).total_seconds()//60))
        valid = (all(evidence.get(k) == evaluation[k] for k in ('symbol', 'session', 'policy_hash', 'scope_hash'))
                 and common.timestamp(evidence['bar_end']) == until
                 and common.timestamp(evidence['checked_at']) <= now < common.timestamp(evidence['valid_until']))
    except (ValueError, TypeError, KeyError):
        valid = False
    if not valid or evidence.get('state') not in {'VALID', 'TREND_CONFLICT'}:
        reasons.extend(evidence.get('reasons') or ['CURRENT_TREND_EVIDENCE_UNAVAILABLE'])
    elif evidence['state'] == 'TREND_CONFLICT' or (fresh and any(
            d * (price-evidence['factors'][k]) <= 0 for k in (
                ('day_open', 'previous_close') if evaluation.get('research_strategy') == 'opening_momentum'
                else ('day_open', 'previous_close', 'vwap')))):
        return {'state': 'WITHDRAWN', 'reasons': ['CURRENT_DAILY_TREND_CONFLICT'], 'checked_at': now.isoformat()}
    for valid, reason in ((event_valid, "EVENT_COVERAGE_NOT_ELIGIBLE"),
                          (contract_valid, "CONTRACT_NOT_QUALIFIED"),
                          (policy_approved, "EXACT_POLICY_NOT_APPROVED")):
        if not valid:
            reasons.append(reason)
    return {"state": "PENDING" if reasons else "QUALIFIED", "reasons": reasons,
            "warnings": warnings, "event_decision": event_decision, "checked_at": now.isoformat()}
