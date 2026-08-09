from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kquant.early_trend import evaluate_early_trend
from kquant.hard_veto import evaluate_hard_veto


def _candles(closes: list[float], *, volume: float = 1_000_000) -> list[dict]:
    start = datetime(2026, 1, 2, 21, tzinfo=UTC)
    rows = []
    previous = closes[0]
    for index, close in enumerate(closes):
        moment = start + timedelta(days=index)
        rows.append({
            "open_time": moment.isoformat(),
            "close_time": (moment + timedelta(hours=6)).isoformat(),
            "open": previous,
            "high": max(previous, close) * 1.01,
            "low": min(previous, close) * 0.99,
            "close": close,
            "volume": volume * (1.5 if index == len(closes) - 1 else 1.0),
            "bar_state": "closed_candle",
        })
        previous = close
    return rows


def _evaluate(closes: list[float]) -> dict:
    daily = _candles(closes)
    benchmarks = {
        "SPY": _candles([100 + index * 0.02 for index in range(len(closes))]),
        "QQQ": _candles([100 + index * 0.03 for index in range(len(closes))]),
    }
    return evaluate_early_trend(
        "RKLB",
        daily,
        [],
        benchmark_candles=benchmarks,
        event_context={"status": "detected_actions_only", "earnings_calendar_status": "historical_not_available"},
    )


def test_constrained_ignition_can_create_early_watch_before_late_expansion() -> None:
    closes = [100.0] * 65 + [98.0, 97.0, 96.0, 95.0, 96.0, 102.0]
    snapshot = _evaluate(closes)
    ignition = next(item for item in snapshot["setup_factors"] if item["factor_id"] == "setup_fast_ema_turn")
    assert ignition["value"]["ignition"] is True
    assert snapshot["strategy_stage"] in {"EARLY_WATCH", "ARMED"}
    assert snapshot["execution_eligibility"]["eligible_for_manual_review"] is False


def test_late_move_waits_for_pullback_and_never_becomes_buy_review() -> None:
    closes = [100.0] * 65 + [100.0, 102.0, 106.0, 112.0, 118.0, 125.0]
    snapshot = _evaluate(closes)
    assert snapshot["strategy_stage"] == "LATE_WAIT_PULLBACK"
    assert snapshot["execution_eligibility"]["paper_only"] is True
    assert "setup_not_armed" in snapshot["execution_eligibility"]["blockers"]


def test_future_bar_does_not_change_prior_snapshot() -> None:
    closes = [100.0] * 65 + [98.0, 97.0, 96.0, 95.0, 96.0, 102.0]
    baseline = _evaluate(closes)
    extended = closes + [180.0]
    repeated = _evaluate(extended[:-1])
    assert repeated["factor_snapshot_hash"] == baseline["factor_snapshot_hash"]


def test_hard_veto_uses_profile_specific_high_beta_limits() -> None:
    signal = {
        "features": {"extension_pct": 11.5, "atr_pct": 8.5},
        "strategy_limits": {"max_extension_pct": 12.0, "max_atr_pct": 12.0},
        "data_status": {"data_quality": "clean", "daily_provider_status": "available", "hourly_provider_status": "available", "market_session": "regular"},
        "risk_reward_plan": {"risk_reward_value": 3.0},
        "trade_risk_assessment": {"hard_vetoes": []},
    }
    result = evaluate_hard_veto(signal, {"regime": "RISK_ON"})
    assert "extension_too_high" not in result["reasons"]
    assert "atr_too_high" not in result["reasons"]
