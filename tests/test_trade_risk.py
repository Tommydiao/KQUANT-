from __future__ import annotations

from kquant.trade_risk import assess_trade_risk


def _candles(volume: float = 200_000) -> list[dict]:
    return [
        {
            "open": 100.0 + index,
            "high": 102.0 + index,
            "low": 99.0 + index,
            "close": 101.0 + index,
            "volume": volume,
            "bar_state": "closed_candle",
        }
        for index in range(20)
    ]


def _plans(rr: float = 2.2) -> tuple[dict, dict, dict]:
    return (
        {"entry_low": 118.0, "entry_high": 120.0},
        {"stop": 115.0},
        {"risk_reward_value": rr},
    )


def test_trade_risk_allows_valid_liquid_manual_review() -> None:
    entry, stop, rr = _plans()
    assessment = assess_trade_risk(
        daily_candles=_candles(),
        feature_values={"gap_risk_pct": 0.5, "extension_pct": 2.0, "atr_pct": 3.0},
        entry_plan=entry,
        stop_plan=stop,
        risk_reward_plan=rr,
        data_clean=True,
    )

    assert assessment["eligible_for_manual_money_review"] is True
    assert assessment["risk_per_share"] == 4.0
    assert assessment["position_sizing_requires_account_value"] is True
    assert assessment["no_order_submission"] is True


def test_trade_risk_blocks_invalid_stop_low_liquidity_and_low_rr() -> None:
    entry, stop, rr = _plans(rr=1.2)
    stop["stop"] = 121.0
    assessment = assess_trade_risk(
        daily_candles=_candles(volume=1_000),
        feature_values={"gap_risk_pct": 4.0, "extension_pct": 7.0, "atr_pct": 6.0},
        entry_plan=entry,
        stop_plan=stop,
        risk_reward_plan=rr,
        data_clean=False,
    )

    assert assessment["status"] == "blocked"
    assert {"data_quality_not_clean", "invalid_stop", "risk_reward_below_minimum", "insufficient_liquidity"}.issubset(assessment["hard_vetoes"])
    assert {"elevated_gap_risk", "extension_chase_risk", "elevated_atr_risk"}.issubset(assessment["warnings"])
