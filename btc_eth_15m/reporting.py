from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from btc_eth_15m.config import AppConfig


def write_report(config: AppConfig, run_id: str) -> Path:
    run_dir = config.runs_dir / run_id
    summary_path = run_dir / "summary.json"
    trades_path = run_dir / "trades.csv"
    equity_path = run_dir / "equity.csv"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    trades = pd.read_csv(trades_path) if trades_path.exists() else pd.DataFrame()
    equity = pd.read_csv(equity_path) if equity_path.exists() else pd.DataFrame()
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    out_path = config.outputs_dir / f"{run_id}-report.md"
    out_path.write_text(_render_markdown(summary, trades, equity), encoding="utf-8")
    (config.outputs_dir / f"{run_id}-summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )
    if trades_path.exists():
        trades.to_csv(config.outputs_dir / f"{run_id}-trades.csv", index=False)
    if equity_path.exists():
        equity.to_csv(config.outputs_dir / f"{run_id}-equity.csv", index=False)
    return out_path


def _render_markdown(summary: dict, trades: pd.DataFrame, equity: pd.DataFrame) -> str:
    pass_status = _pass_status(summary)
    lines = [
        f"# BTC/ETH 15m Backtest Report",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Symbols: `{summary['symbols']}`",
        f"- Trade count: `{summary['trade_count']}`",
        f"- Final equity: `{_format_money(summary['final_equity'])}`",
        f"- Total return: `{summary['total_return_pct']:.2f}%`",
        f"- Max drawdown: `{summary['max_drawdown_pct']:.2f}%`",
        f"- Win rate: `{summary['win_rate_pct']:.2f}%`",
        f"- Profit factor: `{summary['profit_factor']:.3f}`",
        f"- Expectancy per trade: `{summary['expectancy']:.4f}`",
        f"- Average R: `{summary.get('avg_r', 0):.3f}`",
        f"- Observation gate: **{pass_status}**",
        "",
        "## Daily Return Diagnostics",
        "",
    ]
    daily = summary.get("daily_return_stats", {})
    if daily:
        lines.extend(
            [
                f"- Target daily return: `{daily.get('target_min_pct', 5.0):.2f}%` to `{daily.get('target_max_pct', 7.0):.2f}%`",
                f"- Trading days: `{daily.get('trading_days', 0)}`",
                f"- Average daily return: `{daily.get('avg_daily_return_pct', 0.0):.3f}%`",
                f"- Median daily return: `{daily.get('median_daily_return_pct', 0.0):.3f}%`",
                f"- Best / worst daily return: `{daily.get('best_daily_return_pct', 0.0):.3f}%` / `{daily.get('worst_daily_return_pct', 0.0):.3f}%`",
                f"- 5%-7% target hit rate: `{daily.get('target_range_hit_rate_pct', 0.0):.2f}%`",
                f"- Days above 5%: `{daily.get('above_target_min_rate_pct', 0.0):.2f}%`",
                f"- Losing-day rate: `{daily.get('loss_day_rate_pct', 0.0):.2f}%`",
                "",
            ]
        )
    else:
        lines.extend(["No daily return diagnostics available.", ""])
    lines.extend(
        [
        "## Symbol Breakdown",
        "",
        ]
    )
    by_symbol = summary.get("by_symbol", {})
    if by_symbol:
        lines.append("| Symbol | Trades | Net PnL | Win Rate |")
        lines.append("|---|---:|---:|---:|")
        for symbol, item in by_symbol.items():
            lines.append(
                f"| {symbol} | {item['trades']} | {item['net_pnl']:.4f} | {item['win_rate_pct']:.2f}% |"
            )
    else:
        lines.append("No trades generated.")

    lines.extend(["", "## Data Quality", ""])
    lines.append("| Symbol | Rows | Missing Bars | First Bar | Last Bar |")
    lines.append("|---|---:|---:|---|---|")
    for symbol, item in summary.get("data_quality", {}).items():
        lines.append(
            f"| {symbol} | {item['rows']} | {item['missing_bars']} | {item['first_bar']} | {item['last_bar']} |"
        )

    lines.extend(["", "## Exit Reasons", ""])
    _append_stats_table(lines, summary.get("by_exit", {}), "Exit")

    lines.extend(["", "## Side Breakdown", ""])
    _append_stats_table(lines, summary.get("by_side", {}), "Side")

    lines.extend(["", "## Year Breakdown", ""])
    _append_stats_table(lines, summary.get("by_year", {}), "Year")

    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- This is a research-only backtest and paper-trading system.",
            "- Live order placement, API keys, leverage changes, and exchange account actions are intentionally out of scope.",
            "- Same-bar stop/target conflicts are resolved conservatively as stop-first.",
        ]
    )
    return "\n".join(lines) + "\n"


def _append_stats_table(lines: list[str], stats: dict, label: str) -> None:
    if not stats:
        lines.append("No data.")
        return
    lines.append(f"| {label} | Trades | Net PnL | Win Rate | Avg R |")
    lines.append("|---|---:|---:|---:|---:|")
    for key, item in stats.items():
        lines.append(
            f"| {key} | {item['trades']} | {item['net_pnl']:.4f} | "
            f"{item['win_rate_pct']:.2f}% | {item['avg_r']:.3f} |"
        )


def _pass_status(summary: dict) -> str:
    trade_count = summary.get("trade_count", 0)
    profit_factor = summary.get("profit_factor", 0)
    expectancy = summary.get("expectancy", 0)
    max_drawdown = abs(summary.get("max_drawdown_pct", 0))
    if trade_count >= 200 and profit_factor > 1.15 and expectancy > 0 and max_drawdown < 15:
        return "PASS"
    return "FAIL"


def _format_money(value: float) -> str:
    if abs(value) < 1:
        return f"{value:.6f}"
    return f"{value:.2f}"
