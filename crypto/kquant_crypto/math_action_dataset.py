"""Point-in-time panel and net-R labels for the 24-hour action study."""

from __future__ import annotations

from collections import Counter
import gzip
import json
import math
from pathlib import Path
from statistics import pstdev
from typing import TYPE_CHECKING, Any, Iterable

from .math_action_contract import CORE_SYMBOLS, canonical_hash

if TYPE_CHECKING:
    from .hybrid_dataset import Dataset


HOUR = 3600
FIVE_MINUTES = 300


def _require_finite(values: Iterable[float], message: str) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError(message)


def _partition(signal_time: int, first_boundary: int, second_boundary: int, contract: dict[str, Any]) -> str:
    purge = int(contract["partitions"]["purge_hours"]) * HOUR
    embargo = int(contract["partitions"]["embargo_hours"]) * HOUR
    if signal_time < first_boundary - purge:
        return "DEVELOPMENT_TRAIN"
    if signal_time < first_boundary + embargo:
        return "PURGED"
    if signal_time < second_boundary - purge:
        return "DEVELOPMENT_VALIDATION"
    if signal_time < second_boundary + embargo:
        return "PURGED"
    return "DEVELOPMENT_DIAGNOSTIC"


def _net_r_long(
    bars: list[Any],
    *,
    stop: float,
    target: float,
    fee: float,
    slippage: float,
    horizon_end: int,
    path_complete: bool = True,
) -> dict[str, Any]:
    if not bars:
        return {
            "fill_status": "NOT_FILLED",
            "label_status": "UNAVAILABLE",
            "unavailable_reason": "missing_entry_bar",
        }
    entry_reference = bars[0].open
    if entry_reference <= stop or entry_reference >= target:
        return {
            "fill_status": "NOT_FILLED",
            "label_status": "UNAVAILABLE",
            "unavailable_reason": "entry_open_outside_frozen_plan",
            "entry_reference": entry_reference,
        }
    entry = entry_reference * (1.0 + slippage)
    stop_fill = stop * (1.0 - slippage)
    base_r = entry - stop_fill + fee * (entry + stop_fill)
    if not math.isfinite(base_r) or base_r <= 0:
        return {
            "fill_status": "NOT_FILLED",
            "label_status": "UNAVAILABLE",
            "unavailable_reason": "invalid_base_r",
            "entry_reference": entry_reference,
        }

    exit_reference = bars[-1].close
    exit_time = horizon_end
    reason = "time_exit"
    for bar in bars:
        if bar.open <= stop:
            exit_reference, exit_time, reason = bar.open, bar.start, "gap_stop"
            break
        if bar.open >= target:
            exit_reference, exit_time, reason = bar.open, bar.start, "gap_target"
            break
        if bar.low <= stop:
            exit_reference, exit_time, reason = stop, bar.start + FIVE_MINUTES, "stop"
            break
        if bar.high >= target:
            exit_reference, exit_time, reason = target, bar.start + FIVE_MINUTES, "target"
            break

    if reason == "time_exit" and not path_complete:
        return {
            "fill_status": "FILLED",
            "label_status": "CENSORED",
            "unavailable_reason": "future_path_gap_before_terminal_exit",
            "entry_reference": entry_reference,
            "entry_price": entry,
            "fees_per_unit": fee * entry,
            "base_r_per_unit": base_r,
        }

    exit_price = exit_reference * (1.0 - slippage)
    fees = fee * (entry + exit_price)
    net_pnl_per_unit = exit_price - entry - fees
    return {
        "fill_status": "FILLED",
        "label_status": "MATURE",
        "unavailable_reason": None,
        "entry_reference": entry_reference,
        "entry_price": entry,
        "exit_reference": exit_reference,
        "exit_price": exit_price,
        "exit_time": exit_time,
        "exit_reason": reason,
        "fees_per_unit": fees,
        "base_r_per_unit": base_r,
        "net_pnl_per_unit": net_pnl_per_unit,
        "net_r": net_pnl_per_unit / base_r,
    }


