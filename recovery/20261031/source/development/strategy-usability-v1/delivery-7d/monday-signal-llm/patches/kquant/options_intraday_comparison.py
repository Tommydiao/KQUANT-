"""S1 research on the same admitted snapshot. Never publishes or approves a claim."""
from copy import deepcopy
from datetime import timedelta

from . import options_one_minute as common
from . import options_opening_momentum as s0
from . import options_opening_trend as trend

POLICY_ID = "STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1"
METHOD_ID = "SAME_SESSION_NATIVE_PRICE_RESEARCH_V1"


def independent_reference(reference, builder, **kwargs):
    """A failed cross-day lookup must not erase captured same-day identity facts."""
    import sqlite3
    try:
        return builder(reference.get("raw_quote", {}), **kwargs)
    except (OSError, sqlite3.Error, ValueError) as exc:
        return {"contract_version": "PRICE_REFERENCE_BUILD_UNAVAILABLE",
            "raw_quote": deepcopy(reference.get("raw_quote", {})), "previous_close": None,
            "reference_blockers": list(dict.fromkeys([
                *reference.get("reference_blockers", []), "PRICE_REFERENCE_BUILD_FAILED"])),
            "reference_build_error": type(exc).__name__, "strict_cross_day_reference": "UNAVAILABLE"}


def load_policy():
    baseline = s0.load_policy()
    policy = {k: deepcopy(v) for k, v in baseline.items() if k != "policy_hash"}
    policy.update(policy_id=POLICY_ID, inherited_policy_hash=baseline["policy_hash"],
                  require_previous_close_direction=False, research_only=True)
    policy["policy_hash"] = common.digest(policy)
    return policy


def intraday_contract(reference, rows, *, symbol, session, now):
    """Validate native same-day evidence; never manufacture a cross-day reference."""
    quote = reference.get("raw_quote", {})
    native = quote.get("currency_evidence", {})
    checks = {}
    checks["identity_currency"] = bool(
        quote.get("symbol") == symbol and native.get("symbol") == symbol
        and native.get("provider_symbol") and quote.get("currency") == native.get("currency") == "USD"
        and native.get("source") == "LONGBRIDGE_SECURITY_STATIC_INFO"
        and native.get("source_hash") == common.digest({k: v for k, v in native.items() if k != "source_hash"}))
    try:
        acquired = common.timestamp(native["received_at"])
        checks["identity_currency"] &= acquired <= now < acquired + timedelta(days=7)
    except (KeyError, TypeError, ValueError):
        checks["identity_currency"] = False
    checks["same_session"] = bool(rows) and all(
        common.timestamp(row["open_at"]).astimezone(common.NY).date().isoformat() == session for row in rows)
    checks["native_price_basis"] = bool(rows) and all(
        row.get("sdk_evidence", {}).get("provider_symbol") == native.get("provider_symbol")
        and row.get("sdk_evidence", {}).get("adjustment") == "NoAdjust"
        and row.get("sdk_evidence", {}).get("interface") in {
            "QuoteContext.candlesticks", "QuoteContext.history_candlesticks_by_offset"}
        for row in rows)
    # Known same-day interpretation risks cannot disappear with the previous-close gate.
    checks["known_intraday_risk"] = not any(
        value in {"INTRADAY_PRICE_SCALE_CONFLICT", "SECURITY_HALTED", "INTRADAY_CORPORATE_ACTION_REVIEW"}
        for value in reference.get("reference_blockers", []))
    checks["session_open"] = bool(rows) and common.finite(rows[0].get("open")) and rows[0]["open"] > 0
    return {"method_id": METHOD_ID, "state": "VERIFIED" if all(checks.values()) else "INCOMPLETE",
            "checks": {key: "PASS" if ok else "UNKNOWN" for key, ok in checks.items()},
            "reasons": ["INTRADAY_" + key.upper() + "_UNVERIFIED" for key, ok in checks.items() if not ok],
            "currency_source_hash": native.get("source_hash"),
            "minute_hashes": [common.digest(row) for row in rows],
            "previous_close": "NOT_REQUIRED", "strict_cross_day_reference": "NOT_CLAIMED"}


def amplitude(bar, session_open):
    valid = common.finite(session_open) and session_open > 0
    return {"role": "DIAGNOSTIC_ONLY", "range_bps": 10000 * (bar["high"] - bar["low"]) / session_open if valid else None,
            "body_bps": 10000 * abs(bar["close"] - bar["open"]) / session_open if valid else None,
            "range_vs_same_slot_median": None, "same_slot_support": 0,
            "range_vs_prior_atr": None, "atr_support": 0,
            "auxiliary_reasons": ["COMPARABLE_SAME_SLOT_RANGES_UNAVAILABLE", "PRIOR_ATR_UNAVAILABLE"]}


