"""DEV-only research for flow persistence and market-residual trend hypotheses."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import gzip
import hashlib
import json
import math
from pathlib import Path
from statistics import pstdev
from typing import Any, Iterable

import numpy as np

from .hybrid_dataset_capsule import load_capsule
from .math_action_contract import CORE_SYMBOLS, canonical_hash, file_hash
from .math_action_dataset import _future_bars, _net_r_long


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "trend_evidence_research_v1.json"
HOUR = 3600


@dataclass(frozen=True)
class MicrostructureBar:
    quote_volume: float
    trade_count: int
    taker_buy_quote_volume: float
    source_hash: str


@dataclass
class EnrichedDataset:
    base: Any
    microstructure: dict[str, dict[int, MicrostructureBar]]
    content_hash: str
    audit: dict[str, Any]


def _require_finite(values: Iterable[float], message: str) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError(message)


def load_trend_contract(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    path = path.resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("scope") != "DEV_ONLY" or value.get("exposure") != "EXPOSED_RESEARCH":
        raise ValueError("Only exposed development research is permitted")
    if value.get("execution_enabled") is not False or value.get("admission_enabled") is not False:
        raise ValueError("Trend research cannot enable execution or admission")
    if tuple(value.get("universe", ())) != CORE_SYMBOLS:
        raise ValueError("Universe must remain BTC/ETH/SOL")
    candidates = value.get("candidates", [])
    expected = {"H1_FLOW_24H", "H1_FLOW_72H", "H2_RESIDUAL_24H", "H2_RESIDUAL_72H"}
    if len(candidates) != 4 or {item.get("id") for item in candidates} != expected:
        raise ValueError("Exactly four preregistered candidates are required")
    if {int(item.get("horizon_hours", 0)) for item in candidates} != {24, 72}:
        raise ValueError("Only 24H and 72H horizons are permitted")
    if value["trade_plan"].get("same_bar_collision") != "stop_first":
        raise ValueError("Stop-first collision policy is mandatory")
    if value["trade_plan"].get("entry_outside_plan") != "not_filled":
        raise ValueError("Entry-gap policy changed")
    if value["bayesian"].get("action_gate") != "posterior_q05_conditional_mean_gt_zero":
        raise ValueError("Bayesian gate changed")
    if value["targets"].get("legacy_10r_contract_resolved") is not False:
        raise ValueError("The unresolved legacy 10R gate must remain fail-closed")
    expected_claims = {
        "independent_oos": False,
        "calibrated_probability": False,
        "performance_gate_passed": False,
        "runtime_admission": False,
        "live_trading": False,
    }
    if value.get("claims") != expected_claims:
        raise ValueError("Research claims must remain fail-closed")
    result = dict(value)
    result["config_path"] = str(path)
    result["config_sha256"] = file_hash(path)
    result["contract_hash"] = canonical_hash(value)
    return result


def _resolve(contract: dict[str, Any], value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def _source_files(root: Path) -> list[str]:
    files: list[str] = []
    for symbol in CORE_SYMBOLS:
        files.extend(str(path) for path in sorted((root / f"symbol={symbol}").rglob("*.parquet")))
    if not files:
        raise ValueError(f"No raw Binance Spot files below {root}")
    return files


def load_enriched_dataset(contract: dict[str, Any]) -> EnrichedDataset:
    """Join immutable OHLCV capsule rows to native Binance hourly flow fields."""
    import duckdb

    capsule_path = _resolve(contract, contract["dataset"]["spot_capsule"])
    base = load_capsule(capsule_path)
    raw_root = _resolve(contract, contract["dataset"]["raw_spot_root"])
    files = _source_files(raw_root)
    warmup = int(base.manifest["window"]["warmup_start"])
    cutoff = int(base.cutoff)
    query = """
        SELECT symbol,
               CAST(epoch(CAST(source_time AS TIMESTAMPTZ)) AS BIGINT) AS start,
               CAST(json_extract_string(payload_json, '$.quote_volume') AS DOUBLE) AS quote_volume,
               CAST(json_extract_string(payload_json, '$.trade_count') AS BIGINT) AS trade_count,
               CAST(json_extract_string(payload_json, '$.taker_buy_quote_volume') AS DOUBLE) AS taker_buy_quote_volume,
               content_hash
        FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
        WHERE event_type = 'kline'
          AND market_type = 'spot'
          AND json_extract_string(payload_json, '$.interval') = '1h'
          AND CAST(source_time AS TIMESTAMPTZ) >= to_timestamp(?)
          AND CAST(source_time AS TIMESTAMPTZ) < to_timestamp(?)
        ORDER BY symbol, start, content_hash
    """
    with duckdb.connect(":memory:") as database:
        records = database.execute(query, [files, warmup, cutoff]).fetchall()

    grouped: defaultdict[tuple[str, int], list[tuple[float, int, float, str]]] = defaultdict(list)
    invalid = Counter()
    for symbol, start, quote_volume, trade_count, taker_quote, source_hash in records:
        if symbol not in CORE_SYMBOLS:
            continue
        try:
            values = (float(quote_volume), int(trade_count), float(taker_quote), str(source_hash))
            if not all(math.isfinite(value) for value in (values[0], values[2])):
                raise ValueError("non_finite")
            if values[0] <= 0 or values[1] <= 0 or not 0 <= values[2] <= values[0]:
                raise ValueError("invalid_range")
        except (TypeError, ValueError):
            invalid["invalid_native_flow_row"] += 1
            continue
        grouped[(symbol, int(start))].append(values)

    microstructure: dict[str, dict[int, MicrostructureBar]] = {symbol: {} for symbol in CORE_SYMBOLS}
    exact_duplicates = 0
    conflicts = []
    missing = []
    for symbol in CORE_SYMBOLS:
        expected = {bar.start for bar in base.bars[symbol]["1h"]}
        for stamp in sorted(expected):
            values = grouped.get((symbol, stamp), [])
            unique = {(quote, count, taker) for quote, count, taker, _ in values}
            if not values:
                missing.append((symbol, stamp))
                continue
            if len(unique) != 1:
                conflicts.append((symbol, stamp))
                continue
            exact_duplicates += max(0, len(values) - 1)
            quote, count, taker = next(iter(unique))
            hashes = sorted({item[3] for item in values})
            microstructure[symbol][stamp] = MicrostructureBar(
                quote_volume=quote,
                trade_count=count,
                taker_buy_quote_volume=taker,
                source_hash=canonical_hash(hashes),
            )
    if conflicts:
        raise ValueError(f"Conflicting native flow rows: {conflicts[:3]}")
    if missing:
        raise ValueError(f"Missing native flow rows: {missing[:3]} ({len(missing)} total)")

    identity = {
        "base_dataset_hash": base.content_hash,
        "flow_rows": {
            symbol: {
                str(stamp): {
                    "quote_volume": bar.quote_volume,
                    "trade_count": bar.trade_count,
                    "taker_buy_quote_volume": bar.taker_buy_quote_volume,
                    "source_hash": bar.source_hash,
                }
                for stamp, bar in sorted(microstructure[symbol].items())
            }
            for symbol in CORE_SYMBOLS
        },
    }
    content_hash = canonical_hash(identity)
    audit = {
        "scope": "DEV_ONLY_EXPOSED_RESEARCH",
        "base_dataset_hash": base.content_hash,
        "enriched_dataset_hash": content_hash,
        "symbols": list(CORE_SYMBOLS),
        "rows": {symbol: len(microstructure[symbol]) for symbol in CORE_SYMBOLS},
        "raw_records_read": len(records),
        "exact_duplicates_collapsed": exact_duplicates,
        "invalid_rows_excluded": dict(invalid),
        "conflicting_timestamps": len(conflicts),
        "missing_timestamps": len(missing),
        "native_fields": ["quote_volume", "trade_count", "taker_buy_quote_volume"],
        "availability": "historical_bar_close_proxy_not_live_receipt_evidence",
        "interpretation": "Aggressor imbalance measures taker participation, not wallet identity or capital inflow",
    }
    return EnrichedDataset(base=base, microstructure=microstructure, content_hash=content_hash, audit=audit)


def _candidate_features(
    symbol: str,
    index: int,
    closes: dict[str, list[float]],
    returns: dict[str, list[float]],
    flows: dict[str, list[MicrostructureBar]],
    market_returns_by_symbol: dict[str, list[float]],
) -> dict[str, float]:
    recent = slice(index - 5, index + 1)
    prior = slice(index - 11, index - 5)
    quote_recent = math.fsum(bar.quote_volume for bar in flows[symbol][recent])
    quote_prior = math.fsum(bar.quote_volume for bar in flows[symbol][prior])
    taker_recent = math.fsum(bar.taker_buy_quote_volume for bar in flows[symbol][recent])
    taker_prior = math.fsum(bar.taker_buy_quote_volume for bar in flows[symbol][prior])
    trades_recent = math.fsum(bar.trade_count for bar in flows[symbol][recent])
    trades_prior = math.fsum(bar.trade_count for bar in flows[symbol][prior])
    imbalance_recent = (2.0 * taker_recent - quote_recent) / quote_recent
    imbalance_prior = (2.0 * taker_prior - quote_prior) / quote_prior
    return_6h = math.log(closes[symbol][index] / closes[symbol][index - 6])
    return_24h = math.log(closes[symbol][index] / closes[symbol][index - 24])
    realized_24h = pstdev(returns[symbol][index - 23 : index + 1]) * math.sqrt(24.0)

    market_returns = market_returns_by_symbol[symbol]
    beta_symbol = np.asarray(returns[symbol][index - 173 : index - 5], dtype=float)
    beta_market = np.asarray(market_returns[index - 173 : index - 5], dtype=float)
    market_variance = float(np.var(beta_market))
    beta = float(np.cov(beta_symbol, beta_market, ddof=0)[0, 1] / market_variance) if market_variance > 0 else 0.0
    residual_history = beta_symbol - beta * beta_market
    recent_residuals = [returns[symbol][offset] - beta * market_returns[offset] for offset in range(index - 5, index + 1)]
    prior_residuals = [returns[symbol][offset] - beta * market_returns[offset] for offset in range(index - 11, index - 5)]
    residual_scale = float(np.std(residual_history))
    residual_return = math.fsum(recent_residuals)
    features = {
        "aggressor_imbalance_6h": imbalance_recent,
        "aggressor_imbalance_change_6h": imbalance_recent - imbalance_prior,
        "quote_volume_log_acceleration_6h": math.log(quote_recent / quote_prior),
        "trade_count_log_acceleration_6h": math.log(trades_recent / trades_prior),
        "log_return_6h": return_6h,
        "return_overextension_24h": return_24h / max(realized_24h, 1e-12),
        "residual_return_6h": residual_return,
        "residual_acceleration_6h": residual_return - math.fsum(prior_residuals),
        "residual_strength_z_6h": residual_return / max(residual_scale * math.sqrt(6.0), 1e-12),
        "market_log_return_6h": math.fsum(market_returns[index - 5 : index + 1]),
        "realized_volatility_24h": realized_24h,
        "trailing_market_beta_168h": beta,
    }
    _require_finite(features.values(), "Non-finite trend feature")
    return features


def build_candidate_panel(
    dataset: EnrichedDataset,
    contract: dict[str, Any],
    *,
    cost_multiplier: float = 1.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if cost_multiplier <= 0:
        raise ValueError("Cost multiplier must be positive")
    hourly = {
        symbol: {bar.start: bar for bar in dataset.base.bars[symbol]["1h"]}
        for symbol in CORE_SYMBOLS
    }
    five = {
        symbol: {bar.start: bar for bar in dataset.base.bars[symbol]["5m"]}
        for symbol in CORE_SYMBOLS
    }
    common_starts = sorted(set.intersection(*(set(hourly[symbol]) for symbol in CORE_SYMBOLS)))
    for previous, current in zip(common_starts, common_starts[1:]):
        if current != previous + HOUR:
            raise ValueError("Hourly history is not continuous")
    warmup = int(contract["dataset"]["feature_warmup_hours"])
    if len(common_starts) <= warmup:
        raise ValueError("Insufficient synchronized history")
    research_start = int(dataset.base.manifest["window"]["start"])
    closes = {symbol: [hourly[symbol][stamp].close for stamp in common_starts] for symbol in CORE_SYMBOLS}
    returns = {
        symbol: [math.nan]
        + [math.log(values[index] / values[index - 1]) for index in range(1, len(values))]
        for symbol, values in closes.items()
    }
    flows = {
        symbol: [dataset.microstructure[symbol][stamp] for stamp in common_starts]
        for symbol in CORE_SYMBOLS
    }
    market_returns_by_symbol = {
        symbol: [
            math.nan
            if offset == 0
            else math.fsum(returns[item][offset] for item in CORE_SYMBOLS if item != symbol)
            / (len(CORE_SYMBOLS) - 1)
            for offset in range(len(common_starts))
        ]
        for symbol in CORE_SYMBOLS
    }
    fee = float(contract["costs"]["spot"]["fee_bps_per_side"]) * cost_multiplier / 10000.0
    slippage = float(contract["costs"]["spot"]["slippage_bps_per_side"]) * cost_multiplier / 10000.0
    stop_multiple = float(contract["trade_plan"]["stop_sigma_24h"])
    target_multiple = float(contract["trade_plan"]["target_sigma_24h"])
    rows: list[dict[str, Any]] = []
    counts = Counter()
    for index in range(warmup, len(common_starts)):
        signal_time = common_starts[index] + HOUR
        if signal_time < research_start:
            continue
        for symbol in CORE_SYMBOLS:
            all_features = _candidate_features(
                symbol,
                index,
                closes,
                returns,
                flows,
                market_returns_by_symbol,
            )
            sigma_24h = pstdev(returns[symbol][index - 167 : index + 1]) * math.sqrt(24.0)
            reference = closes[symbol][index]
            stop = reference * math.exp(-stop_multiple * sigma_24h)
            target = reference * math.exp(target_multiple * sigma_24h)
            for candidate in contract["candidates"]:
                horizon = int(candidate["horizon_hours"])
                if signal_time + horizon * HOUR > dataset.base.cutoff:
                    continue
                future, path_complete = _future_bars(five[symbol], signal_time, horizon)
                outcome = _net_r_long(
                    future,
                    stop=stop,
                    target=target,
                    fee=fee,
                    slippage=slippage,
                    horizon_end=signal_time + horizon * HOUR,
                    path_complete=path_complete,
                )
                identity = {
                    "enriched_dataset_hash": dataset.content_hash,
                    "contract_hash": contract["contract_hash"],
                    "candidate_id": candidate["id"],
                    "symbol": symbol,
                    "signal_time": signal_time,
                }
                selected_features = {name: all_features[name] for name in candidate["features"]}
                row = {
                    "sample_id": canonical_hash(identity),
                    **identity,
                    "hypothesis": candidate["hypothesis"],
                    "horizon_hours": horizon,
                    "cost_multiplier": cost_multiplier,
                    "market_type": "spot",
                    "direction": "long",
                    "action": f"SPOT_LONG_{symbol}",
                    "feature_snapshot_frozen_at": signal_time,
                    "feature_availability_basis": "assumed_close_historical_replay",
                    "features": selected_features,
                    "feature_context": {
                        "trailing_market_beta_168h": all_features["trailing_market_beta_168h"]
                    },
                    "signal_reference": reference,
                    "sigma_24h": sigma_24h,
                    "stop": stop,
                    "target": target,
                    "label_horizon_end": signal_time + horizon * HOUR,
                    "label_available_at": outcome.get("exit_time", signal_time + horizon * HOUR),
                    "label_execution_policy_id": (
                        f"SPOT_NEXT_5M_OPEN_STOP1SIGMA_TARGET2SIGMA_{horizon}H_"
                        f"COST_X{cost_multiplier:g}_V1"
                    ),
                    "evidence_scope": "DEV_ONLY_EXPOSED_RESEARCH",
                    "independent_oos": False,
                    **outcome,
                }
                row["feature_snapshot_hash"] = canonical_hash(
                    {"identity": identity, "features": selected_features, "as_of": signal_time}
                )
                rows.append(row)
                counts[f"{candidate['id']}:{outcome['fill_status']}:{outcome['label_status']}"] += 1
    audit = {
        **dataset.audit,
        "contract_hash": contract["contract_hash"],
        "cost_multiplier": cost_multiplier,
        "rows": len(rows),
        "unique_signal_times": len({row["signal_time"] for row in rows}),
        "research_start": research_start,
        "first_signal_time": min((row["signal_time"] for row in rows), default=None),
        "last_signal_time": max((row["signal_time"] for row in rows), default=None),
        "status_counts": dict(counts),
        "limits": [
            "All observations are exposed development evidence, not independent OOS",
            "Hourly candidate labels overlap; portfolio trades and synchronized time blocks are the reporting units",
            "Historical availability is assumed at bar close and is not strict quote evidence",
            "Native aggressor fields identify taker side, not wallet ownership or causal capital flow",
        ],
    }
    audit["panel_hash"] = canonical_hash(rows)
    return rows, audit


def write_rows(path: Path, rows: list[dict[str, Any]]) -> str:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows)
    path.write_bytes(gzip.compress(payload.encode("utf-8"), mtime=0))
    return canonical_hash(rows)


def read_rows(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if len({row["sample_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate candidate sample identity")
    return rows


def walk_forward_folds(rows: list[dict[str, Any]], contract: dict[str, Any]) -> list[dict[str, int]]:
    times = sorted({row["signal_time"] for row in rows})
    settings = contract["walk_forward"]
    fold_count = int(settings["folds"])
    first = float(settings["first_evaluation_fraction"])
    width = float(settings["evaluation_fraction"])
    purge = int(settings["purge_hours"]) * HOUR
    embargo = int(settings["embargo_hours"]) * HOUR
    maximum_horizon = max(int(item["horizon_hours"]) for item in contract["candidates"]) * HOUR
    result = []
    for index in range(fold_count):
        evaluation_index = min(len(times) - 1, int(len(times) * (first + index * width)))
        end_index = min(len(times), int(len(times) * (first + (index + 1) * width)))
        if end_index <= evaluation_index:
            raise ValueError("Invalid walk-forward window")
        evaluation_start = times[evaluation_index]
        evaluation_end = times[end_index - 1] + HOUR
        result.append(
            {
                "fold": index + 1,
                "training_start": times[0],
                "training_end_exclusive": evaluation_start - purge,
                "evaluation_start": evaluation_start + embargo,
                "evaluation_end_exclusive": evaluation_end,
                "last_entry_time_exclusive": evaluation_end - maximum_horizon,
            }
        )
    if any(item["training_end_exclusive"] <= item["training_start"] for item in result):
        raise ValueError("Walk-forward training window is empty")
    if any(item["last_entry_time_exclusive"] <= item["evaluation_start"] for item in result):
        raise ValueError("Walk-forward evaluation window is empty after horizon reserve")
    return result


def fit_ridge_fold(
    rows: list[dict[str, Any]],
    candidate: dict[str, Any],
    fold: dict[str, int],
    contract: dict[str, Any],
    *,
    feature_names: list[str] | None = None,
) -> dict[str, Any]:
    feature_names = list(feature_names or candidate["features"])
    horizon = int(candidate["horizon_hours"])
    anchor = int(fold["training_start"])
    train = [
        row
        for row in rows
        if row["candidate_id"] == candidate["id"]
        and fold["training_start"] <= row["signal_time"] < fold["training_end_exclusive"]
        and row["fill_status"] == "FILLED"
        and row["label_status"] == "MATURE"
        and ((row["signal_time"] - anchor) // HOUR) % horizon == 0
    ]
    if len(train) < len(feature_names) + len(CORE_SYMBOLS) + 10:
        raise ValueError(f"Insufficient training rows for {candidate['id']} fold {fold['fold']}")
    raw = np.asarray([[row["features"][name] for name in feature_names] for row in train], dtype=float)
    mean, scale = raw.mean(axis=0), raw.std(axis=0)
    if not np.isfinite(raw).all() or not np.all(scale > 0):
        raise ValueError("Invalid fold feature transform")
    standardized = (raw - mean) / scale
    symbol_columns = list(CORE_SYMBOLS[1:])
    dummies = np.asarray(
        [[float(row["symbol"] == symbol) for symbol in symbol_columns] for row in train], dtype=float
    )
    matrix = np.column_stack([np.ones(len(train)), standardized, dummies])
    outcome = np.asarray([row["net_r"] for row in train], dtype=float)
    penalty = float(contract["ridge"]["l2_penalty"])
    regularizer = np.eye(matrix.shape[1]) * penalty
    regularizer[0, 0] = 0.0
    coefficients = np.linalg.solve(matrix.T @ matrix + regularizer, matrix.T @ outcome)
    artifact = {
        "version": "trend_evidence_ridge_dev_v1.0.0",
        "scope": "DEV_ONLY_EXPOSED_RESEARCH",
        "runtime_enabled": False,
        "candidate_id": candidate["id"],
        "fold": fold,
        "contract_hash": contract["contract_hash"],
        "feature_names": feature_names,
        "symbol_columns": symbol_columns,
        "transform": {"mean": mean.tolist(), "scale": scale.tolist()},
        "coefficients": coefficients.tolist(),
        "l2_penalty": penalty,
        "training_rows": len(train),
        "training_signal_times": len({row["signal_time"] for row in train}),
        "training_panel_hash": canonical_hash([row["sample_id"] for row in train]),
        "in_sample_rmse": float(np.sqrt(np.mean((matrix @ coefficients - outcome) ** 2))),
        "claims": {"independent_oos": False, "performance_gate_passed": False},
    }
    artifact["artifact_hash"] = canonical_hash(artifact)
    return artifact


def predict_ridge_fold(
    rows: list[dict[str, Any]], artifact: dict[str, Any]
) -> list[dict[str, Any]]:
    expected = canonical_hash({key: value for key, value in artifact.items() if key != "artifact_hash"})
    if artifact.get("artifact_hash") != expected or artifact.get("runtime_enabled") is not False:
        raise ValueError("Unsafe or corrupt trend Ridge artifact")
    fold = artifact["fold"]
    evaluation = [
        row
        for row in rows
        if row["candidate_id"] == artifact["candidate_id"]
        and fold["evaluation_start"] <= row["signal_time"] < fold["last_entry_time_exclusive"]
    ]
    feature_names = artifact["feature_names"]
    mean = np.asarray(artifact["transform"]["mean"], dtype=float)
    scale = np.asarray(artifact["transform"]["scale"], dtype=float)
    coefficients = np.asarray(artifact["coefficients"], dtype=float)
    result = []
    for row in evaluation:
        values = np.asarray([row["features"][name] for name in feature_names], dtype=float)
        vector = np.concatenate(
            ([1.0], (values - mean) / scale, [float(row["symbol"] == item) for item in artifact["symbol_columns"]])
        )
        result.append(
            {
                "sample_id": row["sample_id"],
                "candidate_id": row["candidate_id"],
                "fold": fold["fold"],
                "signal_time": row["signal_time"],
                "symbol": row["symbol"],
                "predicted_net_r": float(vector @ coefficients),
                "passes_research_gate": bool(vector @ coefficients > 0.0),
                "model_artifact_hash": artifact["artifact_hash"],
                "decision_authority": "DEV_RIDGE_BASELINE_ONLY",
            }
        )
    return result


def run_ridge_walk_forward(rows: list[dict[str, Any]], contract: dict[str, Any]) -> dict[str, Any]:
    folds = walk_forward_folds(rows, contract)
    artifacts = []
    predictions = []
    ablations = []
    ablation_predictions = []
    for candidate in contract["candidates"]:
        for fold in folds:
            artifact = fit_ridge_fold(rows, candidate, fold, contract)
            artifacts.append(artifact)
            predictions.extend(predict_ridge_fold(rows, artifact))
            ablation = fit_ridge_fold(
                rows,
                candidate,
                fold,
                contract,
                feature_names=list(candidate["ablation_features"]),
            )
            ablations.append(ablation)
            ablation_predictions.extend(predict_ridge_fold(rows, ablation))
    result = {
        "status": "DEV_ONLY_EXPOSED_RESEARCH",
        "contract_hash": contract["contract_hash"],
        "folds": folds,
        "artifacts": artifacts,
        "ablation_artifacts": ablations,
        "ablation_predictions": ablation_predictions,
        "predictions": predictions,
        "claims": {"independent_oos": False, "calibrated_probability": False},
    }
    result["result_hash"] = canonical_hash(result)
    return result


def _performance_metrics(trades: list[dict[str, Any]], equity_curve: list[dict[str, Any]]) -> dict[str, Any]:
    r_values = [float(trade["net_r"]) for trade in trades]
    pnl_values = [float(trade["net_pnl"]) for trade in trades]
    wins_r = [value for value in r_values if value > 0]
    losses_r = [value for value in r_values if value <= 0]
    wins_pnl = [value for value in pnl_values if value > 0]
    losses_pnl = [value for value in pnl_values if value <= 0]
    equities = [float(point["equity"]) for point in equity_curve]
    peak = -math.inf
    maximum_drawdown = 0.0
    for value in equities:
        peak = max(peak, value)
        if peak > 0:
            maximum_drawdown = max(maximum_drawdown, (peak - value) / peak)
    return {
        "trades": len(trades),
        "mean_net_r": math.fsum(r_values) / len(r_values) if r_values else None,
        "win_rate": len(wins_r) / len(r_values) if r_values else None,
        "average_win_r": math.fsum(wins_r) / len(wins_r) if wins_r else None,
        "average_loss_r": math.fsum(losses_r) / len(losses_r) if losses_r else None,
        "payoff_r": (
            (math.fsum(wins_r) / len(wins_r)) / abs(math.fsum(losses_r) / len(losses_r))
            if wins_r and losses_r
            else None
        ),
        "profit_factor_r": math.fsum(wins_r) / -math.fsum(losses_r) if losses_r and math.fsum(losses_r) < 0 else None,
        "profit_factor_pnl": (
            math.fsum(wins_pnl) / -math.fsum(losses_pnl)
            if losses_pnl and math.fsum(losses_pnl) < 0
            else None
        ),
        "net_pnl": math.fsum(pnl_values),
        "maximum_drawdown_fraction": maximum_drawdown if equities else None,
    }


def replay_candidate_fold(
    rows: list[dict[str, Any]],
    predictions: list[dict[str, Any]],
    dataset: EnrichedDataset,
    fold: dict[str, int],
    contract: dict[str, Any],
    *,
    timeline_mode: str = "full_5m",
    runtime_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Event-driven 5-minute paper replay; selection never reads a future label."""
    if timeline_mode not in {"full_5m", "decision_events"}:
        raise ValueError(f"Unknown replay timeline mode: {timeline_mode}")
    by_id = {row["sample_id"]: row for row in rows}
    grouped: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    for prediction in predictions:
        if int(prediction["fold"]) != int(fold["fold"]):
            continue
        row = by_id[prediction["sample_id"]]
        grouped[row["signal_time"]].append({**prediction, "row": row})
    runtime_cache = runtime_cache if runtime_cache is not None else {}
    bars = runtime_cache.get("five_minute_bars")
    if bars is None:
        bars = {
            symbol: {bar.start: bar for bar in dataset.base.bars[symbol]["5m"]}
            for symbol in CORE_SYMBOLS
        }
        runtime_cache["five_minute_bars"] = bars
    policy = contract["portfolio"]
    cost_multiplier = float(rows[0].get("cost_multiplier", 1.0)) if rows else 1.0
    fee_rate = (
        float(contract["costs"]["spot"]["fee_bps_per_side"])
        * cost_multiplier
        / 10000.0
    )
    cash = float(policy["research_capital"])
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    last_marks: dict[str, float] = {}
    day_start_equity: dict[int, float] = {}
    loss_streak = 0
    pause_until = 0

    def equity() -> float:
        return cash + math.fsum(
            position["quantity"] * last_marks.get(position["symbol"], position["entry_price"])
            * (1.0 - fee_rate)
            for position in positions
        )

    def close_due(now: int) -> None:
        nonlocal cash, loss_streak, pause_until
        due = sorted(
            (position for position in positions if position["exit_time"] <= now),
            key=lambda item: (item["exit_time"], CORE_SYMBOLS.index(item["symbol"])),
        )
        for position in due:
            positions.remove(position)
            cash += position["exit_credit"]
            loss_streak = loss_streak + 1 if position["net_pnl"] < 0 else 0
            if loss_streak >= int(policy["loss_streak"]):
                pause_until = max(
                    pause_until,
                    position["exit_time"] + int(policy["pause_hours"]) * HOUR,
                )
                loss_streak = 0
            trades.append(position)
            events.append(
                {
                    "time": position["exit_time"],
                    "event": "EXIT",
                    "sample_id": position["sample_id"],
                    "reason": position["exit_reason"],
                }
            )

    start = int(fold["evaluation_start"])
    end = int(fold["evaluation_end_exclusive"])
    if timeline_mode == "decision_events":
        stamps = set(grouped)
        stamps.update(
            int(item["row"]["exit_time"])
            for values in grouped.values()
            for item in values
            if start <= int(item["row"]["exit_time"]) < end
        )
        first_day = start // 86400
        last_day = (end - 1) // 86400
        stamps.update(day * 86400 for day in range(first_day, last_day + 1) if start <= day * 86400 < end)
        stamps.add(end - 300)
        timeline = sorted(stamp for stamp in stamps if start <= stamp < end)
    else:
        timeline = range(start, end, 300)
    for stamp in timeline:
        current_bars = {symbol: bars[symbol].get(stamp) for symbol in CORE_SYMBOLS}
        if any(bar is None for bar in current_bars.values()):
            events.append({"time": stamp, "event": "DATA_GAP", "reason": "missing_synchronized_5m_bar"})
            continue
        for symbol, bar in current_bars.items():
            last_marks.setdefault(symbol, bar.open)
        close_due(stamp)
        day = stamp // 86400
        day_start_equity.setdefault(day, equity())
        if stamp in grouped:
            candidates = sorted(
                grouped[stamp],
                key=lambda item: (float(item["predicted_net_r"]), -CORE_SYMBOLS.index(item["symbol"])),
                reverse=True,
            )
            passing = [item for item in candidates if bool(item.get("passes_research_gate"))]
            if not passing:
                events.append({"time": stamp, "event": "WAIT", "reason": "no_positive_expected_net_r"})
            else:
                best = passing[0]
                row = best["row"]
                blocked = None
                if stamp >= int(fold["last_entry_time_exclusive"]):
                    blocked = "fold_terminal_reserve"
                elif stamp < pause_until:
                    blocked = "loss_streak_pause"
                elif equity() - day_start_equity[day] <= -day_start_equity[day] * float(policy["daily_loss_limit"]):
                    blocked = "daily_loss_pause"
                elif any(item["symbol"] == row["symbol"] for item in positions):
                    blocked = "symbol_already_exposed"
                elif len(positions) >= int(policy["max_positions"]):
                    blocked = "position_limit"
                elif row["fill_status"] != "FILLED" or row["label_status"] != "MATURE":
                    blocked = row.get("unavailable_reason") or "selected_label_not_mature"
                if blocked:
                    events.append(
                        {"time": stamp, "event": "WAIT", "reason": blocked, "selected_sample_id": row["sample_id"]}
                    )
                else:
                    current_equity = equity()
                    open_risk = math.fsum(item["risk_amount"] for item in positions)
                    risk_budget = min(
                        current_equity * float(policy["risk_per_trade"]),
                        current_equity * float(policy["max_open_risk"]) - open_risk,
                    )
                    entry_price = float(row["entry_price"])
                    quantity = min(
                        max(risk_budget, 0.0) / float(row["base_r_per_unit"]),
                        current_equity * float(policy["max_symbol_notional"]) / entry_price,
                        cash / (entry_price * (1.0 + fee_rate)),
                    )
                    if quantity <= 0:
                        events.append({"time": stamp, "event": "WAIT", "reason": "risk_or_cash_unavailable"})
                    else:
                        entry_fee = quantity * entry_price * fee_rate
                        exit_price = float(row["exit_price"])
                        exit_fee = quantity * exit_price * fee_rate
                        net_pnl = quantity * float(row["net_pnl_per_unit"])
                        cash -= quantity * entry_price + entry_fee
                        position = {
                            "sample_id": row["sample_id"],
                            "candidate_id": row["candidate_id"],
                            "fold": fold["fold"],
                            "symbol": row["symbol"],
                            "signal_time": stamp,
                            "entry_time": stamp,
                            "entry_price": entry_price,
                            "exit_time": int(row["exit_time"]),
                            "exit_price": exit_price,
                            "exit_reason": row["exit_reason"],
                            "quantity": quantity,
                            "entry_fee": entry_fee,
                            "exit_fee": exit_fee,
                            "exit_credit": quantity * exit_price - exit_fee,
                            "risk_amount": quantity * float(row["base_r_per_unit"]),
                            "net_pnl": net_pnl,
                            "net_r": float(row["net_r"]),
                            "predicted_net_r": float(best["predicted_net_r"]),
                        }
                        positions.append(position)
                        events.append({"time": stamp, "event": "ENTRY", "sample_id": row["sample_id"]})
        for symbol, bar in current_bars.items():
            last_marks[symbol] = bar.close
        close_due(stamp + 300)
        equity_curve.append({"time": stamp + 300, "equity": equity()})
    if positions:
        raise ValueError("Fold ended with unresolved positions")
    return {
        "status": "DEV_ONLY_5M_MARK_TO_MARKET_REPLAY",
        "timeline_mode": timeline_mode,
        "equity_observation_grid": (
            "every_5m" if timeline_mode == "full_5m" else "decision_exit_and_utc_day_boundary_events"
        ),
        "fold": fold,
        "initial_cash": float(policy["research_capital"]),
        "final_cash": cash,
        "trades": trades,
        "events": events,
        "equity_curve": equity_curve,
        "metrics": _performance_metrics(trades, equity_curve),
        "claims": {"independent_oos": False, "execution_evidence": False},
    }


