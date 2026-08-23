from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .backtest import TradeOutcome
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
                "INSERT INTO crypto_validation_trades(trade_id,run_id,asset_id,symbol,signal_time,entry_time,exit_time,entry_price,exit_price,stop_price,target_price,realized_r,exit_reason,setup_score,factor_ids_json,evidence_partition,oos_fold,factor_values_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"trade_{uuid4().hex}", run_id, outcome.asset_id or asset_id, outcome.symbol or symbol, outcome.signal_time, outcome.entry_time, outcome.exit_time, outcome.entry_price, outcome.exit_price, outcome.stop_price, outcome.target_price, outcome.realized_r, outcome.exit_reason, outcome.setup_score, json.dumps(list(outcome.factor_ids), ensure_ascii=True), evidence_partition, oos_fold, json.dumps(dict(outcome.factor_values), ensure_ascii=True, sort_keys=True)),
            )
    return run_id


def latest_validation_run(db_path: Path) -> dict[str, Any] | None:
    migrate(db_path)
    with connect(db_path) as conn:
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