def _future_bars(
    five_by_start: dict[int, Any], signal_time: int, horizon_hours: int
) -> tuple[list[Any], bool]:
    count = horizon_hours * 12
    result = []
    for index in range(count):
        bar = five_by_start.get(signal_time + index * FIVE_MINUTES)
        if bar is None:
            return result, False
        result.append(bar)
    return result, True


def build_spot_long_panel(dataset: "Dataset", contract: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build one potential Spot-long action per symbol at each common hour."""
    if tuple(contract["universe"]["spot_long"]) != CORE_SYMBOLS:
        raise ValueError("Unexpected spot universe")
    if dataset.manifest.get("source") != "binance:spot:market_specific_compacted_closed_klines":
        raise ValueError("Only the frozen Binance Spot capsule is supported")
    if contract["dataset"]["availability_contract"] != "assumed_close_historical_replay":
        raise ValueError("Unsupported availability contract")

    hourly = {symbol: {bar.start: bar for bar in dataset.bars[symbol]["1h"]} for symbol in CORE_SYMBOLS}
    five = {symbol: {bar.start: bar for bar in dataset.bars[symbol]["5m"]} for symbol in CORE_SYMBOLS}
    common_starts = sorted(set.intersection(*(set(hourly[symbol]) for symbol in CORE_SYMBOLS)))
    if len(common_starts) < 169:
        raise ValueError("Insufficient synchronized hourly history")
    for previous, current in zip(common_starts, common_starts[1:]):
        if current != previous + HOUR:
            raise ValueError("Hourly history is not continuous")

    closes = {symbol: [hourly[symbol][stamp].close for stamp in common_starts] for symbol in CORE_SYMBOLS}
    turnovers = {
        symbol: [hourly[symbol][stamp].close * hourly[symbol][stamp].volume for stamp in common_starts]
        for symbol in CORE_SYMBOLS
    }
    returns = {
        symbol: [math.nan] + [math.log(values[index] / values[index - 1]) for index in range(1, len(values))]
        for symbol, values in closes.items()
    }
    lookback = int(contract["trade_plan"]["volatility_lookback_hours"])
    horizon_hours = int(contract["trade_plan"]["max_holding_hours"])
    stop_multiple = float(contract["trade_plan"]["stop_sigma_24h"])
    target_multiple = float(contract["trade_plan"]["target_sigma_24h"])
    fee = float(contract["costs"]["spot"]["fee_bps_per_side"]) / 10000.0
    slippage = float(contract["costs"]["spot"]["slippage_bps_per_side"]) / 10000.0

    eligible_stamps = common_starts[max(lookback, 48) :]
    signal_times = [stamp + HOUR for stamp in eligible_stamps]
    first_index = int(len(signal_times) * float(contract["partitions"]["train_fraction"]))
    second_index = int(
        len(signal_times)
        * (float(contract["partitions"]["train_fraction"]) + float(contract["partitions"]["validation_fraction"]))
    )
    if not 0 < first_index < second_index < len(signal_times):
        raise ValueError("Invalid chronological partition boundaries")
    first_boundary, second_boundary = signal_times[first_index], signal_times[second_index]

    rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    for index in range(max(lookback, 48), len(common_starts)):
        signal_time = common_starts[index] + HOUR
        if signal_time + horizon_hours * HOUR > dataset.cutoff:
            continue
        market_six_hour = sum(
            math.log(closes[symbol][index] / closes[symbol][index - 6]) for symbol in CORE_SYMBOLS
        ) / len(CORE_SYMBOLS)
        partition = _partition(signal_time, first_boundary, second_boundary, contract)
        for symbol in CORE_SYMBOLS:
            recent_returns = returns[symbol][index - lookback + 1 : index + 1]
            _require_finite(recent_returns, "Non-finite volatility history")
            sigma_24h = pstdev(recent_returns) * math.sqrt(24.0)
            downside = [min(value, 0.0) for value in returns[symbol][index - 23 : index + 1]]
            current_turnover = math.fsum(turnovers[symbol][index - 23 : index + 1])
            prior_turnover = math.fsum(turnovers[symbol][index - 47 : index - 23])
            features = {
                "log_return_1h": returns[symbol][index],
                "log_return_6h": math.log(closes[symbol][index] / closes[symbol][index - 6]),
                "log_return_24h": math.log(closes[symbol][index] / closes[symbol][index - 24]),
                "realized_volatility_24h": pstdev(returns[symbol][index - 23 : index + 1]) * math.sqrt(24.0),
                "downside_volatility_24h": math.sqrt(math.fsum(value * value for value in downside) / len(downside)) * math.sqrt(24.0),
                "turnover_log_change_24h": math.log(current_turnover / prior_turnover),
                "relative_return_6h": math.log(closes[symbol][index] / closes[symbol][index - 6]) - market_six_hour,
            }
            _require_finite(features.values(), "Non-finite feature")
            reference = closes[symbol][index]
            stop = reference * math.exp(-stop_multiple * sigma_24h)
            target = reference * math.exp(target_multiple * sigma_24h)
            future, path_complete = _future_bars(five[symbol], signal_time, horizon_hours)
            outcome = _net_r_long(
                future,
                stop=stop,
                target=target,
                fee=fee,
                slippage=slippage,
                horizon_end=signal_time + horizon_hours * HOUR,
                path_complete=path_complete,
            )
            status_counts[f"{outcome['fill_status']}:{outcome['label_status']}"] += 1
            feature_as_of = {name: signal_time for name in features}
            identity = {
                "dataset_hash": dataset.content_hash,
                "contract_hash": contract["contract_hash"],
                "symbol": symbol,
                "market_type": "spot",
                "direction": "long",
                "signal_time": signal_time,
            }
            row = {
                "sample_id": canonical_hash(identity),
                **identity,
                "action": f"SPOT_LONG_{symbol}",
                "partition": partition,
                "independent_oos": False,
                "feature_snapshot_frozen_at": signal_time,
                "feature_availability_basis": "assumed_close_historical_replay",
                "feature_as_of": feature_as_of,
                "features": features,
                "signal_reference": reference,
                "sigma_24h": sigma_24h,
                "stop": stop,
                "target": target,
                "label_horizon_end": signal_time + horizon_hours * HOUR,
                "label_execution_policy_id": "SPOT_NEXT_5M_OPEN_STOP1SIGMA_TARGET2SIGMA_24H_COST10_5_V1",
                "evidence_scope": "DEV_ONLY_EXPOSED_RESEARCH",
                **outcome,
            }
            row["feature_snapshot_hash"] = canonical_hash(
                {
                    "identity": identity,
                    "features": features,
                    "feature_as_of": feature_as_of,
                }
            )
            rows.append(row)

    partition_counts = Counter(row["partition"] for row in rows)
    audit = {
        "version": contract["version"],
        "scope": contract["scope"],
        "exposure": contract["exposure"],
        "execution_enabled": False,
        "admission_enabled": False,
        "dataset_hash": dataset.content_hash,
        "contract_hash": contract["contract_hash"],
        "rows": len(rows),
        "unique_signal_times": len({row["signal_time"] for row in rows}),
        "symbols": list(CORE_SYMBOLS),
        "partition_boundaries": {
            "development_validation_start": first_boundary,
            "development_diagnostic_start": second_boundary,
        },
        "partition_counts": dict(partition_counts),
        "status_counts": dict(status_counts),
        "perpetual_short": {
            "status": "DATA_BLOCKED",
            "reason": "No frozen USD-M Futures OHLCV, mark-price and actual funding source is registered",
        },
        "limits": [
            "All rows are exposed development research and are not independent OOS evidence",
            "Historical availability is assumed at bar close and is not receipt-time or exchange-fill evidence",
            "Turnover is close multiplied by base volume, not native quote turnover",
            "Overlapping hourly 24-hour labels are dependent observations",
        ],
    }
    audit["panel_hash"] = canonical_hash(rows)
    return rows, audit


def write_panel(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    payload = "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in rows).encode("utf-8")
    path.write_bytes(gzip.compress(payload, mtime=0))
    return canonical_hash(rows)


def read_panel(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    if len({row["sample_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate sample identity")
    return rows
