from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from btc_eth_15m.config import AppConfig


def write_v2_report(config: AppConfig, sweep_csv: str | Path | None = None) -> Path:
    sweep_path = Path(sweep_csv) if sweep_csv else _latest_sweep_csv(config.outputs_dir)
    if not sweep_path.is_absolute():
        sweep_path = Path.cwd() / sweep_path
    sweep_rows = _read_sweep_rows(sweep_path)
    rows = []
    for row in sweep_rows:
        summary = _load_summary(config, str(row["run_id"]))
        strategy = summary.get("strategy", {})
        robust = _robustness(summary)
        daily = summary.get("daily_return_stats", {})
        rows.append(
            {
                "variant": row["variant"],
                "run_id": row["run_id"],
                "family": strategy.get("mode", "unknown"),
                "regime": strategy.get("regime_filter", "none"),
                "trades": int(summary["trade_count"]),
                "profit_factor": float(summary["profit_factor"]),
                "avg_r": float(summary["avg_r"]),
                "total_return_pct": float(summary["total_return_pct"]),
                "max_drawdown_pct": float(summary["max_drawdown_pct"]),
                "win_rate_pct": float(summary["win_rate_pct"]),
                "avg_daily_return_pct": float(daily.get("avg_daily_return_pct", 0.0)),
                "target_range_hit_rate_pct": float(daily.get("target_range_hit_rate_pct", 0.0)),
                "above_target_min_rate_pct": float(daily.get("above_target_min_rate_pct", 0.0)),
                "loss_day_rate_pct": float(daily.get("loss_day_rate_pct", 0.0)),
                **robust,
            }
        )

    rows.sort(key=lambda item: (item["avg_r"], item["profit_factor"]), reverse=True)
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    out_path = config.outputs_dir / f"{datetime.now(tz=UTC).strftime('%Y%m%dT%H%M%SZ')}-v2-research-report.md"
    out_path.write_text(_render_v2_markdown(rows, sweep_path), encoding="utf-8")
    return out_path