def evaluate_s1(*, symbol, right, rows, missing, minute_check, reference, opening, closing,
                now, checkpoint, scope_hash, policy=None, _prepared=None):
    p = policy or load_policy()
    session = opening.astimezone(common.NY).date().isoformat()
    cutoff = min(opening + timedelta(minutes=p["entry_window_minutes"]), closing)
    end = checkpoint
    result = dict(policy_id=p["policy_id"], policy_hash=p["policy_hash"], policy_snapshot=p,
        data_method_id=METHOD_ID, symbol=symbol, right=right, session=session, scope_hash=scope_hash,
        evaluated_at=now.isoformat(), calculation_bar_end=end.isoformat(),
        qualified_signal=False, research_only=True, conditions={"previous_close_direction": "NOT_REQUIRED"},
        event_id=common.digest([p["policy_hash"], scope_hash, session, symbol, right]),
        **trend.exit_times(opening, closing, policy=p))

    def finish(state, *reasons):
        result.update(state=state, reasons=list(reasons))
        result["evaluation_id"] = common.digest([result["event_id"], end.isoformat(),
            result.get("input_snapshot_hash"), state, list(reasons)])
        return result

    if (end - opening).total_seconds() / 60 not in p["checkpoint_minutes"] or end > now:
        return finish("WAIT_TREND", "WAIT_FIRST_COMPLETE_FIVE_MINUTES")
    result["deadline_at"] = min(end + timedelta(seconds=p["signal_deadline_seconds"]), cutoff).isoformat()
    result["input_checks"] = {"current_minutes": minute_check}
    if missing:
        result["missing_minutes"] = missing
        return finish("INCOMPLETE", "SOURCE_CONFLICT" if any("SOURCE_CONFLICT" in row["reasons"]
            for row in minute_check.get("missing_slots", [])) else "CONTIGUOUS_SESSION_MINUTES_MISSING")
    evidence = deepcopy(_prepared[0]) if _prepared is not None else intraday_contract(
        reference, rows, symbol=symbol, session=session, now=now)
    result["input_checks"]["intraday"] = evidence
    result["input_snapshot_hash"] = _prepared[1] if _prepared is not None else common.digest([evidence, rows])
    groups = _prepared[2] if _prepared is not None else s0.price_aggregate(rows)
    bar = groups[-1]
    width = bar["high"] - bar["low"]
    if width <= 0:
        return finish("INCOMPLETE", "ZERO_BAR_RANGE")
    m, q = (bar["close"] - bar["open"]) / width, (bar["close"] - bar["low"]) / width
    direction = 1 if right == "CALL" else -1
    prior = groups[:-1]
    boundary = (max(b["high"] for b in prior) if direction == 1 else min(b["low"] for b in prior)) if prior else None
    checks = {"session_direction": direction * (bar["close"] - rows[0]["open"]) > 0,
        "momentum": direction * m >= p["momentum_min"],
        "close_position": q >= p["close_position_min"] if direction == 1 else q <= 1 - p["close_position_min"],
        "prior_breakout": boundary is None or direction * (bar["close"] - boundary) > 0}
    result["conditions"].update({key: "PASS" if ok else "FAIL" for key, ok in checks.items()})
    result["factor_evidence"] = dict(momentum=m, close_position=q, day_open=rows[0]["open"],
        price=bar["close"], previous_close=None, prior_boundary=boundary, checks=checks,
        reference={"raw_quote": {key: deepcopy(reference.get("raw_quote", {}).get(key))
            for key in ("symbol", "currency", "currency_evidence")},
            "reference_blockers": deepcopy(reference.get("reference_blockers", []))},
        state="FULL_INTRADAY_RESEARCH" if evidence["state"] == "VERIFIED" else "PARTIAL")
    result["bar_evidence"] = bar
    result["amplitude"] = amplitude(bar, rows[0]["open"])
    if evidence["state"] != "VERIFIED":
        result["known_false_partial"] = not all(checks.values())
        return finish("INCOMPLETE", *evidence["reasons"])
    if not all(checks.values()):
        return finish("NO_TRIGGER", *["MOMENTUM_" + key.upper() + "_NOT_MET" for key, ok in checks.items() if not ok])
    structure = bar["low"] if direction == 1 else bar["high"]
    risk = direction * (bar["close"] - structure)
    if risk <= 0:
        return finish("INCOMPLETE", "STRUCTURE_R_UNAVAILABLE")
    result.update(confirmation_at=end.isoformat(), structure_line=structure, initial_r=risk,
        entry_range=sorted([bar["close"], bar["close"] + direction * p["max_chase_r_fraction"] * risk]))
    return finish("EXPIRED", "ORIGINAL_DEADLINE_EXCEEDED") if now >= common.timestamp(result["deadline_at"]) else finish(
        "NUMERIC_PASS", "RESEARCH_CANDIDATE_NOT_QUALIFIED_ENTRY")