def evaluate_ridge_candidates(
    base_rows: list[dict[str, Any]],
    stress_rows: list[dict[str, Any]],
    ridge: dict[str, Any],
    dataset: EnrichedDataset,
    contract: dict[str, Any],
) -> dict[str, Any]:
    folds = ridge["folds"]
    predictions = ridge["predictions"]
    stress_by_id = {row["sample_id"]: row for row in stress_rows}
    candidate_results = {}
    for candidate in contract["candidates"]:
        candidate_predictions = [
            item for item in predictions if item["candidate_id"] == candidate["id"]
        ]
        base_replays = []
        stress_replays = []
        fixed_stress_trades = []
        for fold in folds:
            base = replay_candidate_fold(base_rows, candidate_predictions, dataset, fold, contract)
            stress = replay_candidate_fold(stress_rows, candidate_predictions, dataset, fold, contract)
            base_replays.append(base)
            stress_replays.append(stress)
            for trade in base["trades"]:
                stress_row = stress_by_id[trade["sample_id"]]
                fixed_stress_trades.append(
                    {
                        **trade,
                        "net_r": float(stress_row["net_r"]),
                        "net_pnl": trade["quantity"] * float(stress_row["net_pnl_per_unit"]),
                    }
                )
        base_trades = [trade for replay in base_replays for trade in replay["trades"]]
        base_curve = [point for replay in base_replays for point in replay["equity_curve"]]
        stress_trades = [trade for replay in stress_replays for trade in replay["trades"]]
        stress_curve = [point for replay in stress_replays for point in replay["equity_curve"]]
        base_metrics = _performance_metrics(base_trades, base_curve)
        base_metrics["maximum_drawdown_fraction"] = max(
            (replay["metrics"]["maximum_drawdown_fraction"] or 0.0 for replay in base_replays),
            default=None,
        )
        fixed_stress_metrics = _performance_metrics(fixed_stress_trades, [])
        full_stress_metrics = _performance_metrics(stress_trades, stress_curve)
        full_stress_metrics["maximum_drawdown_fraction"] = max(
            (replay["metrics"]["maximum_drawdown_fraction"] or 0.0 for replay in stress_replays),
            default=None,
        )
        by_symbol = {
            symbol: _performance_metrics([trade for trade in base_trades if trade["symbol"] == symbol], [])
            for symbol in CORE_SYMBOLS
        }
        best_symbol = max(CORE_SYMBOLS, key=lambda symbol: by_symbol[symbol]["net_pnl"])
        without_best_symbol = [trade for trade in base_trades if trade["symbol"] != best_symbol]
        without_largest_winner = list(base_trades)
        if without_largest_winner:
            largest = max(range(len(without_largest_winner)), key=lambda index: without_largest_winner[index]["net_pnl"])
            without_largest_winner.pop(largest)
        candidate_results[candidate["id"]] = {
            "candidate": candidate,
            "base": base_metrics,
            "fixed_sequence_double_cost": fixed_stress_metrics,
            "full_double_cost_replay": full_stress_metrics,
            "folds": [replay["metrics"] for replay in base_replays],
            "by_symbol": by_symbol,
            "best_symbol": best_symbol,
            "without_best_symbol": _performance_metrics(without_best_symbol, []),
            "without_largest_winner": _performance_metrics(without_largest_winner, []),
            "trades": base_trades,
            "equity_curve": base_curve,
        }
    result = {
        "status": "DESCRIPTIVE_DEV_ONLY",
        "candidate_results": candidate_results,
        "selection_authority": "NONE_RIDGE_IS_BASELINE_ONLY",
        "claims": {"independent_oos": False, "performance_gate_passed": False},
    }
    result["result_hash"] = canonical_hash(result)
    return result
