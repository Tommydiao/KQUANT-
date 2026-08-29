from __future__ import annotations

from kquant.technical_features import calculate_feature_snapshot, ema_last, rsi


def _candles(closes: list[float]) -> list[dict]:
    rows = []
    for index, close in enumerate(closes):
        rows.append(
            {
                "open_time": f"2026-01-{index + 1:02d}T14:30:00+00:00",
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000 + index * 10_000,
                "bar_state": "closed_candle",
            }
        )
    return rows


def test_ema_and_rsi_have_deterministic_defined_edge_cases() -> None:
    assert ema_last([1.0, 2.0, 3.0], 3) == 2.25
    assert rsi([float(index) for index in range(1, 17)], 14) == 100.0
    assert rsi([1.0, 2.0], 14) is None


def test_feature_snapshot_exposes_required_values_and_null_policy() -> None:
    snapshot = calculate_feature_snapshot(_candles([100 + index for index in range(30)]), timeframe="1D")

    assert snapshot["contract_version"] == "technical_features_v1"
    assert snapshot["values"]["ema_20"] is not None
    assert snapshot["values"]["atr_pct"] is not None
    assert snapshot["values"]["rsi_14"] == 100.0
    assert snapshot["values"]["volume_ratio_20"] is not None
    assert snapshot["values"]["gap_risk_pct"] is not None
    assert snapshot["availability"]["rsi_14"]["minimum_bars"] == 15
