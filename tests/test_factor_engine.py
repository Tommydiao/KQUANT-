from __future__ import annotations

from kquant.factor_engine import build_factor_snapshot, decision_evidence


def test_factor_snapshot_is_versioned_and_exposes_only_registered_factors() -> None:
    signal = {
        "symbol": "NVDA",
        "profile_name": "swing_long_v1",
        "strategy_version": "swing_long_v1.1.0",
        "strategy_config_hash": "frozen",
        "score": 86,
        "score_breakdown": {
            "total_score": 86,
            "factors": {
                "trend": {"close_above_ema20": 16, "ema20_above_ema50": 14, "ema50_above_ema200": 12, "trend_return": 8},
                "trigger": {"close_above_hourly_ema20": 10, "hourly_ema20_above_ema50": 9, "hourly_momentum": 8},
            },
            "deductions": {"atr": 2, "extension_high": 1, "extension_low": 0},
            "volume_score": 8,
        },
        "features": {"trend_return_5d_pct": 3.1, "one_hour_momentum_pct": 0.8, "volume_ratio": 1.5, "atr_pct": 2.4, "extension_pct": 1.2, "rsi14": 58},
        "data_status": {"daily_candle_time": "2026-07-24T20:00:00+00:00"},
        "ai_feature_packet_v3": {"relative_strength_context": {"stock_minus_spy_pct": 1.2, "stock_minus_qqq_pct": 0.5}},
    }
    snapshot = build_factor_snapshot(signal, {"regime": "RISK_ON"})
    evidence = decision_evidence(snapshot, signal)

    assert snapshot["registry_version"] == "factor_registry_v1"
    assert snapshot["factor_snapshot_hash"]
    assert "daily_ema_stack" in snapshot["supporting_factors"]
    assert "market_breadth" in snapshot["unavailable_factors"]
    assert all(item["factor_id"] != "unregistered_factor" for item in evidence["supporting_factors"])