def _latest_sweep_csv(outputs_dir: Path) -> Path:
    candidates = sorted(outputs_dir.glob("*-sweep.csv"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No sweep CSV found under {outputs_dir}")
    return candidates[0]


def _read_sweep_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _load_summary(config: AppConfig, run_id: str) -> dict:
    path = config.runs_dir / run_id / "summary.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing run summary: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _robustness(summary: dict) -> dict:
    by_year = summary.get("by_year", {})
    by_symbol = summary.get("by_symbol", {})
    by_side = summary.get("by_side", {})
    year_avg = [float(item["avg_r"]) for item in by_year.values()]
    symbol_avg = [float(item["avg_r"]) for item in by_symbol.values()]
    side_avg = [float(item["avg_r"]) for item in by_side.values()]
    return {
        "positive_years": sum(value > 0 for value in year_avg),
        "year_count": len(year_avg),
        "worst_year_avg_r": min(year_avg) if year_avg else 0.0,
        "positive_symbols": sum(value > 0 for value in symbol_avg),
        "symbol_count": len(symbol_avg),
        "worst_symbol_avg_r": min(symbol_avg) if symbol_avg else 0.0,
        "positive_sides": sum(value > 0 for value in side_avg),
        "side_count": len(side_avg),
    }


def _render_v2_markdown(rows: list[dict[str, Any]], sweep_path: Path) -> str:
    if not rows:
        raise ValueError("Cannot render v2 report from an empty sweep.")
    best = rows[0]
    paper_ok = _paper_observation_ok(best)
    daily_target_ok = _daily_target_ok(best)
    ai_recommendation = _ai_recommendation(rows)
    families = _family_comparison(rows)

    lines = [
        "# BTC/ETH 15m v2 Research Report",
        "",
        f"- Source sweep: `{sweep_path.name}`",
        f"- Variants tested: `{len(rows)}`",
        f"- Strategy families: `{', '.join(sorted({row['family'] for row in rows}))}`",
        f"- Best variant: `{best['variant']}`",
        f"- Best PF / Avg R: `{best['profit_factor']:.3f}` / `{best['avg_r']:.3f}`",
        f"- Best max drawdown: `{best['max_drawdown_pct']:.2f}%`",
        f"- Best average daily return: `{best['avg_daily_return_pct']:.3f}%`",
        f"- Best 5%-7% daily hit rate: `{best['target_range_hit_rate_pct']:.2f}%`",
        f"- Daily target decision: **{'YES' if daily_target_ok else 'NO'}**",
        f"- Paper observation decision: **{'YES' if paper_ok else 'NO'}**",
        f"- AI/ML decision: **{ai_recommendation}**",
        "",
        "## Variant Ranking",
        "",
        "| Variant | Family | Regime | Trades | PF | Avg R | Avg Daily | 5%-7% Days | Loss Days | Return | Max DD | Positive Years | Run ID |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['variant']} | {row['family']} | {row['regime']} | {row['trades']} | "
            f"{row['profit_factor']:.3f} | {row['avg_r']:.3f} | {row['avg_daily_return_pct']:.3f}% | "
            f"{row['target_range_hit_rate_pct']:.2f}% | {row['loss_day_rate_pct']:.2f}% | "
            f"{row['total_return_pct']:.2f}% | {row['max_drawdown_pct']:.2f}% | "
            f"{row['positive_years']}/{row['year_count']} | `{row['run_id']}` |"
        )

    lines.extend(["", "## Family Comparison", ""])
    lines.append("| Family | Variants | Best Avg R | Best PF | Best Return |")
    lines.append("|---|---:|---:|---:|---:|")
    for family, row in families:
        lines.append(
            f"| {family} | {row['variants']} | {row['best_avg_r']:.3f} | "
            f"{row['best_pf']:.3f} | {row['best_return']:.2f}% |"
        )

    lines.extend(
        [
            "",
            "## Robustness Decision",
            "",
            "- A branch meets the requested daily target only if average daily return is between 5% and 7%, 5%-7% target hit rate is at least 50%, and loss-day rate is below 35%. This is intentionally strict because occasional 5% days do not prove a daily-income strategy.",
            "- A branch is only paper-observation eligible if it first meets the 5%-7% daily target gate, then also has PF > 1.05, Avg R > 0, max drawdown better than -25%, at least 3 yearly buckets positive, and non-negative symbol buckets.",
            f"- Best current branch has PF `{best['profit_factor']:.3f}`, Avg R `{best['avg_r']:.3f}`, max drawdown `{best['max_drawdown_pct']:.2f}%`, positive years `{int(best['positive_years'])}/{int(best['year_count'])}`, and positive symbols `{int(best['positive_symbols'])}/{int(best['symbol_count'])}`.",
            "- Therefore the v2 rule set is not approved for live trading or paper-observation automation yet.",
            "",
            "## Next Research Direction",
            "",
            "- Keep the best current ETH short branch as a session-filtered trend-pullback candidate, but add external/context features before more parameter tuning.",
            "- Useful next features: BTC 4H/1D trend state, session/time-of-day filter, realized volatility expansion, funding/OI if available, and symbol-relative strength.",
            "- AI/ML should not be used to place trades. It can be useful next as a meta-filter that scores rule-generated setups after the rule engine produces candidates.",
            "",
            "## Safety Boundary",
            "",
            "- This report is research-only.",
            "- No API keys, signed requests, leverage changes, order placement, or live exchange account actions are part of this system.",
        ]
    )
    return "\n".join(lines) + "\n"


def _family_comparison(rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        family = str(row["family"])
        current = grouped.setdefault(
            family,
            {"variants": 0, "best_avg_r": float("-inf"), "best_pf": float("-inf"), "best_return": float("-inf")},
        )
        current["variants"] += 1
        current["best_avg_r"] = max(current["best_avg_r"], float(row["avg_r"]))
        current["best_pf"] = max(current["best_pf"], float(row["profit_factor"]))
        current["best_return"] = max(current["best_return"], float(row["total_return_pct"]))
    return sorted(grouped.items(), key=lambda item: item[1]["best_avg_r"], reverse=True)


def _paper_observation_ok(best: dict) -> bool:
    return (
        _daily_target_ok(best)
        and best["profit_factor"] > 1.05
        and best["avg_r"] > 0
        and best["max_drawdown_pct"] > -25
        and best["positive_years"] >= 3
        and best["positive_symbols"] == best["symbol_count"]
    )


def _daily_target_ok(best: dict) -> bool:
    return (
        5.0 <= best["avg_daily_return_pct"] <= 7.0
        and best["target_range_hit_rate_pct"] >= 50.0
        and best["loss_day_rate_pct"] < 35.0
    )


def _ai_recommendation(rows: list[dict[str, Any]]) -> str:
    best = rows[0]
    if not _daily_target_ok(best):
        return "Do not add trade-execution AI yet; use ML only for feature triage/meta-filter research"
    if any(row["avg_r"] > 0 for row in rows) and any(row["profit_factor"] > 1.0 for row in rows):
        return "Use AI/ML only as a meta-filter after paper observation"
    return "Do not add trade-execution AI yet; use ML only for feature triage/meta-filter research"
