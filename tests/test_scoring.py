from __future__ import annotations

from kquant.scoring import CANONICAL_SCORING_CONFIG, calculate_score_components


def test_canonical_scoring_golden_sample_persists_factors_and_deductions() -> None:
    result = calculate_score_components(
        CANONICAL_SCORING_CONFIG,
        close=110.0,
        ema20=105.0,
        ema50=100.0,
        ema200=95.0,
        hourly_close=110.0,
        hourly_ema20=105.0,
        hourly_ema50=100.0,
        trend_return_pct=4.0,
        hourly_momentum_pct=1.0,
        volume_ratio=1.25,
        atr_pct=6.0,
        extension_pct=8.0,
    )

    assert result["scoring_config_version"] == "score_config_v1"
    assert result["trend_score"] == 50.8
    assert result["trigger_score"] == 22.0
    assert result["volume_score"] == 9.0
    assert result["risk_score"] == 15.6
    assert result["total_score"] == 97.4
    assert result["deductions"] == {"atr": 1.4, "extension_high": 1.0, "extension_low": 0.0}
