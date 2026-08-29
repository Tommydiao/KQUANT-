from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


STRATEGY_VERSION = "early_trend_3_15d_v1.0.0"
SETUP_POLICY_VERSION = "early_trend_setup_v1.0.0"
TRIGGER_POLICY_VERSION = "early_trend_trigger_v1.0.0"


class SetupStage(StrEnum):
    NOT_READY = "NOT_READY"
    EARLY_WATCH = "EARLY_WATCH"
    ARMED = "ARMED"
    BUY_REVIEW = "BUY_REVIEW"
    LATE_WAIT_PULLBACK = "LATE_WAIT_PULLBACK"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class ExecutionEligibility:
    status: str
    eligible_for_manual_review: bool
    paper_only: bool
    blockers: tuple[str, ...]
    session: str
    bbo_valid: bool
    quote_fresh: bool
    closed_5m_confirmed: bool


@dataclass(frozen=True)
class TriggerDecision:
    score: float | None
    threshold: float
    confirmed: bool
    as_of: str | None
    factors: tuple[dict[str, Any], ...]
    status: str


@dataclass(frozen=True)
class EarlyTrendSnapshot:
    symbol: str
    strategy_version: str
    setup_policy_version: str
    trigger_policy_version: str
    strategy_stage: str
    setup_score: float
    trigger_score: float | None
    setup_as_of: str | None
    confirmation_as_of: str | None
    setup_factors: tuple[dict[str, Any], ...]
    trigger: TriggerDecision
    execution_eligibility: ExecutionEligibility
    invalidation_price: float | None
    pullback_zone: tuple[float, float] | None
    summary: str
    factor_snapshot_hash: str
    lead_time_evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _closed(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in candles if item.get("bar_state") != "forming_candle"]


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result


def _return_pct(values: list[float], bars: int, end: int | None = None) -> float | None:
    stop = len(values) if end is None else end
    if stop <= bars or values[stop - bars - 1] <= 0:
        return None
    return (values[stop - 1] / values[stop - bars - 1] - 1.0) * 100.0


def _true_ranges(candles: list[dict[str, Any]]) -> list[float]:
    result: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        high = float(candle["high"])
        low = float(candle["low"])
        if previous_close is None:
            result.append(high - low)
        else:
            result.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = float(candle["close"])
    return result


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _factor(
    factor_id: str,
    group: str,
    value: Any,
    contribution: float,
    maximum: float,
    as_of: str | None,
    detail: str,
) -> dict[str, Any]:
    return {
        "factor_id": factor_id,
        "group": group,
        "value": value,
        "contribution": round(contribution, 2),
        "maximum": maximum,
        "as_of": as_of,
        "detail": detail,
    }


def _benchmark_context(stock_closes: list[float], benchmark_candles: dict[str, list[dict[str, Any]]]) -> dict[str, float | None]:
    stock_5 = _return_pct(stock_closes, 5)
    stock_prev_5 = _return_pct(stock_closes, 5, len(stock_closes) - 5)
    result: dict[str, float | None] = {"stock_5d": stock_5}
    for symbol in ("SPY", "QQQ"):
        candles = _closed(list(benchmark_candles.get(symbol) or []))
        closes = [float(item["close"]) for item in candles]
        benchmark_5 = _return_pct(closes, 5)
        benchmark_prev_5 = _return_pct(closes, 5, len(closes) - 5)
        result[f"{symbol.lower()}_5d"] = benchmark_5
        result[f"relative_{symbol.lower()}_5d"] = (
            stock_5 - benchmark_5 if stock_5 is not None and benchmark_5 is not None else None
        )
        result[f"relative_{symbol.lower()}_acceleration"] = (
            (stock_5 - benchmark_5) - (stock_prev_5 - benchmark_prev_5)
            if None not in (stock_5, benchmark_5, stock_prev_5, benchmark_prev_5)
            else None
        )
    return result


