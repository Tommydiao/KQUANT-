"""Deterministic mathematical baselines for the DEV-only action panel."""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from typing import Any

import numpy as np

from .math_action_contract import CORE_SYMBOLS, canonical_hash


def _mature(rows: list[dict[str, Any]], partition: str | None = None) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["fill_status"] == "FILLED"
        and row["label_status"] == "MATURE"
        and (partition is None or row["partition"] == partition)
    ]


def _training_rows(rows: list[dict[str, Any]], stride_hours: int) -> list[dict[str, Any]]:
    return [
        row
        for row in _mature(rows, "DEVELOPMENT_TRAIN")
        if (row["signal_time"] // 3600) % stride_hours == 0
    ]


def fit_ridge_baseline(rows: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    features = list(contract["features"]["spot_long"])
    stride = int(contract["dataset"]["training_stride_hours"])
    train = _training_rows(rows, stride)
    if len(train) < len(features) + len(CORE_SYMBOLS) + 10:
        raise ValueError("Insufficient non-overlapping development rows")
    raw = np.asarray([[row["features"][name] for name in features] for row in train], dtype=float)
    mean = raw.mean(axis=0)
    scale = raw.std(axis=0)
    if not np.isfinite(raw).all() or not np.all(scale > 0):
        raise ValueError("Invalid feature transform")
    symbol_columns = list(CORE_SYMBOLS[1:])

    def matrix(source: list[dict[str, Any]]) -> np.ndarray:
        values = np.asarray([[row["features"][name] for name in features] for row in source], dtype=float)
        standardized = (values - mean) / scale
        dummies = np.asarray([[float(row["symbol"] == symbol) for symbol in symbol_columns] for row in source])
        return np.column_stack([np.ones(len(source)), standardized, dummies])

    x = matrix(train)
    y = np.asarray([row["net_r"] for row in train], dtype=float)
    penalty = float(contract["ridge_baseline"]["l2_penalty"])
    regularizer = np.eye(x.shape[1]) * penalty
    regularizer[0, 0] = 0.0
    coefficients = np.linalg.solve(x.T @ x + regularizer, x.T @ y)
    fitted = x @ coefficients
    artifact = {
        "version": "math_action_ridge_dev_v1.0.0",
        "scope": "DEV_ONLY",
        "exposure": "EXPOSED_RESEARCH",
        "runtime_enabled": False,
        "admission_enabled": False,
        "contract_hash": contract["contract_hash"],
        "feature_names": features,
        "symbol_columns": symbol_columns,
        "transform": {"mean": mean.tolist(), "scale": scale.tolist()},
        "coefficients": coefficients.tolist(),
        "l2_penalty": penalty,
        "training_stride_hours": stride,
        "training_rows": len(train),
        "training_signal_times": len({row["signal_time"] for row in train}),
        "training_panel_hash": canonical_hash([row["sample_id"] for row in train]),
        "in_sample_rmse": float(np.sqrt(np.mean((y - fitted) ** 2))),
        "claims": {
            "independent_oos": False,
            "calibrated_probability": False,
            "performance_gate_passed": False,
        },
    }
    artifact["artifact_hash"] = canonical_hash(artifact)
    return artifact


def predict_ridge(rows: list[dict[str, Any]], artifact: dict[str, Any]) -> list[dict[str, Any]]:
    expected_hash = artifact.get("artifact_hash")
    if expected_hash != canonical_hash({key: value for key, value in artifact.items() if key != "artifact_hash"}):
        raise ValueError("Ridge artifact hash mismatch")
    if artifact.get("scope") != "DEV_ONLY" or artifact.get("runtime_enabled") is not False:
        raise ValueError("Unsafe ridge artifact")
    features = artifact["feature_names"]
    mean = np.asarray(artifact["transform"]["mean"], dtype=float)
    scale = np.asarray(artifact["transform"]["scale"], dtype=float)
    beta = np.asarray(artifact["coefficients"], dtype=float)
    result = []
    for row in rows:
        values = np.asarray([row["features"][name] for name in features], dtype=float)
        vector = np.concatenate(
            ([1.0], (values - mean) / scale, [float(row["symbol"] == symbol) for symbol in artifact["symbol_columns"]])
        )
        result.append(
            {
                "sample_id": row["sample_id"],
                "signal_time": row["signal_time"],
                "symbol": row["symbol"],
                "action": row["action"],
                "partition": row["partition"],
                "predicted_net_r": float(vector @ beta),
                "model_version": artifact["version"],
                "model_artifact_hash": artifact["artifact_hash"],
                "decision_authority": "DEVELOPMENT_BASELINE_ONLY",
            }
        )
    return result


def action_diagnostics(
    rows: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    *,
    minimum_predicted_net_r: float = 0.0,
) -> dict[str, Any]:
    by_id = {row["sample_id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("Duplicate sample identity")
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for prediction in predictions:
        row = by_id[prediction["sample_id"]]
        if row["partition"] == "PURGED":
            continue
        grouped[(row["partition"], row["signal_time"])].append({**prediction, "row": row})

    selected = []
    waits: Counter[str] = Counter()
    for (partition, signal_time), candidates in sorted(grouped.items()):
        best = max(candidates, key=lambda item: (item["predicted_net_r"], -CORE_SYMBOLS.index(item["symbol"])))
        if best["predicted_net_r"] <= minimum_predicted_net_r:
            waits[partition] += 1
            continue
        selected_row = {
                "partition": partition,
                "signal_time": signal_time,
                "sample_id": best["sample_id"],
                "symbol": best["symbol"],
                "action": best["action"],
                "predicted_net_r": best["predicted_net_r"],
                "fill_status": best["row"]["fill_status"],
                "label_status": best["row"]["label_status"],
                "unavailable_reason": best["row"].get("unavailable_reason"),
            }
        if best["row"]["fill_status"] == "FILLED" and best["row"]["label_status"] == "MATURE":
            selected_row.update(
                realized_net_r=best["row"]["net_r"],
                exit_time=best["row"]["exit_time"],
                exit_reason=best["row"]["exit_reason"],
            )
        selected.append(selected_row)

    metrics = {}
    for partition in ("DEVELOPMENT_TRAIN", "DEVELOPMENT_VALIDATION", "DEVELOPMENT_DIAGNOSTIC"):
        partition_selected = [row for row in selected if row["partition"] == partition]
        values = [row["realized_net_r"] for row in partition_selected if "realized_net_r" in row]
        wins = [value for value in values if value > 0]
        losses = [value for value in values if value <= 0]
        gross_win = math.fsum(wins)
        gross_loss = -math.fsum(losses)
        metrics[partition] = {
            "selected_actions": len(values),
            "selected_without_mature_outcome": len(partition_selected) - len(values),
            "wait_actions": waits[partition],
            "mean_net_r": math.fsum(values) / len(values) if values else None,
            "win_rate": len(wins) / len(values) if values else None,
            "profit_factor": gross_win / gross_loss if gross_loss > 0 else None,
            "average_win_r": math.fsum(wins) / len(wins) if wins else None,
            "average_loss_r": math.fsum(losses) / len(losses) if losses else None,
            "payoff_ratio": (
                (math.fsum(wins) / len(wins)) / abs(math.fsum(losses) / len(losses))
                if wins and losses
                else None
            ),
        }
    return {
        "status": "DESCRIPTIVE_DEV_ONLY",
        "model_role": "mathematical_ridge_baseline",
        "action_rule": "choose highest predicted spot-long net R when prediction is above zero; otherwise wait",
        "independent_oos": False,
        "calibrated_probability": False,
        "portfolio_constraints_applied": False,
        "metrics": metrics,
        "selected": selected,
        "limits": [
            "All partitions are exposed development data; validation and diagnostic names are workflow labels, not OOS claims",
            "Hourly 24-hour labels overlap and action-level results are not a deployable portfolio backtest",
            "Ridge is a benchmark and has no authority to pass the Bayesian q05 action gate",
            "Perpetual short and WAIT opportunity cost are unavailable until a frozen Futures dataset exists",
        ],
    }


def replay_action_policy(
    rows: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    contract: dict[str, Any],
    *,
    score_field: str,
    eligibility_field: str | None = None,
    force_wait_reason: str | None = None,
) -> dict[str, Any]:
    """Replay math-selected actions with the frozen research cash/risk budget."""
    by_id = {row["sample_id"]: row for row in rows}
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for prediction in predictions:
        row = by_id[prediction["sample_id"]]
        if row["partition"] != "PURGED":
            grouped[row["signal_time"]].append({**prediction, "row": row})

    policy = contract["portfolio"]
    cash = float(policy["research_capital"])
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    loss_streak = 0
    pause_until = 0
    day_start_equity: dict[int, float] = {}
    realized_by_day: defaultdict[int, float] = defaultdict(float)
    equity_curve: list[dict[str, Any]] = []

    def equity(mark_prices: dict[str, float] | None = None) -> float:
        result = cash
        for position in positions:
            mark = (mark_prices or {}).get(position["symbol"], position["entry_price"])
            result += position["quantity"] * mark * (1.0 - position["fee_rate"])
        return result

    def close_due(now: int) -> None:
        nonlocal cash, loss_streak, pause_until
        due = sorted(
            [position for position in positions if position["exit_time"] <= now],
            key=lambda position: (position["exit_time"], CORE_SYMBOLS.index(position["symbol"])),
        )
        for position in due:
            positions.remove(position)
            cash += position["exit_credit"]
            realized_by_day[position["exit_time"] // 86400] += position["net_pnl"]
            loss_streak = loss_streak + 1 if position["net_pnl"] < 0 else 0
            if loss_streak >= int(policy["loss_streak"]):
                pause_until = max(pause_until, position["exit_time"] + int(policy["pause_hours"]) * 3600)
                loss_streak = 0
            trades.append(position)

    for signal_time, candidates in sorted(grouped.items()):
        close_due(signal_time)
        day = signal_time // 86400
        marks = {candidate["symbol"]: candidate["row"]["signal_reference"] for candidate in candidates}
        current_equity = equity(marks)
        day_start_equity.setdefault(day, current_equity)
        equity_curve.append({"time": signal_time, "equity": current_equity, "frequency": "hourly"})
        if force_wait_reason:
            events.append({"signal_time": signal_time, "action": "WAIT", "reason": force_wait_reason})
            continue
        eligible = [
            candidate
            for candidate in candidates
            if eligibility_field is None or bool(candidate.get(eligibility_field))
        ]
        if not eligible:
            events.append({"signal_time": signal_time, "action": "WAIT", "reason": "no_action_passed_math_gate"})
            continue
        best = max(
            eligible,
            key=lambda candidate: (candidate[score_field], -CORE_SYMBOLS.index(candidate["symbol"])),
        )
        if best[score_field] <= 0:
            events.append({"signal_time": signal_time, "action": "WAIT", "reason": "best_expected_net_r_not_positive"})
            continue
        if signal_time < pause_until:
            events.append({"signal_time": signal_time, "action": "WAIT", "reason": "loss_streak_pause"})
            continue
        if current_equity - day_start_equity[day] <= -day_start_equity[day] * float(policy["daily_loss_limit"]):
            events.append({"signal_time": signal_time, "action": "WAIT", "reason": "daily_loss_pause"})
            continue
        row = best["row"]
        if row["fill_status"] != "FILLED" or row["label_status"] != "MATURE":
            events.append({
                "signal_time": signal_time,
                "action": "WAIT",
                "reason": row.get("unavailable_reason") or "selected_outcome_not_mature",
                "selected_sample_id": row["sample_id"],
            })
            continue
        if any(position["symbol"] == row["symbol"] for position in positions):
            events.append({"signal_time": signal_time, "action": "WAIT", "reason": "symbol_already_exposed"})
            continue
        if len(positions) >= int(policy["max_positions"]):
            events.append({"signal_time": signal_time, "action": "WAIT", "reason": "position_limit"})
            continue
        current_equity = equity(marks)
        open_risk = sum(position["risk_amount"] for position in positions)
        risk_budget = min(
            current_equity * float(policy["risk_per_trade"]),
            current_equity * float(policy["max_open_risk"]) - open_risk,
        )
        quantity = min(
            max(risk_budget, 0.0) / row["base_r_per_unit"],
            current_equity * float(policy["max_symbol_notional"]) / row["entry_price"],
            cash / row["entry_price"],
        )
        if quantity <= 0:
            events.append({"signal_time": signal_time, "action": "WAIT", "reason": "risk_or_cash_unavailable"})
            continue
        notional = quantity * row["entry_price"]
        fee_rate = float(contract["costs"]["spot"]["fee_bps_per_side"]) / 10000.0
        entry_fee = quantity * row["entry_price"] * fee_rate
        exit_fee = quantity * row["exit_price"] * fee_rate
        exit_credit = quantity * row["exit_price"] - exit_fee
        risk_amount = quantity * row["base_r_per_unit"]
        net_pnl = quantity * row["net_pnl_per_unit"]
        cash -= notional + entry_fee
        position = {
            "sample_id": row["sample_id"],
            "partition": row["partition"],
            "symbol": row["symbol"],
            "action": row["action"],
            "signal_time": signal_time,
            "entry_time": signal_time,
            "exit_time": row["exit_time"],
            "exit_reason": row["exit_reason"],
            "score": best[score_field],
            "quantity": quantity,
            "notional": notional,
            "entry_price": row["entry_price"],
            "exit_price": row["exit_price"],
            "entry_fee": entry_fee,
            "exit_fee": exit_fee,
            "fee_rate": fee_rate,
            "exit_credit": exit_credit,
            "risk_amount": risk_amount,
            "net_pnl": net_pnl,
            "net_r": row["net_r"],
        }
        positions.append(position)
        events.append({"signal_time": signal_time, "action": row["action"], "sample_id": row["sample_id"]})
    close_due(max((position["exit_time"] for position in positions), default=0))

    partition_metrics = {}
    for partition in ("DEVELOPMENT_TRAIN", "DEVELOPMENT_VALIDATION", "DEVELOPMENT_DIAGNOSTIC"):
        selected = [trade for trade in trades if trade["partition"] == partition]
        wins = [trade["net_pnl"] for trade in selected if trade["net_pnl"] > 0]
        losses = [trade["net_pnl"] for trade in selected if trade["net_pnl"] <= 0]
        partition_metrics[partition] = {
            "trades": len(selected),
            "net_pnl": math.fsum(trade["net_pnl"] for trade in selected),
            "mean_net_r": math.fsum(trade["net_r"] for trade in selected) / len(selected) if selected else None,
            "win_rate": len(wins) / len(selected) if selected else None,
            "profit_factor": math.fsum(wins) / -math.fsum(losses) if losses and math.fsum(losses) < 0 else None,
        }
    return {
        "status": "DEV_ONLY_PORTFOLIO_REPLAY",
        "execution_enabled": False,
        "admission_enabled": False,
        "initial_cash": float(policy["research_capital"]),
        "final_cash": cash,
        "net_pnl": cash - float(policy["research_capital"]),
        "trades": trades,
        "events": events,
        "equity_curve": equity_curve,
        "metrics": partition_metrics,
        "limitations": [
            "Portfolio equity is marked hourly from contemporaneous signal references; a separate 5-minute replay is required for strict intrahour drawdown evidence",
            "All partitions are exposed development research and no OOS claim is made",
            "Replay cannot create execution intent, EVAL admission or exchange orders",
        ],
    }
