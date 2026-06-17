from __future__ import annotations

import json
import csv
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from btc_eth_15m.config import AppConfig


PULLBACK_VARIANTS: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    ("base", {}, {}),
    ("gap25", {"min_trend_gap_bps": 25.0}, {}),
    ("gap50", {"min_trend_gap_bps": 50.0}, {}),
    ("slope8_gap25", {"ema_slope_bars": 8, "min_trend_gap_bps": 25.0}, {}),
    ("tight_extension_gap25", {"min_trend_gap_bps": 25.0, "max_extension_atr": 0.75}, {}),
    ("volume12_gap25", {"min_trend_gap_bps": 25.0, "min_volume_ratio": 1.2}, {}),
    ("stop18_rr2_gap25", {"min_trend_gap_bps": 25.0, "stop_atr_mult": 1.8, "reward_risk": 2.0}, {}),
    ("stop20_rr15_gap25", {"min_trend_gap_bps": 25.0, "stop_atr_mult": 2.0, "reward_risk": 1.5}, {}),
    ("rr15_hold16_gap25", {"min_trend_gap_bps": 25.0, "reward_risk": 1.5}, {"max_hold_bars": 16}),
    ("recent_pullback_gap25", {"min_trend_gap_bps": 25.0, "pullback_lookback": 1}, {}),
]

V2_VARIANTS: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    (
        "tp_best_prior_trend_regime",
        {"mode": "trend_pullback", "regime_filter": "trend", "min_trend_gap_bps": 25.0, "stop_atr_mult": 2.0, "reward_risk": 1.5},
        {"max_hold_bars": 12},
    ),
    (
        "tp_best_prior_volatile",
        {"mode": "trend_pullback", "regime_filter": "volatile", "min_trend_gap_bps": 25.0, "stop_atr_mult": 2.0, "reward_risk": 1.5},
        {"max_hold_bars": 12},
    ),
    (
        "bf_base",
        {"mode": "breakout_failure", "min_trend_gap_bps": 25.0, "stop_atr_mult": 1.2, "reward_risk": 1.5},
        {"max_hold_bars": 10},
    ),
    (
        "bf_tighter_sweep",
        {"mode": "breakout_failure", "min_trend_gap_bps": 25.0, "breakout_buffer_atr": 0.05, "stop_atr_mult": 1.2, "reward_risk": 1.5},
        {"max_hold_bars": 10},
    ),
    (
        "bf_wider_sweep",
        {"mode": "breakout_failure", "min_trend_gap_bps": 25.0, "breakout_buffer_atr": 0.20, "stop_atr_mult": 1.5, "reward_risk": 1.2},
        {"max_hold_bars": 12},
    ),
    (
        "bf_longer_range",
        {"mode": "breakout_failure", "min_trend_gap_bps": 25.0, "breakout_lookback": 48, "stop_atr_mult": 1.5, "reward_risk": 1.5},
        {"max_hold_bars": 12},
    ),
    (
        "bf_strong_trend",
        {"mode": "breakout_failure", "regime_filter": "trend", "min_trend_gap_bps": 50.0, "breakout_lookback": 48, "stop_atr_mult": 1.8, "reward_risk": 1.2},
        {"max_hold_bars": 12},
    ),
    (
        "bf_strong_volatile",
        {"mode": "breakout_failure", "regime_filter": "volatile", "min_trend_gap_bps": 50.0, "breakout_lookback": 48, "stop_atr_mult": 1.8, "reward_risk": 1.2},
        {"max_hold_bars": 12},
    ),
    (
        "vb_base",
        {"mode": "volatility_breakout", "regime_filter": "trend", "min_trend_gap_bps": 25.0, "stop_atr_mult": 1.5, "reward_risk": 2.0},
        {"max_hold_bars": 12},
    ),
    (
        "vb_strict_contraction",
        {"mode": "volatility_breakout", "regime_filter": "trend", "min_trend_gap_bps": 25.0, "volatility_quantile": 0.20, "contraction_lookback": 12, "stop_atr_mult": 1.5, "reward_risk": 2.0},
        {"max_hold_bars": 12},
    ),
    (
        "vb_longer_breakout",
        {"mode": "volatility_breakout", "regime_filter": "trend", "min_trend_gap_bps": 25.0, "breakout_lookback": 48, "stop_atr_mult": 1.8, "reward_risk": 2.0},
        {"max_hold_bars": 16},
    ),
    (
        "vb_volume_confirm",
        {"mode": "volatility_breakout", "regime_filter": "trend", "min_trend_gap_bps": 25.0, "min_volume_ratio": 1.2, "stop_atr_mult": 1.5, "reward_risk": 2.0},
        {"max_hold_bars": 12},
    ),
    (
        "vb_high_rr",
        {"mode": "volatility_breakout", "regime_filter": "trend", "min_trend_gap_bps": 25.0, "breakout_lookback": 48, "stop_atr_mult": 1.8, "reward_risk": 3.0},
        {"max_hold_bars": 20},
    ),
    (
        "rr_base_range",
        {"mode": "range_reversion", "regime_filter": "range", "min_trend_gap_bps": 25.0, "channel_zscore": 1.5, "stop_atr_mult": 1.2, "reward_risk": 1.2},
        {"max_hold_bars": 8},
    ),
    (
        "rr_wide_band",
        {"mode": "range_reversion", "regime_filter": "range", "min_trend_gap_bps": 25.0, "channel_zscore": 2.0, "stop_atr_mult": 1.5, "reward_risk": 1.2},
        {"max_hold_bars": 10},
    ),
    (
        "rr_fast_exit",
        {"mode": "range_reversion", "regime_filter": "range", "min_trend_gap_bps": 25.0, "channel_zscore": 1.5, "stop_atr_mult": 1.0, "reward_risk": 1.0},
        {"max_hold_bars": 4},
    ),
    (
        "rr_strict_rsi",
        {"mode": "range_reversion", "regime_filter": "range", "min_trend_gap_bps": 25.0, "channel_zscore": 1.75, "mean_reversion_rsi_long": 30.0, "mean_reversion_rsi_short": 70.0, "stop_atr_mult": 1.5, "reward_risk": 1.5},
        {"max_hold_bars": 8},
    ),
    (
        "daily_target_eth_short_htf",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 190.0, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "dt_eth_short_gap300",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 300.0, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "dt_eth_short_volume15",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 190.0, "min_signal_volume_ratio": 1.5, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "dt_eth_short_mid_atr",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 190.0, "min_signal_atr_pct": 0.0059, "max_signal_atr_pct": 0.0120, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "dt_eth_short_regime_mid",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 190.0, "min_signal_regime_atr_pct": 0.0059, "max_signal_regime_atr_pct": 0.0102, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "dt_eth_short_hour15_16",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 190.0, "signal_start_hour_utc": 15, "signal_end_hour_utc": 16, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "dt_eth_short_hour21_23",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 190.0, "signal_start_hour_utc": 21, "signal_end_hour_utc": 23, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "daily_target_eth_short_high_atr",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_atr_pct": 0.0095, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "daily_target_bf_eth_short_volatile",
        {"mode": "breakout_failure", "regime_filter": "volatile", "side_filter": "short", "min_trend_gap_bps": 50.0, "breakout_lookback": 48, "stop_atr_mult": 1.8, "reward_risk": 1.2},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "daily_target_vb_eth_short_trend",
        {"mode": "volatility_breakout", "regime_filter": "trend", "side_filter": "short", "min_trend_gap_bps": 50.0, "breakout_lookback": 48, "stop_atr_mult": 1.8, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 16},
    ),
]