def _trigger_decision(candles: list[dict[str, Any]], closed_5m: list[dict[str, Any]]) -> TriggerDecision:
    completed = _closed(candles)
    if len(completed) < 30:
        return TriggerDecision(None, 70.0, False, None, (), "limited_evidence")
    closes = [float(item["close"]) for item in completed]
    volumes = [float(item.get("volume") or 0) for item in completed]
    ema8, ema9, ema20 = _ema(closes, 8), _ema(closes, 9), _ema(closes, 20)
    as_of = str(completed[-1].get("close_time") or completed[-1].get("open_time") or "") or None
    factors: list[dict[str, Any]] = []
    close = closes[-1]
    ema_fast_score = 20.0 if close >= ema8[-1] >= ema9[-1] else 0.0
    factors.append(_factor("trigger_ema8_9", "confirmation", close, ema_fast_score, 20, as_of, "1H close and fast EMA alignment"))
    ema20_score = 15.0 if close >= ema20[-1] else 0.0
    factors.append(_factor("trigger_ema20", "confirmation", ema20[-1], ema20_score, 15, as_of, "1H close above EMA20"))
    momentum = _return_pct(closes, 7)
    momentum_score = 20.0 if momentum is not None and 0.3 <= momentum <= 6.0 else 8.0 if momentum is not None and momentum > 0 else 0.0
    factors.append(_factor("trigger_momentum_7bar", "confirmation", momentum, momentum_score, 20, as_of, "Seven closed 1H bars"))
    prior_volume = _average(volumes[-21:-1])
    volume_ratio = volumes[-1] / prior_volume if prior_volume > 0 else None
    volume_score = 20.0 if volume_ratio is not None and volume_ratio >= 1.2 else 8.0 if volume_ratio is not None and volume_ratio >= 1.0 else 0.0
    factors.append(_factor("trigger_relative_volume", "confirmation", volume_ratio, volume_score, 20, as_of, "Latest closed 1H volume versus prior 20"))
    previous_high = max(float(item["high"]) for item in completed[-11:-1])
    reclaimed = float(completed[-1]["low"]) <= ema20[-1] * 1.005 and close >= ema20[-1]
    structure_score = 15.0 if close > previous_high or reclaimed else 0.0
    factors.append(_factor("trigger_breakout_or_reclaim", "confirmation", close > previous_high or reclaimed, structure_score, 15, as_of, "Closed 1H breakout or EMA20 reclaim"))
    five = _closed(closed_5m)
    five_confirmed = False
    if len(five) >= 10:
        five_closes = [float(item["close"]) for item in five]
        five_confirmed = five_closes[-1] >= _ema(five_closes, 9)[-1] and five_closes[-1] >= five_closes[-2]
    five_score = 10.0 if five_confirmed else 0.0
    factors.append(_factor("trigger_closed_5m", "execution", five_confirmed, five_score, 10, str(five[-1].get("close_time") or five[-1].get("open_time") or "") if five else None, "Latest completed 5m confirmation"))
    score = round(sum(float(item["contribution"]) for item in factors), 1)
    return TriggerDecision(score, 70.0, score >= 70 and five_confirmed, as_of, tuple(factors), "available")


