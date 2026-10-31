"""Version-isolated price-first opening research; no orders or implicit approvals."""
import json
from copy import deepcopy
from functools import lru_cache
from datetime import timedelta
from pathlib import Path

from . import options_one_minute as common
from . import options_opening_trend as trend

POLICY_ID = "STRAT-OPENING-MOMENTUM-5M-V1"
CONFIG = Path(__file__).resolve().parents[1] / "config/options_opening_momentum_v1.json"


@lru_cache(maxsize=8)
def _policy_at_version(path, file_version):
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if policy["policy_id"] != POLICY_ID or any(policy[key] for key in (
            "qualified_publication_enabled", "paper_enabled", "automatic_paper_enabled",
            "real_orders_enabled", "llm_required")):
        raise ValueError("MOMENTUM_RESEARCH_BOUNDARY_CHANGED")
    policy["policy_hash"] = common.digest(policy)
    return policy


def load_policy():
    info = CONFIG.stat()
    return deepcopy(_policy_at_version(str(CONFIG.absolute()),
                    (info.st_mtime_ns, info.st_ctime_ns, info.st_size)))


def policy_for(evaluation, *, validate=True):
    identity = evaluation.get("policy_id")
    if identity not in {None, POLICY_ID, trend.POLICY_ID}:
        raise ValueError("UNKNOWN_STRATEGY_VERSION")
    policy = load_policy() if identity == POLICY_ID else trend.load_policy()
    if validate and evaluation.get("policy_hash") != policy["policy_hash"]:
        raise ValueError("POLICY_OR_SCOPE_CHANGED")
    return policy


def price_reference_valid(reference, symbol, session, now):
    if reference.get("contract_version") in {"PRICE_REFERENCE_V2", "PRICE_REFERENCE_V3"}:
        from .options_price_reference import valid
        return valid(reference, symbol=symbol, session=session, now=now)
    try:
        return (reference.get("symbol") == symbol and reference.get("session") == session
                and reference.get("price_comparable") is True and bool(reference.get("price_basis_evidence_hash"))
                and bool(reference.get("source_hash")) and common.timestamp(reference["received_at"]) <= now
                and common.finite(reference.get("previous_close")) and reference["previous_close"] > 0
                and reference.get("time_evidence", {}).get("state") == "ORDERED")
    except (KeyError, TypeError, ValueError):
        return False


def price_aggregate(rows):
    return [{"open_at": group[0]["open_at"], "available_at": group[-1]["available_at"],
             "open": group[0]["open"], "close": group[-1]["close"],
             "high": max(r["high"] for r in group), "low": min(r["low"] for r in group),
             "source_hashes": [common.digest(r) for r in group]}
            for offset in range(0, len(rows) - 4, 5) for group in [rows[offset:offset + 5]]]


