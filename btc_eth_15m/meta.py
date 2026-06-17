from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from btc_eth_15m.config import AppConfig


FEATURES = [
    "signal_rsi",
    "signal_atr_pct",
    "signal_regime_atr_pct",
    "signal_volume_ratio",
    "signal_htf_gap_bps",
    "signal_distance_ema_mid_atr",
    "signal_hour_utc",
]


@dataclass(frozen=True)
class Rule:
    feature: str
    op: str
    threshold: float

    @property
    def label(self) -> str:
        return f"{self.feature} {self.op} {self.threshold:.6g}"


def write_meta_filter_report(config: AppConfig, run_id: str) -> Path:
    trades = _load_trades(config, run_id)
    summary = _load_summary(config, run_id)
    _validate_features(trades)
    result = walk_forward_meta_filter(trades)
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    csv_path = config.outputs_dir / f"{stamp}-{run_id}-meta-filter.csv"
    report_path = config.outputs_dir / f"{stamp}-{run_id}-meta-filter.md"
    result.to_csv(csv_path, index=False)
    report_path.write_text(_render_meta_report(run_id, summary, result, csv_path.name), encoding="utf-8")
    return report_path


def walk_forward_meta_filter(trades: pd.DataFrame) -> pd.DataFrame:
    data = trades.copy()
    data["entry_year"] = pd.to_datetime(data["entry_time"], utc=True).dt.year
    years = sorted(data["entry_year"].unique())
    rows = []
    for year in years[1:]:
        train = data[data["entry_year"] < year]
        test = data[data["entry_year"] == year]
        if train.empty or test.empty:
            continue
        rule = _best_rule(train)
        filtered = _apply_rule(test, rule)
        rows.append(
            {
                "test_year": int(year),
                "rule": rule.label,
                "train_trades": int(len(train)),
                "train_avg_r": float(_apply_rule(train, rule)["r_multiple"].mean()),
                "test_trades_all": int(len(test)),
                "test_avg_r_all": float(test["r_multiple"].mean()),
                "test_trades_kept": int(len(filtered)),
                "test_avg_r_kept": float(filtered["r_multiple"].mean()) if not filtered.empty else 0.0,
                "test_pf_kept": _profit_factor(filtered),
                "keep_rate_pct": float(len(filtered) / len(test) * 100) if len(test) else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _best_rule(train: pd.DataFrame) -> Rule:
    candidates = []
    min_trades = max(20, int(len(train) * 0.05))
    for feature in FEATURES:
        if feature not in train.columns:
            continue
        series = train[feature].dropna()
        if series.nunique() < 3:
            continue
        for quantile in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
            threshold = float(series.quantile(quantile))
            for op in ("<=", ">="):
                rule = Rule(feature, op, threshold)
                selected = _apply_rule(train, rule)
                if len(selected) < min_trades:
                    continue
                candidates.append(
                    (
                        float(selected["r_multiple"].mean()),
                        _profit_factor(selected),
                        len(selected),
                        rule,
                    )
                )
    if not candidates:
        return Rule("signal_rsi", ">=", float(train["signal_rsi"].median()))
    candidates.sort(key=lambda item: (item[0], item[1], -item[2]), reverse=True)
    return candidates[0][3]


def _apply_rule(frame: pd.DataFrame, rule: Rule) -> pd.DataFrame:
    if rule.op == "<=":
        return frame[frame[rule.feature] <= rule.threshold]
    if rule.op == ">=":
        return frame[frame[rule.feature] >= rule.threshold]
    raise ValueError(f"Unsupported rule op: {rule.op}")


def _profit_factor(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    wins = frame[frame["r_multiple"] > 0]["r_multiple"].sum()
    losses = abs(frame[frame["r_multiple"] < 0]["r_multiple"].sum())
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return float(wins / losses)


def _load_trades(config: AppConfig, run_id: str) -> pd.DataFrame:
    path = config.runs_dir / run_id / "trades.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing trades file: {path}")
    return pd.read_csv(path)


def _load_summary(config: AppConfig, run_id: str) -> dict:
    path = config.runs_dir / run_id / "summary.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing summary file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_features(trades: pd.DataFrame) -> None:
    missing = [feature for feature in FEATURES if feature not in trades.columns]
    if missing:
        raise ValueError(
            "Run does not include meta-filter feature columns. "
            "Rerun the target strategy after the feature-export update. "
            f"Missing: {', '.join(missing)}"
        )


def _render_meta_report(run_id: str, summary: dict, result: pd.DataFrame, csv_name: str) -> str:
    overall_all = result["test_avg_r_all"].mean() if not result.empty else 0.0
    overall_kept = result["test_avg_r_kept"].mean() if not result.empty else 0.0
    total_kept = int(result["test_trades_kept"].sum()) if not result.empty else 0
    total_all = int(result["test_trades_all"].sum()) if not result.empty else 0
    improves = overall_kept > overall_all and overall_kept > 0 and total_kept >= 100
    lines = [
        "# BTC/ETH 15m Meta-Filter Report",
        "",
        f"- Source run: `{run_id}`",
        f"- Strategy family: `{summary.get('strategy', {}).get('mode', 'unknown')}`",
        f"- Source trade count: `{summary.get('trade_count', 0)}`",
        f"- Result CSV: `{csv_name}`",
        f"- Walk-forward baseline Avg R: `{overall_all:.3f}`",
        f"- Walk-forward kept Avg R: `{overall_kept:.3f}`",
        f"- Kept trades: `{total_kept}/{total_all}`",
        f"- Meta-filter decision: **{'RESEARCHABLE' if improves else 'NOT READY'}**",
        "",
        "## Walk-Forward Results",
        "",
        "| Year | Rule | All Trades | All Avg R | Kept Trades | Kept Avg R | Kept PF | Keep Rate |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result.itertuples(index=False):
        lines.append(
            f"| {row.test_year} | `{row.rule}` | {row.test_trades_all} | {row.test_avg_r_all:.3f} | "
            f"{row.test_trades_kept} | {row.test_avg_r_kept:.3f} | {row.test_pf_kept:.3f} | {row.keep_rate_pct:.1f}% |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This is R-multiple feature triage, not an equity re-simulation.",
            "- A useful meta-filter must improve out-of-sample yearly Avg R and retain enough trades to be meaningful.",
            "- This layer does not place orders and does not call an external AI model.",
        ]
    )
    return "\n".join(lines) + "\n"