def evaluate_early_trend(
    symbol: str,
    daily_candles: list[dict[str, Any]],
    confirmation_candles: list[dict[str, Any]],
    *,
    five_minute_candles: list[dict[str, Any]] | None = None,
    benchmark_candles: dict[str, list[dict[str, Any]]] | None = None,
    realtime_snapshot: dict[str, Any] | None = None,
    event_context: dict[str, Any] | None = None,
    instrument_eligible: bool = True,
    validation_ready: bool = False,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate one immutable early-trend snapshot from completed bars only."""

    active = dict(parameters or {})
    watch_threshold = float(active.get("watch_threshold", 60.0))
    armed_threshold = float(active.get("armed_threshold", 72.0))
    ignition_return_min = float(active.get("ignition_return_min", 5.0))
    volume_ratio_full = float(active.get("volume_ratio_full", 1.2))
    contraction_ratio = float(active.get("atr_contraction_ratio", 0.9))
    late_return_5d = float(active.get("late_return_5d", 15.0))
    late_extension_pct = float(active.get("late_extension_pct", 10.0))
    daily = _closed(daily_candles)
    confirmation = _closed(confirmation_candles)
    if len(daily) < 60:
        empty_execution = ExecutionEligibility("blocked", False, True, ("insufficient_daily_history",), "unknown", False, False, False)
        snapshot = EarlyTrendSnapshot(
            symbol.upper(), STRATEGY_VERSION, SETUP_POLICY_VERSION, TRIGGER_POLICY_VERSION,
            SetupStage.NOT_READY, 0.0, None, None, None, (),
            TriggerDecision(None, 70.0, False, None, (), "limited_evidence"),
            empty_execution, None, None, "日线历史不足，暂不判断。", "", {
                "status": "limited_evidence", "historical_setup_trades": 0,
                "prospective_trigger_results": 0, "buy_review_activation_ready": False,
            },
        )
        payload = snapshot.to_dict()
        payload["factor_snapshot_hash"] = _snapshot_hash(payload)
        return payload

    closes = [float(item["close"]) for item in daily]
    volumes = [float(item.get("volume") or 0) for item in daily]
    ema8, ema9, ema20 = _ema(closes, 8), _ema(closes, 9), _ema(closes, 20)
    close = closes[-1]
    as_of = str(daily[-1].get("close_time") or daily[-1].get("open_time") or "") or None
    factors: list[dict[str, Any]] = []

    fast_turn = close >= ema8[-1] >= ema9[-1]
    ema20_slope = (ema20[-1] / ema20[-6] - 1.0) * 100 if ema20[-6] else 0.0
    reclaimed_ema20 = any(closes[index - 1] < ema20[index - 1] <= closes[index] for index in range(max(1, len(closes) - 5), len(closes)))
    relative = _benchmark_context(closes, benchmark_candles or {})
    latest_return = (close / closes[-2] - 1.0) * 100 if closes[-2] else 0.0
    short_base_breakout = close > max(closes[-6:-1])
    ignition = bool(
        latest_return >= ignition_return_min
        and short_base_breakout
        and close >= ema8[-1] * 0.98
        and float(relative.get("relative_spy_5d") or -1) > 0
    )
    trend_score = min(25.0, (10 if fast_turn else 15 if ignition else 0) + (5 if close >= ema20[-1] else 0) + (5 if ema20_slope > 0 else 0) + (5 if reclaimed_ema20 else 0))
    factors.append(_factor("setup_fast_ema_turn", "trend", {"fast_turn": fast_turn, "ignition": ignition, "latest_return_pct": round(latest_return, 3), "ema20_slope_pct": round(ema20_slope, 3), "reclaimed": reclaimed_ema20}, trend_score, 25, as_of, "EMA8/9 turn, constrained ignition, EMA20 slope and reclaim"))

    rs_score = 0.0
    for key in ("relative_spy_5d", "relative_qqq_5d"):
        if _number(relative.get(key)) is not None and float(relative[key]) > 0:
            rs_score += 5
    for key in ("relative_spy_acceleration", "relative_qqq_acceleration"):
        if _number(relative.get(key)) is not None and float(relative[key]) > 0:
            rs_score += 5
    factors.append(_factor("setup_relative_strength_acceleration", "relative_strength", relative, rs_score, 20, as_of, "Five-day strength and acceleration versus SPY/QQQ"))

    avg_volume20 = _average(volumes[-21:-1])
    volume_ratio = volumes[-1] / avg_volume20 if avg_volume20 > 0 else 0.0
    up_volumes = [volumes[index] for index in range(len(daily) - 5, len(daily)) if closes[index] > closes[index - 1]]
    down_volumes = [volumes[index] for index in range(len(daily) - 5, len(daily)) if closes[index] <= closes[index - 1]]
    up_down_ratio = _average(up_volumes) / _average(down_volumes) if down_volumes and _average(down_volumes) > 0 else (2.0 if up_volumes else 0.0)
    accumulation_days = sum(1 for index in range(len(daily) - 5, len(daily)) if closes[index] > closes[index - 1])
    volume_score = (10 if volume_ratio >= volume_ratio_full else 6 if volume_ratio >= 1.0 else 0) + (5 if up_down_ratio >= 1.2 else 0) + (5 if accumulation_days >= 3 else 0)
    factors.append(_factor("setup_volume_accumulation", "volume", {"relative_volume": round(volume_ratio, 3), "up_down_volume": round(up_down_ratio, 3), "accumulation_days": accumulation_days}, volume_score, 20, as_of, "Relative volume and five-day accumulation"))

    true_ranges = _true_ranges(daily)
    atr14 = _average(true_ranges[-14:])
    prior_atr = _average(true_ranges[-34:-14])
    atr_pct = atr14 / close * 100 if close > 0 else 0.0
    contraction = prior_atr > 0 and atr14 <= prior_atr * contraction_ratio
    prior10_high = max(float(item["high"]) for item in daily[-11:-1])
    prior20_high = max(float(item["high"]) for item in daily[-21:-1])
    near_breakout = close >= prior10_high * 0.98
    breakout = close > prior20_high
    structure_score = min(20.0, (7 if near_breakout else 0) + (6 if contraction else 0) + (7 if breakout or reclaimed_ema20 or (short_base_breakout and ignition) else 0))
    factors.append(_factor("setup_base_breakout", "structure", {"near_10d_high": near_breakout, "short_base_ignition": short_base_breakout and ignition, "atr_contraction": contraction, "breakout_20d": breakout}, structure_score, 20, as_of, "Base proximity, constrained five-day ignition, ATR contraction and breakout/reclaim"))

    extension_pct = (close / ema20[-1] - 1.0) * 100 if ema20[-1] else 0.0
    return_5d = _return_pct(closes, 5) or 0.0
    gap_pct = abs((float(daily[-1]["open"]) / float(daily[-2]["close"]) - 1.0) * 100) if float(daily[-2]["close"]) else 0.0
    dollar_volume = close * avg_volume20
    risk_score = (5 if dollar_volume >= 20_000_000 else 0) + (4 if atr_pct <= 12 else 0) + (3 if gap_pct <= 8 else 0) + (3 if -2 <= extension_pct <= 10 else 0)
    factors.append(_factor("setup_liquidity_risk", "risk", {"dollar_volume": round(dollar_volume, 2), "atr_pct": round(atr_pct, 3), "gap_pct": round(gap_pct, 3), "extension_pct": round(extension_pct, 3), "return_5d_pct": round(return_5d, 3)}, risk_score, 15, as_of, "Liquidity, volatility, gap and extension"))

    score = round(sum(float(item["contribution"]) for item in factors), 1)
    event = dict(event_context or {})
    setup_blockers: list[str] = []
    if not instrument_eligible:
        setup_blockers.append("instrument_not_supported")
    if not benchmark_candles or any(relative.get(key) is None for key in ("relative_spy_5d", "relative_qqq_5d")):
        setup_blockers.append("benchmark_history_missing")
    if event.get("status") in {"missing", "unknown", "unavailable", "not_ingested"} or event.get("earnings_calendar_status") == "not_ingested":
        setup_blockers.append("event_calendar_missing")
    if event.get("earnings_within_days") is not None and abs(int(event["earnings_within_days"])) <= 2:
        setup_blockers.append("earnings_window")

    invalidated = close < ema20[-1] and ema8[-1] < ema9[-1] and all(float(relative.get(key) or -1) < 0 for key in ("relative_spy_5d", "relative_qqq_5d"))
    late = return_5d > late_return_5d or extension_pct > late_extension_pct
    if invalidated:
        stage = SetupStage.INVALIDATED
        summary = "结构已经失效，继续观察而不是抄底。"
    elif late:
        stage = SetupStage.LATE_WAIT_PULLBACK
        summary = "走势已经转强，但短线扩张过快，等待回踩或横盘消化。"
    elif score >= armed_threshold and not setup_blockers:
        stage = SetupStage.ARMED
        summary = "结构已进入准备区，等待闭合 1H 与 5m 触发确认。"
    elif score >= watch_threshold:
        stage = SetupStage.EARLY_WATCH
        summary = "结构正在转强，加入早期观察。"
    else:
        stage = SetupStage.NOT_READY
        summary = "结构尚未达到早期转强观察标准。"

    trigger = _trigger_decision(confirmation, list(five_minute_candles or []))
    realtime = dict(realtime_snapshot or {})
    quote = dict(realtime.get("quote") or {})
    calendar = dict(realtime.get("calendar") or {})
    session = str(calendar.get("session") or realtime.get("session") or "unknown")
    trust = str(realtime.get("trust") or "unavailable")
    bid, ask = _number(quote.get("bid")), _number(quote.get("ask"))
    bbo_valid = bid is not None and ask is not None and bid > 0 and ask >= bid
    quote_fresh = trust == "live_quote" and float(quote.get("age_seconds") or 10_000) <= 15
    execution_blockers = list(setup_blockers)
    if stage != SetupStage.ARMED:
        execution_blockers.append("setup_not_armed")
    if session != "regular":
        execution_blockers.append("session_not_regular")
    if not quote_fresh:
        execution_blockers.append("quote_not_fresh")
    if not bbo_valid:
        execution_blockers.append("bbo_unavailable")
    if not trigger.confirmed:
        execution_blockers.append("closed_confirmation_missing")
    if not validation_ready:
        execution_blockers.append("strategy_validation_not_ready")
    execution_blockers = list(dict.fromkeys(execution_blockers))
    executable_structure = stage == SetupStage.ARMED and trigger.confirmed and not [item for item in execution_blockers if item != "strategy_validation_not_ready"]
    if executable_structure:
        stage = SetupStage.BUY_REVIEW
    execution = ExecutionEligibility(
        "paper_only" if executable_structure else "waiting",
        executable_structure,
        True,
        tuple(execution_blockers),
        session,
        bbo_valid,
        quote_fresh,
        any(item.get("factor_id") == "trigger_closed_5m" and bool(item.get("value")) for item in trigger.factors),
    )
    pullback_zone = (round(ema9[-1], 2), round(ema20[-1], 2)) if ema9[-1] >= ema20[-1] else (round(ema20[-1], 2), round(ema9[-1], 2))
    invalidation = round(min(ema20[-1], min(float(item["low"]) for item in daily[-5:])), 2)
    evidence = {
        "status": "limited_evidence",
        "historical_setup_trades": 0,
        "prospective_trigger_results": 0,
        "minimum_test_trades": 100,
        "minimum_forward_days": 20,
        "minimum_forward_triggers": 30,
        "buy_review_activation_ready": bool(validation_ready),
        "daily_setup_and_intraday_trigger_reported_separately": True,
    }
    payload_without_hash = {
        "symbol": symbol.upper(),
        "strategy_version": STRATEGY_VERSION,
        "setup_policy_version": SETUP_POLICY_VERSION,
        "trigger_policy_version": TRIGGER_POLICY_VERSION,
        "strategy_stage": stage.value,
        "setup_score": score,
        "trigger_score": trigger.score,
        "setup_as_of": as_of,
        "confirmation_as_of": trigger.as_of,
        "setup_factors": tuple(factors),
        "trigger": trigger,
        "execution_eligibility": execution,
        "invalidation_price": invalidation,
        "pullback_zone": pullback_zone,
        "summary": summary,
        "lead_time_evidence": evidence,
    }
    factor_hash = _snapshot_hash(payload_without_hash)
    return EarlyTrendSnapshot(
        symbol.upper(), STRATEGY_VERSION, SETUP_POLICY_VERSION, TRIGGER_POLICY_VERSION,
        stage.value, score, trigger.score, as_of, trigger.as_of, tuple(factors), trigger,
        execution, invalidation, pullback_zone, summary, factor_hash, evidence,
    ).to_dict()


def _snapshot_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
