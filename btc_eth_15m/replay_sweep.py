from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from btc_eth_15m.config import AppConfig


@dataclass(frozen=True)
class ReplayVariant:
    name: str
    description: str
    predicate: Callable[[dict[str, Any]], bool]
    strategy_overrides: dict[str, Any]


def write_replay_filter_sweep(config: AppConfig, run_id: str) -> Path:
    """Filter an existing trade replay without re-running the pandas backtest path."""
    trades_path = config.runs_dir / run_id / "trades.csv"
    summary_path = config.runs_dir / run_id / "summary.json"
    if not trades_path.exists():
        raise FileNotFoundError(f"Missing trades file: {trades_path}")
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary file: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    trades = _read_trades(trades_path)
    trading_days = int(summary.get("daily_return_stats", {}).get("trading_days") or 1)
    initial_equity = float(summary.get("final_equity", 0.0)) - float(summary.get("by_symbol", {}).get("ETHUSDT", {}).get("net_pnl", 0.0))
    if initial_equity <= 0:
        initial_equity = 10_000.0

    sweep_id = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    rows = [
        _variant_stats(
            sweep_id=sweep_id,
            run_id=run_id,
            variant=variant,
            trades=[trade for trade in trades if variant.predicate(trade)],
            initial_equity=initial_equity,
            trading_days=trading_days,
        )
        for variant in REPLAY_VARIANTS
    ]
    rows.sort(key=lambda row: (row["avg_r"], row["profit_factor"], row["total_return_pct"]), reverse=True)

    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    csv_path = config.outputs_dir / f"{sweep_id}-replay-filter.csv"
    md_path = config.outputs_dir / f"{sweep_id}-replay-filter.md"
    _write_csv(csv_path, rows)
    md_path.write_text(_render_markdown(rows, run_id, trades_path), encoding="utf-8")
    return md_path


def _read_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            parsed = dict(row)
            for key in (
                "net_pnl",
                "gross_pnl",
                "fees",
                "r_multiple",
                "hold_bars",
                "signal_atr_pct",
                "signal_regime_atr_pct",
                "signal_volume_ratio",
                "signal_htf_gap_bps",
                "signal_hour_utc",
            ):
                parsed[key] = _number(parsed.get(key))
            rows.append(parsed)
    return rows


def _variant_stats(
    *,
    sweep_id: str,
    run_id: str,
    variant: ReplayVariant,
    trades: list[dict[str, Any]],
    initial_equity: float,
    trading_days: int,
) -> dict[str, Any]:
    pnl = [float(trade.get("net_pnl") or 0.0) for trade in trades]
    r_values = [float(trade.get("r_multiple") or 0.0) for trade in trades]
    wins = [value for value in pnl if value > 0]
    losses = [value for value in pnl if value < 0]
    total_pnl = sum(pnl)
    final_equity = initial_equity + total_pnl
    daily_pnl: dict[str, float] = defaultdict(float)
    for trade, value in zip(trades, pnl, strict=False):
        day = str(trade.get("exit_time") or trade.get("entry_time") or "")[:10]
        if day:
            daily_pnl[day] += value
    daily_returns = [(value / initial_equity) * 100 for value in daily_pnl.values()]
    target_hits = sum(1 for value in daily_returns if 5.0 <= value <= 7.0)
    above_target_min = sum(1 for value in daily_returns if value >= 5.0)
    loss_days = sum(1 for value in daily_returns if value < 0.0)
    exit_counts = Counter(str(trade.get("exit_reason") or "unknown") for trade in trades)

    return {
        "sweep_id": sweep_id,
        "variant": variant.name,
        "run_id": run_id,
        "mode": "replay_filter",
        "description": variant.description,
        "trade_count": len(trades),
        "final_equity": final_equity,
        "total_return_pct": _pct(total_pnl, initial_equity),
        "max_drawdown_pct": _max_drawdown_pct(pnl, initial_equity),
        "win_rate_pct": _pct(len(wins), len(trades)),
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses else (999.0 if wins else 0.0),
        "expectancy": (total_pnl / len(trades)) if trades else 0.0,
        "avg_r": (sum(r_values) / len(r_values)) if r_values else 0.0,
        "avg_daily_return_pct": (total_pnl / initial_equity * 100 / trading_days) if trading_days else 0.0,
        "target_range_hit_rate_pct": _pct(target_hits, trading_days),
        "above_target_min_rate_pct": _pct(above_target_min, trading_days),
        "loss_day_rate_pct": _pct(loss_days, trading_days),
        "stop_count": exit_counts.get("stop", 0),
        "target_count": exit_counts.get("target", 0),
        "time_count": exit_counts.get("time", 0),
        "strategy_overrides": json.dumps(variant.strategy_overrides, sort_keys=True),
        "app_overrides": json.dumps({"symbols": ["ETHUSDT"], "max_hold_bars": 12}, sort_keys=True),
    }