def evaluate_comparison_pair(**arguments):
    """One admission and snapshot for both directions and versions; original S0 is untouched."""
    opening, closing, now = map(common.timestamp, (arguments["opening"], arguments["closing"], arguments["now"]))
    end = common.timestamp(arguments["checkpoint"]) if arguments.get("checkpoint") else opening + timedelta(
        minutes=int((now - opening).total_seconds() // 300) * 5)
    check = {}
    rows, missing = trend.complete_minutes(arguments["bars"], symbol=arguments["symbol"], opening=opening,
        until=end, now=now, diagnostics=check, price_only=True, source_decisions=arguments.get("source_decisions"))
    valid = s0.price_reference_valid(arguments["reference"], arguments["symbol"],
                                    opening.astimezone(common.NY).date().isoformat(), now)
    prepared = rows, missing, check, valid, s0.price_aggregate(rows) if not missing else []
    # This preparation belongs only to this admitted input generation. S0 validity
    # is deliberately not a prerequisite for independent same-session S1 evidence.
    s1_prepared = None
    if not missing and rows:
        evidence = intraday_contract(arguments["reference"], rows, symbol=arguments["symbol"],
            session=opening.astimezone(common.NY).date().isoformat(), now=now)
        s1_prepared = evidence, common.digest([evidence, rows]), prepared[4]
    output = []
    for right in ("CALL", "PUT"):
        original = s0.evaluate(right=right, **arguments, _prepared=prepared)
        challenger = evaluate_s1(symbol=arguments["symbol"], right=right, rows=rows, missing=missing,
            minute_check=check, reference=arguments["reference"], opening=opening, closing=closing,
            now=now, checkpoint=end, scope_hash=arguments["scope_hash"], _prepared=s1_prepared)
        fully_s1 = challenger.get("factor_evidence", {}).get("state") == "FULL_INTRADAY_RESEARCH"
        cohort = "PAIRED_POLICY_COMPARISON" if valid and fully_s1 else (
            "S1_INTRADAY_ONLY_DATA" if fully_s1 else "INPUT_INCOMPLETE")
        compact_s0 = {k: deepcopy(original[k]) for k in ("evaluation_id", "policy_id", "policy_hash", "state", "reasons")}
        compact_s0["conditions"] = {key: "UNKNOWN" if value is None else "PASS" if value else "FAIL"
            for key, value in original.get("factor_evidence", {}).get("checks", {}).items()}
        compact_s0["conditions"].pop("daily_direction", None)
        compact_s0["conditions"]["session_direction"] = challenger.get("conditions", {}).get("session_direction", "UNKNOWN")
        compact_s0["conditions"]["previous_close_direction"] = (
            "PASS" if (1 if right == "CALL" else -1) * (rows[-1]["close"] - arguments["reference"]["previous_close"]) > 0
            else "FAIL") if valid and not missing else "UNKNOWN"
        comparison = dict(schema="S0_S1_COMPARISON_V1", cohort=cohort, s0=compact_s0, s1=challenger,
            economic_opportunity_id=common.digest([arguments["scope_hash"], original["session"], arguments["symbol"], right, end.isoformat()]),
            amplitude=challenger.get("amplitude"), outcome={"state": "NOT_MEASURED", "y60_pct": None},
            option_cost={"state": "REFERENCE_CONTRACT_UNAVAILABLE", "round_trip_cost_per_unit": None},
            qualified_signal=False)
        challenger["research_strategy"] = "opening_momentum"
        challenger["parent_evaluation_id"] = original["evaluation_id"]
        challenger["economic_opportunity_id"] = comparison["economic_opportunity_id"]
        challenger["reference_collection_owner"] = "S0" if original["state"] == "NUMERIC_PASS" else "S1"
        original["strategy_comparison"] = comparison
        output.append(original)
    return output


def compact_comparison(value):
    result = deepcopy(value)
    s1 = result.get("s1", {})
    for field in ("policy_snapshot", "bar_evidence", "input_checks", "factor_evidence"):
        s1.pop(field, None)
    revision = result.get("reference_eligibility")
    if isinstance(revision, dict):
        retained = {key: deepcopy(revision[key]) for key in (
            "state", "checked_at", "deadline_at", "revision", "reasons", "reference_contract_status") if key in revision}
        reference = revision.get("reference_contract") or result.get("reference_contract")
        if reference:
            selected = {key: deepcopy(reference[key]) for key in (
                "contract_id", "underlying", "right", "expiry_date", "strike", "dte", "bid", "ask",
                "delta", "quote_currency", "multiplier", "multiplier_status", "reference_only") if key in reference}
            selected["snapshot"] = {key: reference.get("snapshot", {}).get(key) for key in (
                "bbo_received_at", "calc_received_at", "bbo_source_freshness", "currency_status")}
            retained["reference_contract"] = selected
            result["reference_contract"] = selected
        result["reference_eligibility"] = retained
    result["evidence_deferred"] = True
    return result
