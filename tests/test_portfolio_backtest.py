from __future__ import annotations

from kquant.portfolio_backtest import (
    PortfolioConfig,
    buy_and_hold_benchmark,
    ema_trend_benchmark,
    portfolio_performance_metrics,
    simulate_cash_portfolio,
)


def _trade(symbol: str, entry: str, exit_time: str, entry_price: float, exit_price: float, score: float = 80) -> dict:
    return {
        "symbol": symbol,
        "signal_time": entry,
        "entry_time": entry,
        "exit_time": exit_time,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "stop_price": entry_price - 2,
        "score": score,
        "realized_r": (exit_price - entry_price) / 2,
    }


def test_cash_portfolio_sorts_same_day_candidates_and_respects_position_limit() -> None:
    trades = [
        _trade("LOW", "2026-01-02T14:30:00+00:00", "2026-01-05T14:30:00+00:00", 10, 12, 70),
        _trade("HIGH", "2026-01-02T14:30:00+00:00", "2026-01-05T14:30:00+00:00", 10, 11, 90),
    ]
    result = simulate_cash_portfolio(trades, PortfolioConfig(initial_cash=10_000, max_positions=1, risk_per_trade_pct=1, max_total_risk_pct=1))
    assert [item["symbol"] for item in result["executions"]] == ["HIGH"]
    assert result["rejected"][0]["reason"] == "max_positions"
    assert result["cash_only"] is True


def test_portfolio_metrics_and_benchmarks_are_reproducible() -> None:
    result = simulate_cash_portfolio([
        _trade("AAA", "2026-01-02T14:30:00+00:00", "2026-01-06T14:30:00+00:00", 10, 12),
        _trade("BBB", "2026-01-07T14:30:00+00:00", "2026-01-10T14:30:00+00:00", 10, 8),
    ])
    metrics = portfolio_performance_metrics(result)
    assert metrics["trade_count"] == 2
    assert metrics["profit_factor"] > 0
    candles = [{"open_time": f"2026-01-{day:02d}T00:00:00+00:00", "close": 100 + day} for day in range(1, 80)]
    assert buy_and_hold_benchmark(candles, "SPY")["total_return_pct"] > 0
    assert ema_trend_benchmark(candles)["available"] is True