def _max_drawdown_pct(pnl: list[float], initial_equity: float) -> float:
    equity = initial_equity
    peak = initial_equity
    worst = 0.0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        if peak > 0:
            worst = min(worst, (equity - peak) / peak * 100)
    return worst


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _render_markdown(rows: list[dict[str, Any]], run_id: str, trades_path: Path) -> str:
    lines = [
        "# kquant Replay-Filter Sweep",
        "",
        f"- Source run: `{run_id}`",
        f"- Source trades: `{trades_path}`",
        "- Scope: ETHUSDT short-only 15m replay filter diagnostics.",
        "- Safety: read-only; this does not call exchange APIs and does not place Paper/Testnet/Live orders.",
        "- Important: this is not a fresh backtest. It filters already executed replay trades to rank candidate filters before the pandas backtest runtime is repaired.",
        "",
        "## Branch Ranking",
        "",
        "| Variant | Trades | PF | Avg R | Avg Daily | 5%-7% Days | Loss Days | Return | Max DD | Win Rate | Stop | Target | Time |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['variant']} | {row['trade_count']} | {row['profit_factor']:.3f} | {row['avg_r']:.3f} | "
            f"{row['avg_daily_return_pct']:.4f}% | {row['target_range_hit_rate_pct']:.2f}% | "
            f"{row['loss_day_rate_pct']:.2f}% | {row['total_return_pct']:.2f}% | "
            f"{row['max_drawdown_pct']:.2f}% | {row['win_rate_pct']:.2f}% | "
            f"{row['stop_count']} | {row['target_count']} | {row['time_count']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Branches with better PF/Avg R here are next backtest candidates, not trading approvals.",
            "- A branch with fewer losses but low sample size must be treated as fragile until rerun through the full backtest/sweep path.",
            "- Paper observation remains `NO` until a full backtest report satisfies the daily target and robustness gates.",
        ]
    )
    return "\n".join(lines) + "\n"


def _number(value: str | float | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator * 100


REPLAY_VARIANTS: list[ReplayVariant] = [
    ReplayVariant(
        "dt_eth_short_gap300",
        "min_signal_htf_gap_bps >= 300",
        lambda trade: (trade.get("signal_htf_gap_bps") or 0.0) >= 300.0,
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 300.0},
    ),
    ReplayVariant(
        "dt_eth_short_volume15",
        "min_signal_volume_ratio >= 1.5",
        lambda trade: (trade.get("signal_volume_ratio") or 0.0) >= 1.5,
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_volume_ratio": 1.5},
    ),
    ReplayVariant(
        "dt_eth_short_mid_atr",
        "0.0059 <= min_signal_atr_pct <= 0.0120",
        lambda trade: 0.0059 <= (trade.get("signal_atr_pct") or 0.0) <= 0.0120,
        {
            "mode": "trend_pullback",
            "side_filter": "short",
            "min_signal_atr_pct": 0.0059,
            "max_signal_atr_pct": 0.0120,
        },
    ),
    ReplayVariant(
        "dt_eth_short_regime_mid",
        "0.0059 <= min_signal_regime_atr_pct <= 0.0102",
        lambda trade: 0.0059 <= (trade.get("signal_regime_atr_pct") or 0.0) <= 0.0102,
        {
            "mode": "trend_pullback",
            "side_filter": "short",
            "min_signal_regime_atr_pct": 0.0059,
            "max_signal_regime_atr_pct": 0.0102,
        },
    ),
    ReplayVariant(
        "dt_eth_short_hour15_16",
        "15 <= signal_hour_utc <= 16",
        lambda trade: 15 <= int(trade.get("signal_hour_utc") or -1) <= 16,
        {"mode": "trend_pullback", "side_filter": "short", "signal_start_hour_utc": 15, "signal_end_hour_utc": 16},
    ),
    ReplayVariant(
        "dt_eth_short_hour21_23",
        "21 <= signal_hour_utc <= 23",
        lambda trade: 21 <= int(trade.get("signal_hour_utc") or -1) <= 23,
        {"mode": "trend_pullback", "side_filter": "short", "signal_start_hour_utc": 21, "signal_end_hour_utc": 23},
    ),
]
