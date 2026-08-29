from __future__ import annotations

from kquant.validation_robustness import (
    concentration_report,
    default_parameter_variants,
    evidence_score,
    parameter_sensitivity_report,
    rolling_walk_forward_windows,
    statistical_confidence_report,
)


def _trades(count: int = 80) -> list[dict]:
    return [
        {
            "completed": True,
            "signal_time": f"2026-01-{index + 1:03d}",
            "realized_r": 1.0 if index % 3 else -0.5,
            "symbol": "NVDA" if index < 40 else "MSFT",
            "sector": "Technology",
            "stock_layer": "Core",
            "market_regime": "RISK_ON" if index % 2 else "RISK_OFF",
            "volatility_bucket": "low" if index % 2 else "high",
        }
        for index in range(count)
    ]


def test_rolling_windows_are_chronological_and_embargoed() -> None:
    windows = rolling_walk_forward_windows(_trades(), windows=3, embargo_bars=2)
    assert len(windows) >= 1
    assert windows[0]["chronological"] is True
    assert windows[0]["train"]["sample_count"] > 0
    assert windows[0]["test"]["sample_count"] > 0


def test_sensitivity_and_confidence_report_real_variants() -> None:
    trades = _trades()
    report = parameter_sensitivity_report(lambda overrides: trades if not overrides else trades[:-1], variants=default_parameter_variants()[:3])
    assert len(report["variants"]) == 3
    assert report["not_an_optimization_search"] is True
    confidence = statistical_confidence_report(trades, trial_count=3)
    assert confidence["summary"]["sample_count"] == 80
    assert confidence["deflated_sharpe"]["available"] is True


def test_concentration_and_evidence_are_research_only() -> None:
    trades = _trades()
    concentration = concentration_report(trades)
    assert concentration["by_symbol"][0]["name"] == "MSFT"
    result = evidence_score(
        test_summary={"sample_count": 120, "average_r": 0.2, "profit_factor": 1.2},
        sensitivity={"stable": True},
        regime={"regime:RISK_ON": {"average_r": 0.2}, "regime:RISK_OFF": {"average_r": 0.1}},
        concentration=concentration,
        portfolio_metrics={"total_return_pct": 10, "max_drawdown_pct": -5},
        benchmark_return_pct=3,
    )
    assert result["not_a_buy_signal"] is True
