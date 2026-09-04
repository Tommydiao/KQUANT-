from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .backtest import TradeOutcome, summarize_outcomes
from .db.migrations import connect, migrate


def save_validation_run(
    db_path: Path,
    *,
    strategy_version: str,
    dataset_version: str,
    split_config: dict[str, Any],
    backtest_config: dict[str, Any],
    status: str,
    report: dict[str, Any],
    outcomes: Sequence[TradeOutcome],
    symbol: str = "",
    asset_id: str | None = None,
    partition_outcomes: Mapping[str, Sequence[TradeOutcome]] | None = None,
    oos_outcomes_by_fold: Mapping[int, Sequence[TradeOutcome]] | None = None,
) -> str:
    migrate(db_path)
    run_id = f"validation_{uuid4().hex}"
    now = datetime.now(UTC).isoformat()
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO crypto_validation_runs(run_id,strategy_version,dataset_version,split_config_json,backtest_config_json,status,report_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, strategy_version, dataset_version, json.dumps(split_config, ensure_ascii=True, sort_keys=True), json.dumps(backtest_config, ensure_ascii=True, sort_keys=True), status, json.dumps(report, ensure_ascii=True, sort_keys=True), now),
        )
        records: list[tuple[TradeOutcome, str, int | None]] = []
        if partition_outcomes:
            for partition in ("train", "validation", "test"):
                records.extend(
                    (outcome, partition, None)
                    for outcome in partition_outcomes.get(partition, ())
                )
            for partition, values in partition_outcomes.items():
                if partition not in {"train", "validation", "test"}:
                    records.extend((outcome, partition, None) for outcome in values)
        else:
            records.extend((outcome, "legacy", None) for outcome in outcomes)
        for fold, values in (oos_outcomes_by_fold or {}).items():
            records.extend((outcome, "oos_test", int(fold)) for outcome in values)
        for outcome, evidence_partition, oos_fold in records:
            conn.execute(
                "INSERT INTO crypto_validation_trades(trade_id,run_id,asset_id,symbol,signal_time,entry_time,exit_time,entry_price,exit_price,stop_price,target_price,realized_r,exit_reason,setup_score,factor_ids_json,evidence_partition,oos_fold,factor_values_json,market_type,direction,gross_r,trading_cost_r,funding_r) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"trade_{uuid4().hex}", run_id, outcome.asset_id or asset_id,
                    outcome.symbol or symbol, outcome.signal_time, outcome.entry_time,
                    outcome.exit_time, outcome.entry_price, outcome.exit_price,
                    outcome.stop_price, outcome.target_price, outcome.realized_r,
                    outcome.exit_reason, outcome.setup_score,
                    json.dumps(list(outcome.factor_ids), ensure_ascii=True), evidence_partition,
                    oos_fold, json.dumps(dict(outcome.factor_values), ensure_ascii=True, sort_keys=True),
                    outcome.market_type, outcome.direction, outcome.gross_r,
                    outcome.trading_cost_r, outcome.funding_r,
                ),
            )
    return run_id


def latest_validation_run(db_path: Path, strategy_version: str | None = None) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
        if strategy_version:
            row = conn.execute(
                "SELECT * FROM crypto_validation_runs WHERE strategy_version=? ORDER BY created_at DESC LIMIT 1",
                (strategy_version,),
            ).fetchone()
        else:
            row = conn.execute("SELECT * FROM crypto_validation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            return None
        value = dict(row)
        value["split_config"] = json.loads(value.pop("split_config_json"))
        value["backtest_config"] = json.loads(value.pop("backtest_config_json"))
        value["report"] = json.loads(value.pop("report_json"))
        trades = conn.execute("SELECT * FROM crypto_validation_trades WHERE run_id=? ORDER BY signal_time", (value["run_id"],)).fetchall()
    value["trades"] = []
    for row in trades:
        trade = dict(row)
        trade["factor_ids"] = json.loads(trade.pop("factor_ids_json"))
        trade["factor_values"] = json.loads(trade.pop("factor_values_json", "{}"))
        value["trades"].append(trade)
    return value


def latest_validation_gate_for_unit(
    db_path: Path,
    *,
    strategy_version: str,
    symbol: str,
    market_type: str,
    direction: str,
    minimum_unit_trades: int = 30,
) -> dict[str, Any] | None:
    """Return a fail-closed gate for one symbol/product/direction unit."""

    from .validation import evaluate_validation_gate

    run = latest_validation_run(db_path, strategy_version)
    if run is None:
        return None
    selected = [
        item for item in run["trades"]
        if item.get("evidence_partition") == "test"
        and str(item.get("symbol") or "").upper() == str(symbol).upper()
        and str(item.get("market_type") or "spot").lower() == str(market_type).lower()
        and str(item.get("direction") or "long").lower() == str(direction).lower()
    ]
    outcomes = [
        TradeOutcome(
            signal_time=str(item["signal_time"]), entry_time=str(item["entry_time"]), exit_time=str(item["exit_time"]),
            entry_price=float(item["entry_price"]), exit_price=float(item["exit_price"]),
            stop_price=float(item["stop_price"]), target_price=float(item["target_price"]),
            realized_r=float(item["realized_r"]), exit_reason=str(item["exit_reason"]),
            setup_score=float(item["setup_score"]), factor_ids=tuple(item.get("factor_ids") or ()),
            asset_id=item.get("asset_id"), symbol=str(item.get("symbol") or ""),
            factor_values=tuple((key, value) for key, value in (item.get("factor_values") or {}).items()),
            market_type=str(item.get("market_type") or "spot"), direction=str(item.get("direction") or "long"),
            gross_r=float(item["gross_r"]) if item.get("gross_r") is not None else None,
            trading_cost_r=float(item.get("trading_cost_r") or 0.0), funding_r=float(item.get("funding_r") or 0.0),
        )
        for item in selected
    ]
    summary = summarize_outcomes(outcomes, bootstrap_iterations=1000, bootstrap_seed=7)
    interval = summary.get("bootstrap_expected_r_interval_95") or ()
    lower = interval[0] if interval else None
    aggregate_gate = evaluate_validation_gate(run["report"])
    checks = {
        "aggregate_gate": aggregate_gate.get("status") == "PASS",
        "unit_trades": int(summary.get("sample_count") or 0) >= int(minimum_unit_trades),
        "bootstrap_expected_r": lower is not None and float(lower) > 0.0,
        "profit_factor": summary.get("profit_factor") is not None and float(summary["profit_factor"]) >= 1.25,
        "average_win_loss_ratio": summary.get("average_win_loss_ratio") is not None and float(summary["average_win_loss_ratio"]) >= 1.5,
        "max_drawdown": summary.get("max_drawdown_r") is not None and float(summary["max_drawdown_r"]) <= 10.0,
    }
    return {
        "status": "PASS" if all(checks.values()) else "NO_GO",
        "run_id": run["run_id"],
        "strategy_version": strategy_version,
        "symbol": str(symbol).upper(),
        "market_type": str(market_type).lower(),
        "direction": str(direction).lower(),
        "checks": checks,
        "failed_checks": [key for key, passed in checks.items() if not passed],
        "unit_summary": summary,
        "aggregate_gate": aggregate_gate,
    }