NEXT_VARIANTS = V2_VARIANTS
DEFAULT_VARIANTS = V2_VARIANTS


def run_sweep(
    config: AppConfig,
    variants: list[tuple[str, dict[str, Any], dict[str, Any]]] | None = None,
    variant_names: list[str] | None = None,
) -> Path:
    from btc_eth_15m.backtest import run_backtest

    variants = variants or DEFAULT_VARIANTS
    if variant_names:
        requested = set(variant_names)
        variants = [variant for variant in variants if variant[0] in requested]
        if len(variants) != len(requested):
            found = {variant[0] for variant in variants}
            missing = sorted(requested - found)
            raise ValueError(f"Unknown sweep variant(s): {', '.join(missing)}")
    rows = []
    sweep_id = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    for index, (name, strategy_overrides, app_overrides) in enumerate(variants, start=1):
        print(f"[{index}/{len(variants)}] running {name}", flush=True)
        variant_config = _variant_config(config, strategy_overrides, app_overrides)
        result = run_backtest(variant_config)
        summary = result["summary"]
        daily = summary.get("daily_return_stats", {})
        rows.append(
            {
                "sweep_id": sweep_id,
                "variant": name,
                "run_id": summary["run_id"],
                "trade_count": summary["trade_count"],
                "final_equity": summary["final_equity"],
                "total_return_pct": summary["total_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "win_rate_pct": summary["win_rate_pct"],
                "profit_factor": summary["profit_factor"],
                "expectancy": summary["expectancy"],
                "avg_r": summary["avg_r"],
                "avg_daily_return_pct": daily.get("avg_daily_return_pct", 0.0),
                "target_range_hit_rate_pct": daily.get("target_range_hit_rate_pct", 0.0),
                "above_target_min_rate_pct": daily.get("above_target_min_rate_pct", 0.0),
                "loss_day_rate_pct": daily.get("loss_day_rate_pct", 0.0),
                "strategy_overrides": json.dumps(strategy_overrides, sort_keys=True),
                "app_overrides": json.dumps(app_overrides, sort_keys=True),
            }
        )

    rows.sort(key=lambda row: (row["avg_r"], row["profit_factor"]), reverse=True)
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    csv_path = config.outputs_dir / f"{sweep_id}-sweep.csv"
    md_path = config.outputs_dir / f"{sweep_id}-sweep.md"
    _write_csv(csv_path, rows)
    md_path.write_text(_render_sweep_markdown(rows), encoding="utf-8")
    return md_path


def _variant_config(config: AppConfig, strategy_overrides: dict[str, Any], app_overrides: dict[str, Any]) -> AppConfig:
    strategy = replace(config.strategy, **strategy_overrides)
    return replace(config, strategy=strategy, **app_overrides)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _render_sweep_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# BTC/ETH 15m Parameter Sweep",
        "",
        "| Variant | Trades | PF | Avg R | Avg Daily | 5%-7% Days | >=5% Days | Loss Days | Return | Max DD | Win Rate | Run ID |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['variant']} | {row['trade_count']} | {row['profit_factor']:.3f} | {row['avg_r']:.3f} | "
            f"{row['avg_daily_return_pct']:.3f}% | {row['target_range_hit_rate_pct']:.2f}% | "
            f"{row['above_target_min_rate_pct']:.2f}% | {row['loss_day_rate_pct']:.2f}% | "
            f"{row['total_return_pct']:.2f}% | {row['max_drawdown_pct']:.2f}% | {row['win_rate_pct']:.2f}% | `{row['run_id']}` |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This sweep is for research only and does not send orders.",
            "- Prefer variants with positive Avg R and PF > 1 before considering paper trading.",
            "- A variant with fewer trades but less negative Avg R is useful evidence for the next research branch, not a live-trading approval.",
        ]
    )
    return "\n".join(lines) + "\n"
