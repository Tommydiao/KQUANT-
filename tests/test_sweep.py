from dataclasses import replace

from btc_eth_15m.config import AppConfig, StrategyConfig

from btc_eth_15m.sweep import V2_VARIANTS, _render_sweep_markdown, _variant_config


def test_variant_config_replaces_strategy_and_app_fields(tmp_path):
    config = AppConfig(
        symbols=["BTCUSDT"],
        db_path=tmp_path / "market.sqlite3",
        runs_dir=tmp_path / "runs",
        outputs_dir=tmp_path / "outputs",
        strategy=StrategyConfig(),
    )
    variant = _variant_config(
        config,
        {"min_trend_gap_bps": 25.0, "stop_atr_mult": 1.8},
        {"max_hold_bars": 16},
    )
    assert variant.strategy.min_trend_gap_bps == 25.0
    assert variant.strategy.stop_atr_mult == 1.8
    assert variant.max_hold_bars == 16
    assert config.strategy.min_trend_gap_bps == 5.0


def test_v2_variants_include_required_strategy_families():
    families = {item[1].get("mode", "trend_pullback") for item in V2_VARIANTS}
    assert {"trend_pullback", "breakout_failure", "volatility_breakout", "range_reversion"}.issubset(families)


def test_sweep_markdown_includes_daily_target_columns():
    rows = [
        {
            "variant": "daily-target-check",
            "trade_count": 10,
            "profit_factor": 1.2,
            "avg_r": 0.1,
            "avg_daily_return_pct": 5.5,
            "target_range_hit_rate_pct": 50.0,
            "above_target_min_rate_pct": 60.0,
            "loss_day_rate_pct": 20.0,
            "total_return_pct": 15.0,
            "max_drawdown_pct": -4.0,
            "win_rate_pct": 55.0,
            "run_id": "run-1",
        }
    ]

    markdown = _render_sweep_markdown(rows)

    assert "Avg Daily" in markdown
    assert "5%-7% Days" in markdown
    assert "| daily-target-check | 10 | 1.200 | 0.100 | 5.500% | 50.00%" in markdown