def evaluate(*, symbol, right, bars, history, reference, opening, closing, now,
             scope_hash, policy=None, checkpoint=None, source_decisions=None, _prepared=None):
    p = policy or load_policy()
    opening, closing, now = map(common.timestamp, (opening, closing, now))
    if right not in {"CALL", "PUT"}:
        raise ValueError("INVALID_RIGHT")
    session = opening.astimezone(common.NY).date().isoformat()
    result = {"policy_id": p["policy_id"], "policy_hash": p["policy_hash"], "policy_snapshot": p,
              "scope_hash": scope_hash, "session": session, "symbol": symbol, "right": right,
              "research_strategy": "opening_momentum", "evaluated_at": now.isoformat(),
              "qualified_signal": False, "runtime_mode": "SHADOW_RESEARCH",
              "paper_enabled": False, "real_orders_enabled": False,
              "event_id": common.digest([p["policy_hash"], scope_hash, session, symbol, right]),
              **trend.exit_times(opening, closing, policy=p)}

    def finish(state, *reasons):
        result.update(state=state, reasons=list(reasons))
        result["evaluation_id"] = common.digest([result["event_id"], result.get("calculation_bar_end"),
                                                 now.isoformat(), state, reasons])
        if state == "NUMERIC_PASS":
            result["evaluation_id"] = common.digest([result["event_id"], result["confirmation_at"], state])
        return result

    cutoff = min(opening + timedelta(minutes=p["entry_window_minutes"]), closing)
    if checkpoint is None and now >= cutoff:
        return finish("ENTRY_WINDOW_CLOSED", "OPENING_ENTRY_WINDOW_CLOSED")
    end = common.timestamp(checkpoint) if checkpoint else opening + timedelta(
        minutes=int((now - opening).total_seconds() // 300) * 5)
    if (end - opening).total_seconds() / 60 not in p["checkpoint_minutes"] or end > now:
        return finish("WAIT_TREND", "WAIT_FIRST_COMPLETE_FIVE_MINUTES")
    result.update(bar_end=end.isoformat(), calculation_bar_end=end.isoformat())
    check = {}
    if _prepared is None:
        rows, missing = trend.complete_minutes(bars, symbol=symbol, opening=opening, until=end,
            now=now, diagnostics=check, price_only=True, source_decisions=source_decisions)
        reference_valid = price_reference_valid(reference, symbol, session, now)
    else:
        rows, missing, check, reference_valid, prepared_groups = _prepared
    result["input_checks"] = {"current_minutes": check, "reference": {
        "state": "VERIFIED" if reference_valid else "UNVERIFIED",
        "reasons": [r for r in reference.get("reference_blockers", [])
                    if r != "NATIVE_CANDLESTICK_UNIT_EVIDENCE_MISSING"]}}
    result["reference_evidence"] = reference
    if missing:
        result["missing_minutes"] = missing
        return finish("INCOMPLETE", "SOURCE_CONFLICT" if any(
            "SOURCE_CONFLICT" in r["reasons"] for r in check["missing_slots"])
            else "CONTIGUOUS_SESSION_MINUTES_MISSING")
    first = rows[0]
    if (first.get("sdk_evidence", {}).get("interface") == "QuoteContext.set_on_candlestick"
            and first["low"] == reference.get("previous_close") and first["open"] != first["low"]):
        result["warnings"] = ["FIRST_MINUTE_SOURCE_RECHECK_REQUIRED"]
    result.update(calculation_input_received_at=max(common.timestamp(r["received_at"]) for r in rows).isoformat(),
                  calculation_input_available_at=end.isoformat())
    groups = price_aggregate(rows) if _prepared is None else prepared_groups
    bar = groups[-1]
    width = bar["high"] - bar["low"]
    if width <= 0:
        return finish("INCOMPLETE", "ZERO_BAR_RANGE")
    m, q = (bar["close"] - bar["open"]) / width, (bar["close"] - bar["low"]) / width
    direction = 1 if right == "CALL" else -1
    prior = groups[:-1]
    boundary = (max(b["high"] for b in prior) if direction == 1 else min(b["low"] for b in prior)) if prior else None
    if not reference_valid:
        result["bar_evidence"] = bar
        result["factor_evidence"] = {"state": "PARTIAL_PRICE_COMPONENTS", "day_open": first["open"],
            "price": bar["close"], "momentum": m, "close_position": q,
            "momentum_threshold": p["momentum_min"], "close_position_threshold": p["close_position_min"],
            "prior_boundary": boundary, "previous_close": None,
            "checks": {"daily_direction": None, "momentum": direction * m >= p["momentum_min"],
                "close_position": q >= p["close_position_min"] if direction == 1 else q <= 1 - p["close_position_min"],
                "prior_breakout": boundary is None or direction * (bar["close"] - boundary) > 0},
            "reference": reference}
        return finish("INCOMPLETE", "PRICE_REFERENCE_UNVERIFIED")
    levels = (first["open"], reference["previous_close"])
    if p["policy_id"] == "STRAT-SESSION-DIRECTION-5M-CHALLENGER-V1" and p.get("previous_close_direction_gate") is False:
        levels = (first["open"],)
    checks = {"daily_direction": all(direction * (bar["close"] - level) > 0 for level in levels),
              "momentum": direction * m >= p["momentum_min"],
              "close_position": q >= p["close_position_min"] if direction == 1 else q <= 1 - p["close_position_min"],
              "prior_breakout": boundary is None or direction * (bar["close"] - boundary) > 0}
    auxiliary = {"state": "UNVERIFIED", "role": "AUXILIARY_ONLY",
                 "warnings": ["NATIVE_CANDLESTICK_UNIT_EVIDENCE_MISSING"], "vwap": None}
    if reference.get("volume_unit") == "SHARES" and reference.get("volume_unit_evidence_hash"):
        from .options_opening_trend_reference import normalize_minutes
        try:
            if any(not common.finite(r.get(k)) or r[k] < 0 for r in rows for k in ("volume", "turnover")):
                raise ValueError("AUXILIARY_AMOUNT_UNAVAILABLE")
            normalized, _ = normalize_minutes(rows, reference)
            volume = sum(r["volume"] for r in normalized)
            if volume > 0:
                auxiliary = {"state": "VERIFIED", "role": "AUXILIARY_ONLY", "warnings": [],
                             "vwap": sum(r["turnover"] for r in normalized) / volume}
                baseline, hashes = trend._baseline(history, opening, common.timestamp(bar["open_at"]), now,
                                                   reference.get("unit_conversion", {}).get("currency_units_per_raw_turnover", 1))
                auxiliary.update(turnover_baseline=baseline, history_source_hashes=hashes,
                                 relative_turnover=sum(r["turnover"] for r in normalized[-5:]) / baseline if baseline else None)
                if baseline is None:
                    auxiliary["warnings"].append("SAME_FIVE_MINUTE_HISTORY_MISSING")
            else:
                auxiliary["warnings"] = ["ZERO_VWAP_DENOMINATOR"]
        except (ValueError, TypeError, KeyError):
            auxiliary["warnings"] = ["AUXILIARY_AMOUNT_UNAVAILABLE"]
    result["factor_evidence"] = {"day_open": first["open"], "previous_close": reference["previous_close"],
        "momentum": m, "close_position": q, "momentum_threshold": p["momentum_min"],
        "close_position_threshold": p["close_position_min"], "prior_boundary": boundary,
        "price": bar["close"], "checks": checks, "auxiliary": auxiliary, "reference": reference}
    result["bar_evidence"] = bar
    if not all(checks.values()):
        return finish("NO_TRIGGER", *["MOMENTUM_" + key.upper() + "_NOT_MET" for key, ok in checks.items() if not ok])
    structure = bar["low"] if direction == 1 else bar["high"]
    risk = direction * (bar["close"] - structure)
    if risk <= 0:
        return finish("INCOMPLETE", "STRUCTURE_R_UNAVAILABLE")
    deadline = min(end + timedelta(seconds=p["signal_deadline_seconds"]), cutoff)
    result.update(confirmation_at=end.isoformat(), deadline_at=deadline.isoformat(), structure_line=structure,
                  initial_r=risk, entry_range=sorted([bar["close"], bar["close"] + direction * p["max_chase_r_fraction"] * risk]))
    return finish("EXPIRED", "ORIGINAL_DEADLINE_EXCEEDED") if now >= deadline else finish(
        "NUMERIC_PASS", "EVENT_CONTRACT_AND_EXACT_APPROVAL_REQUIRED")


def evaluate_pair(**arguments):
    """One immutable as-of input check serves both independent direction results."""
    p = arguments.get("policy") or load_policy()
    opening, closing, now = map(common.timestamp, (arguments["opening"], arguments["closing"], arguments["now"]))
    checkpoint = arguments.get("checkpoint")
    end = common.timestamp(checkpoint) if checkpoint else opening + timedelta(
        minutes=int((now - opening).total_seconds() // 300) * 5)
    prepared = None
    if ((end - opening).total_seconds() / 60 in p["checkpoint_minutes"] and end <= now
            and (checkpoint is not None or now < min(opening + timedelta(minutes=p["entry_window_minutes"]), closing))):
        check = {}
        rows, missing = trend.complete_minutes(arguments["bars"], symbol=arguments["symbol"],
            opening=opening, until=end, now=now, diagnostics=check, price_only=True,
            source_decisions=arguments.get("source_decisions"))
        valid = price_reference_valid(arguments["reference"], arguments["symbol"],
                                      opening.astimezone(common.NY).date().isoformat(), now)
        prepared = rows, missing, check, valid, price_aggregate(rows) if not missing else []
    own = {**arguments, "policy": p, "_prepared": prepared}
    return [evaluate(right=right, **own) for right in ("CALL", "PUT")]
