"""Fail-closed DEV research for spot sell-pressure repair and buy-pressure start events."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean, median, pstdev
from typing import Any, Iterable

import numpy as np

from .hybrid_dataset_capsule import load_capsule
from .math_action_contract import CORE_SYMBOLS, canonical_hash, file_hash
from .math_action_dataset import _future_bars, _net_r_long
from .trend_evidence_research import _performance_metrics


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "spot_event_research_v1.json"
FIVE_MINUTES = 300
FIFTEEN_MINUTES = 900
HOUR = 3600
DAY = 86400


@dataclass(frozen=True)
class FiveMinuteFlow:
    quote_volume: float
    trade_count: int
    taker_buy_quote_volume: float
    source_hash: str

    @property
    def imbalance(self) -> float:
        return (2.0 * self.taker_buy_quote_volume - self.quote_volume) / self.quote_volume


@dataclass
class EventDataset:
    base: Any
    flows: dict[str, dict[int, FiveMinuteFlow]]
    content_hash: str
    audit: dict[str, Any]


def _finite(values: Iterable[float], message: str) -> None:
    if not all(math.isfinite(value) for value in values):
        raise ValueError(message)


def load_event_contract(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    path = path.resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("scope") != "DEV_ONLY" or value.get("exposure") != "EXPOSED_RESEARCH":
        raise ValueError("Spot-event research is restricted to exposed DEV evidence")
    if value.get("execution_enabled") is not False or value.get("admission_enabled") is not False:
        raise ValueError("Spot-event research cannot enable execution or admission")
    if tuple(value.get("universe", ())) != CORE_SYMBOLS:
        raise ValueError("Spot-event universe must remain BTC/ETH/SOL")
    expected = {"SELL_PRESSURE_REPAIR_6H", "BUY_PRESSURE_START_6H"}
    if len(value.get("candidates", ())) != 2 or {item["id"] for item in value["candidates"]} != expected:
        raise ValueError("Exactly two preregistered event hypotheses are required")
    registered = {item["id"]: item for item in value["candidates"]}
    if registered["SELL_PRESSURE_REPAIR_6H"] != {
        "id": "SELL_PRESSURE_REPAIR_6H",
        "hypothesis": "sell_pressure_exhaustion_then_price_repair",
        "event_return_quantile": 0.10,
        "imbalance_quantile": 0.10,
        "quote_volume_quantile": 0.90,
    }:
        raise ValueError("Sell-pressure event definition changed")
    if registered["BUY_PRESSURE_START_6H"] != {
        "id": "BUY_PRESSURE_START_6H",
        "hypothesis": "buy_pressure_increase_before_overextension",
        "imbalance_quantile": 0.90,
        "quote_volume_quantile": 0.90,
        "positive_return_cap_quantile": 0.75,
        "trailing_24h_return_cap_quantile": 0.75,
    }:
        raise ValueError("Buy-pressure event definition changed")
    dataset = value["dataset"]
    if (
        int(dataset["event_alignment_seconds"]) != FIFTEEN_MINUTES
        or int(dataset["event_bars_5m"]) != 3
        or int(dataset["confirmation_bars_5m"]) != 2
    ):
        raise ValueError("The aligned 15-minute event contract changed")
    event = value["event_policy"]
    if (
        int(event["primary_horizon_hours"]) != 6
        or event["diagnostic_horizons_hours"] != [1, 24]
        or int(event["cooldown_hours"]) != 24
    ):
        raise ValueError("The registered horizon or cooldown changed")
    plan = value["trade_plan"]
    if (
        int(plan["max_holding_hours"]) != 6
        or plan["same_bar_collision"] != "stop_first"
        or plan["gap_policy"] != "actual_open"
        or plan["entry_outside_plan"] != "not_filled"
    ):
        raise ValueError("Frozen protection semantics changed")
    if value["uncertainty"].get("multiple_testing") != "holm":
        raise ValueError("Holm family correction is mandatory")
    if value["final_targets"].get("legacy_10r_contract_resolved") is not False:
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


def _raw_source_files(root: Path, start: int, end: int) -> list[str]:
    files: list[str] = []
    first_day = datetime.fromtimestamp(start, timezone.utc).date()
    last_day = datetime.fromtimestamp(end - 1, timezone.utc).date()
    for symbol in CORE_SYMBOLS:
        day = first_day
        while day <= last_day:
            folder = root / f"symbol={symbol}" / f"date={day.isoformat()}"
            files.extend(str(path) for path in sorted(folder.glob("*.parquet")))
            day += timedelta(days=1)
    if not files:
        raise ValueError(f"No raw Binance Spot files below {root}")
    return files


def load_event_dataset(contract: dict[str, Any]) -> EventDataset:
    """Join the authorized OHLCV capsule to native Binance 5-minute trade-side fields."""
    import duckdb

    capsule_path = _resolve(contract, contract["dataset"]["spot_capsule"])
    base = load_capsule(capsule_path)
    warmup = int(base.manifest["window"]["warmup_start"])
    cutoff = int(base.cutoff)
    files = _raw_source_files(
        _resolve(contract, contract["dataset"]["raw_spot_root"]), warmup, cutoff
    )
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
          AND json_extract_string(payload_json, '$.interval') = '5m'
          AND CAST(source_time AS TIMESTAMPTZ) >= to_timestamp(?)
          AND CAST(source_time AS TIMESTAMPTZ) < to_timestamp(?)
        ORDER BY symbol, start, content_hash
    """
    with duckdb.connect(":memory:") as database:
        records = database.execute(query, [files, warmup, cutoff]).fetchall()

    grouped: defaultdict[tuple[str, int], list[tuple[float, int, float, str]]] = defaultdict(list)
    invalid = Counter()
    for symbol, start, quote_volume, trade_count, taker_quote, source_hash in records:
        try:
            values = (float(quote_volume), int(trade_count), float(taker_quote), str(source_hash))
            _finite((values[0], values[2]), "non-finite")
            if values[0] <= 0 or values[1] <= 0 or not 0 <= values[2] <= values[0]:
                raise ValueError("invalid range")
        except (TypeError, ValueError):
            invalid["invalid_native_flow_row"] += 1
            continue
        grouped[(str(symbol), int(start))].append(values)

    flows: dict[str, dict[int, FiveMinuteFlow]] = {symbol: {} for symbol in CORE_SYMBOLS}
    missing: list[tuple[str, int]] = []
    conflicts: list[tuple[str, int]] = []
    exact_duplicates = 0
    identity = hashlib.sha256(base.content_hash.encode("ascii"))
    for symbol in CORE_SYMBOLS:
        expected = {bar.start for bar in base.bars[symbol]["5m"]}
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
            source_hash = canonical_hash(sorted({item[3] for item in values}))
            flow = FiveMinuteFlow(quote, count, taker, source_hash)
            flows[symbol][stamp] = flow
            identity.update(
                canonical_hash([symbol, stamp, quote, count, taker, source_hash]).encode("ascii")
            )
    if conflicts:
        raise ValueError(f"Conflicting native 5m flow rows: {conflicts[:3]}")
    if missing:
        raise ValueError(f"Missing native 5m flow rows: {missing[:3]} ({len(missing)} total)")

    content_hash = identity.hexdigest()
    audit = {
        "scope": "DEV_ONLY_EXPOSED_RESEARCH",
        "base_dataset_hash": base.content_hash,
        "event_dataset_hash": content_hash,
        "rows": {symbol: len(flows[symbol]) for symbol in CORE_SYMBOLS},
        "raw_records_read": len(records),
        "exact_duplicates_collapsed": exact_duplicates,
        "invalid_rows_excluded": dict(invalid),
        "conflicting_timestamps": len(conflicts),
        "missing_timestamps": len(missing),
        "native_fields": ["quote_volume", "trade_count", "taker_buy_quote_volume"],
        "availability": "historical_bar_close_proxy_not_live_receipt_or_exchange_fill_evidence",
        "interpretation": "Trade-side participation proxy; not liquidation, wallet, or whale-flow identity",
    }
    return EventDataset(base, flows, content_hash, audit)


def build_aligned_windows(dataset: EventDataset, contract: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in CORE_SYMBOLS}
    warmup = int(contract["dataset"]["volatility_warmup_bars_5m"])
    research_start = int(dataset.base.manifest["window"]["start"])
    for symbol in CORE_SYMBOLS:
        bars = sorted(dataset.base.bars[symbol]["5m"], key=lambda item: item.start)
        by_start = {bar.start: bar for bar in bars}
        starts = [bar.start for bar in bars]
        returns = [math.nan] + [math.log(bars[index].close / bars[index - 1].close) for index in range(1, len(bars))]
        index_by_start = {stamp: index for index, stamp in enumerate(starts)}
        for start in starts:
            if start % FIFTEEN_MINUTES:
                continue
            index = index_by_start[start]
            if index < warmup or index + 4 >= len(bars):
                continue
            event_bars = [by_start.get(start + offset * FIVE_MINUTES) for offset in range(3)]
            confirmations = [by_start.get(start + offset * FIVE_MINUTES) for offset in (3, 4)]
            if any(item is None for item in event_bars + confirmations):
                continue
            event_end = start + FIFTEEN_MINUTES
            signal_time = event_end + 2 * FIVE_MINUTES
            if signal_time < research_start:
                continue
            flow_bars = [dataset.flows[symbol][item.start] for item in event_bars]
            confirmation_flows = [dataset.flows[symbol][item.start] for item in confirmations]
            quote_volume = math.fsum(item.quote_volume for item in flow_bars)
            taker_buy = math.fsum(item.taker_buy_quote_volume for item in flow_bars)
            trade_count = sum(item.trade_count for item in flow_bars)
            return_15m = math.log(event_bars[-1].close / event_bars[0].open)
            return_24h = math.log(event_bars[-1].close / bars[index + 2 - 288].close)
            volatility_slice = returns[index + 4 - warmup + 1 : index + 5]
            _finite(volatility_slice, "Non-finite event volatility history")
            sigma_24h = pstdev(volatility_slice) * math.sqrt(288.0)
            values = {
                "symbol": symbol,
                "event_start": start,
                "event_end": event_end,
                "signal_time": signal_time,
                "event_return_15m": return_15m,
                "event_imbalance": (2.0 * taker_buy - quote_volume) / quote_volume,
                "event_quote_volume": quote_volume,
                "event_trade_count": trade_count,
                "trailing_return_24h": return_24h,
                "sigma_24h": sigma_24h,
                "event_low": min(item.low for item in event_bars),
                "event_close": event_bars[-1].close,
                "confirmation_first_low": confirmations[0].low,
                "confirmation_second_low": confirmations[1].low,
                "confirmation_first_close": confirmations[0].close,
                "confirmation_second_close": confirmations[1].close,
                "confirmation_first_imbalance": confirmation_flows[0].imbalance,
                "confirmation_second_imbalance": confirmation_flows[1].imbalance,
                "source_hash": canonical_hash(
                    [item.source_hash for item in flow_bars + confirmation_flows]
                ),
            }
            _finite(
                (
                    values["event_return_15m"],
                    values["event_imbalance"],
                    values["event_quote_volume"],
                    values["trailing_return_24h"],
                    values["sigma_24h"],
                ),
                "Non-finite aligned event feature",
            )
            result[symbol].append(values)
    return result


def event_walk_forward_folds(windows: dict[str, list[dict[str, Any]]], contract: dict[str, Any]) -> list[dict[str, int]]:
    times = sorted(set.intersection(*(set(item["signal_time"] for item in windows[s]) for s in CORE_SYMBOLS)))
    settings = contract["walk_forward"]
    folds = int(settings["folds"])
    first = float(settings["first_evaluation_fraction"])
    width = float(settings["evaluation_fraction"])
    purge = int(settings["purge_hours"]) * HOUR
    embargo = int(settings["embargo_hours"]) * HOUR
    reserve = max(
        [int(contract["event_policy"]["primary_horizon_hours"]), *contract["event_policy"]["diagnostic_horizons_hours"]]
    ) * HOUR
    result = []
    for index in range(folds):
        boundary_index = min(len(times) - 1, int(len(times) * (first + index * width)))
        end_index = min(len(times), int(len(times) * (first + (index + 1) * width)))
        boundary = times[boundary_index]
        evaluation_end = times[end_index - 1] + FIFTEEN_MINUTES
        result.append(
            {
                "fold": index + 1,
                "training_start": times[0],
                "training_end_exclusive": boundary - purge,
                "evaluation_start": boundary + embargo,
                "evaluation_end_exclusive": evaluation_end,
                "last_entry_time_exclusive": evaluation_end - reserve,
            }
        )
    if any(item["training_end_exclusive"] <= item["training_start"] for item in result):
        raise ValueError("Empty event training window")
    if any(item["last_entry_time_exclusive"] <= item["evaluation_start"] for item in result):
        raise ValueError("Empty event evaluation window")
    return result


def fit_event_thresholds(
    windows: dict[str, list[dict[str, Any]]], folds: list[dict[str, int]], contract: dict[str, Any]
) -> list[dict[str, Any]]:
    thresholds: list[dict[str, Any]] = []
    for fold in folds:
        for symbol in CORE_SYMBOLS:
            training = [
                item
                for item in windows[symbol]
                if fold["training_start"] <= item["signal_time"] < fold["training_end_exclusive"]
            ]
            if len(training) < 100:
                raise ValueError(f"Insufficient threshold history for {symbol} fold {fold['fold']}")
            returns = np.asarray([item["event_return_15m"] for item in training], dtype=float)
            positive = returns[returns > 0]
            if len(positive) < 20:
                raise ValueError("Insufficient positive-return threshold history")
            values = {
                "fold": int(fold["fold"]),
                "symbol": symbol,
                "training_start": int(fold["training_start"]),
                "training_end_exclusive": int(fold["training_end_exclusive"]),
                "training_windows": len(training),
                "return_q10": float(np.quantile(returns, 0.10)),
                "imbalance_q10": float(np.quantile([item["event_imbalance"] for item in training], 0.10)),
                "imbalance_q90": float(np.quantile([item["event_imbalance"] for item in training], 0.90)),
                "quote_volume_q90": float(np.quantile([item["event_quote_volume"] for item in training], 0.90)),
                "positive_return_q75": float(np.quantile(positive, 0.75)),
                "trailing_return_24h_q75": float(
                    np.quantile([item["trailing_return_24h"] for item in training], 0.75)
                ),
            }
            values["threshold_hash"] = canonical_hash(values)
            thresholds.append(values)
    return thresholds


def classify_event(window: dict[str, Any], threshold: dict[str, Any], candidate_id: str) -> str | None:
    """Return EVENT, PRICE_ONLY_CONTROL, or None without reading future labels."""
    if candidate_id == "SELL_PRESSURE_REPAIR_6H":
        price_condition = window["event_return_15m"] <= threshold["return_q10"]
        flow_condition = (
            window["event_imbalance"] <= threshold["imbalance_q10"]
            and window["event_quote_volume"] >= threshold["quote_volume_q90"]
        )
        confirmation = (
            window["confirmation_first_low"] >= window["event_low"]
            and window["confirmation_second_low"] >= window["event_low"]
            and window["confirmation_second_close"] > window["confirmation_first_close"]
        )
        if price_condition and flow_condition and confirmation:
            return "EVENT"
        if price_condition and confirmation and not flow_condition:
            return "PRICE_ONLY_CONTROL"
        return None
    if candidate_id == "BUY_PRESSURE_START_6H":
        price_condition = (
            0 < window["event_return_15m"] <= threshold["positive_return_q75"]
            and window["trailing_return_24h"] <= threshold["trailing_return_24h_q75"]
        )
        flow_event = (
            window["event_imbalance"] >= threshold["imbalance_q90"]
            and window["event_quote_volume"] >= threshold["quote_volume_q90"]
        )
        flow_confirmation = (
            window["confirmation_first_imbalance"] > 0
            and window["confirmation_second_imbalance"] > 0
        )
        price_confirmation = window["confirmation_second_close"] >= window["event_close"]
        if price_condition and flow_event and flow_confirmation and price_confirmation:
            return "EVENT"
        if price_condition and price_confirmation and not (flow_event and flow_confirmation):
            return "PRICE_ONLY_CONTROL"
        return None
    raise ValueError(f"Unknown event candidate {candidate_id}")


def fixed_horizon_outcome(
    five_by_start: dict[int, Any], signal_time: int, horizon_hours: int, *, fee: float, slippage: float
) -> dict[str, Any]:
    bars, complete = _future_bars(five_by_start, signal_time, horizon_hours)
    if not bars:
        return {"label_status": "UNAVAILABLE", "reason": "missing_entry_bar"}
    if not complete:
        return {"label_status": "CENSORED", "reason": "future_path_gap"}
    entry_reference = float(bars[0].open)
    exit_reference = float(bars[-1].close)
    entry_price = entry_reference * (1.0 + slippage)
    exit_price = exit_reference * (1.0 - slippage)
    fees = fee * (entry_price + exit_price)
    initial_debit = entry_price + fee * entry_price
    net_pnl = exit_price - entry_price - fees
    return {
        "label_status": "MATURE",
        "reason": None,
        "entry_reference": entry_reference,
        "exit_reference": exit_reference,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "exit_time": signal_time + horizon_hours * HOUR,
        "gross_return": exit_reference / entry_reference - 1.0,
        "net_return": net_pnl / initial_debit,
        "fees_per_unit": fees,
        "maximum_favorable_excursion": max(item.high for item in bars) / entry_reference - 1.0,
        "maximum_adverse_excursion": min(item.low for item in bars) / entry_reference - 1.0,
    }


def _observation(
    window: dict[str, Any],
    candidate: dict[str, Any],
    sample_type: str,
    fold: dict[str, int],
    threshold: dict[str, Any],
    dataset: EventDataset,
    contract: dict[str, Any],
) -> dict[str, Any]:
    symbol = window["symbol"]
    signal_time = int(window["signal_time"])
    five = {bar.start: bar for bar in dataset.base.bars[symbol]["5m"]}
    fee = float(contract["costs"]["spot"]["fee_bps_per_side"]) / 10000.0
    slippage = float(contract["costs"]["spot"]["slippage_bps_per_side"]) / 10000.0
    stress = float(contract["costs"]["stress_multiplier"])
    horizons = [
        int(contract["event_policy"]["primary_horizon_hours"]),
        *[int(value) for value in contract["event_policy"]["diagnostic_horizons_hours"]],
    ]
    base_horizons = {
        str(horizon): fixed_horizon_outcome(five, signal_time, horizon, fee=fee, slippage=slippage)
        for horizon in sorted(set(horizons))
    }
    stress_horizons = {
        str(horizon): fixed_horizon_outcome(
            five, signal_time, horizon, fee=fee * stress, slippage=slippage * stress
        )
        for horizon in sorted(set(horizons))
    }
    reference = float(window["confirmation_second_close"])
    stop = reference * math.exp(-float(contract["trade_plan"]["stop_sigma_24h"]) * window["sigma_24h"])
    target = reference * math.exp(float(contract["trade_plan"]["target_sigma_24h"]) * window["sigma_24h"])
    future, path_complete = _future_bars(five, signal_time, int(contract["trade_plan"]["max_holding_hours"]))
    base_plan = _net_r_long(
        future,
        stop=stop,
        target=target,
        fee=fee,
        slippage=slippage,
        horizon_end=signal_time + int(contract["trade_plan"]["max_holding_hours"]) * HOUR,
        path_complete=path_complete,
    )
    stress_plan = _net_r_long(
        future,
        stop=stop,
        target=target,
        fee=fee * stress,
        slippage=slippage * stress,
        horizon_end=signal_time + int(contract["trade_plan"]["max_holding_hours"]) * HOUR,
        path_complete=path_complete,
    )
    features = {
        key: value
        for key, value in window.items()
        if key
        in {
            "event_return_15m",
            "event_imbalance",
            "event_quote_volume",
            "event_trade_count",
            "trailing_return_24h",
            "sigma_24h",
            "confirmation_first_imbalance",
            "confirmation_second_imbalance",
            "confirmation_first_close",
            "confirmation_second_close",
        }
    }
    identity = {
        "event_dataset_hash": dataset.content_hash,
        "contract_hash": contract["contract_hash"],
        "candidate_id": candidate["id"],
        "sample_type": sample_type,
        "symbol": symbol,
        "event_start": int(window["event_start"]),
        "signal_time": signal_time,
        "fold": int(fold["fold"]),
    }
    row = {
        "sample_id": canonical_hash(identity),
        **identity,
        "hypothesis": candidate["hypothesis"],
        "market_type": "spot",
        "direction": "long",
        "event_end": int(window["event_end"]),
        "feature_snapshot_frozen_at": signal_time,
        "feature_availability_basis": "assumed_close_historical_replay",
        "threshold_hash": threshold["threshold_hash"],
        "features": features,
        "feature_snapshot_hash": canonical_hash(
            {"identity": identity, "threshold_hash": threshold["threshold_hash"], "features": features}
        ),
        "source_hash": window["source_hash"],
        "signal_reference": reference,
        "stop": stop,
        "target": target,
        "fixed_horizon_base": base_horizons,
        "fixed_horizon_double_cost": stress_horizons,
        "trade_plan_base": base_plan,
        "trade_plan_double_cost": stress_plan,
        "label_execution_policy_id": "SPOT_EVENT_NEXT_5M_OPEN_FIXED_HORIZON_AND_STOP1_TARGET2_SIGMA_6H_V1",
        "evidence_scope": "DEV_ONLY_EXPOSED_RESEARCH",
        "independent_oos": False,
    }
    return row


def build_event_observations(
    dataset: EventDataset, contract: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    windows = build_aligned_windows(dataset, contract)
    folds = event_walk_forward_folds(windows, contract)
    thresholds = fit_event_thresholds(windows, folds, contract)
    threshold_map = {(item["fold"], item["symbol"]): item for item in thresholds}
    candidate_map = {item["id"]: item for item in contract["candidates"]}
    cooldown = int(contract["event_policy"]["cooldown_hours"]) * HOUR
    rows: list[dict[str, Any]] = []
    counts = Counter()
    for fold in folds:
        for symbol in CORE_SYMBOLS:
            selected_at: dict[tuple[str, str], int] = {}
            threshold = threshold_map[(fold["fold"], symbol)]
            eligible = [
                item
                for item in windows[symbol]
                if fold["evaluation_start"] <= item["signal_time"] < fold["last_entry_time_exclusive"]
            ]
            for window in eligible:
                for candidate_id, candidate in candidate_map.items():
                    sample_type = classify_event(window, threshold, candidate_id)
                    if sample_type is None:
                        continue
                    key = (candidate_id, sample_type)
                    if window["signal_time"] - selected_at.get(key, -cooldown) < cooldown:
                        counts[f"{candidate_id}:{sample_type}:cooldown_rejected"] += 1
                        continue
                    selected_at[key] = int(window["signal_time"])
                    row = _observation(window, candidate, sample_type, fold, threshold, dataset, contract)
                    rows.append(row)
                    primary = row["fixed_horizon_base"][str(contract["event_policy"]["primary_horizon_hours"])]
                    counts[f"{candidate_id}:{sample_type}:{primary['label_status']}"] += 1
    if len({row["sample_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate event observation identity")
    audit = {
        **dataset.audit,
        "contract_hash": contract["contract_hash"],
        "aligned_windows": {symbol: len(windows[symbol]) for symbol in CORE_SYMBOLS},
        "folds": folds,
        "thresholds": thresholds,
        "rows": len(rows),
        "status_counts": dict(counts),
        "first_signal_time": min((row["signal_time"] for row in rows), default=None),
        "last_signal_time": max((row["signal_time"] for row in rows), default=None),
        "limits": [
            "All observations are exposed development evidence, not independent OOS",
            "Historical entry is a next-5m-open proxy, not an exchange fill",
            "Candidate and control cooldowns are applied independently at 24 hours",
            "Trade-side participation is not liquidation, wallet, or whale identity",
        ],
    }
    audit["panel_hash"] = canonical_hash(rows)
    return rows, audit


def _distribution(rows: list[dict[str, Any]], *, horizon: int, cost_key: str) -> dict[str, Any]:
    outcomes = [row[cost_key][str(horizon)] for row in rows]
    mature = [item for item in outcomes if item["label_status"] == "MATURE"]
    values = [float(item["net_return"]) for item in mature]
    if not values:
        return {
            "observations": len(rows),
            "mature": 0,
            "censored_or_unavailable": len(rows),
            "positive_rate": None,
            "mean_net_return": None,
            "median_net_return": None,
            "q10_net_return": None,
            "q90_net_return": None,
            "mean_mfe": None,
            "mean_mae": None,
            "average_positive_return": None,
            "average_nonpositive_return": None,
            "payoff": None,
            "profit_factor": None,
        }
    positive = [value for value in values if value > 0]
    nonpositive = [value for value in values if value <= 0]
    average_positive = fmean(positive) if positive else None
    average_nonpositive = fmean(nonpositive) if nonpositive else None
    return {
        "observations": len(rows),
        "mature": len(values),
        "censored_or_unavailable": len(rows) - len(values),
        "positive_rate": sum(value > 0 for value in values) / len(values),
        "mean_net_return": fmean(values),
        "median_net_return": median(values),
        "q10_net_return": float(np.quantile(values, 0.10)),
        "q90_net_return": float(np.quantile(values, 0.90)),
        "mean_mfe": fmean(float(item["maximum_favorable_excursion"]) for item in mature),
        "mean_mae": fmean(float(item["maximum_adverse_excursion"]) for item in mature),
        "average_positive_return": average_positive,
        "average_nonpositive_return": average_nonpositive,
        "payoff": (
            average_positive / abs(average_nonpositive)
            if average_positive is not None and average_nonpositive not in {None, 0.0}
            else None
        ),
        "profit_factor": (
            math.fsum(positive) / -math.fsum(nonpositive)
            if positive and nonpositive and math.fsum(nonpositive) < 0
            else None
        ),
    }


def _block_bootstrap_increment(
    event_rows: list[dict[str, Any]],
    control_rows: list[dict[str, Any]],
    folds: list[dict[str, int]],
    contract: dict[str, Any],
    candidate_id: str,
) -> dict[str, Any]:
    settings = contract["uncertainty"]
    block_days = int(settings["block_days"])
    paths = int(settings["paths"])
    horizon = str(contract["event_policy"]["primary_horizon_hours"])
    by_day: defaultdict[tuple[int, int, str], list[float]] = defaultdict(list)
    for sample_type, source in (("EVENT", event_rows), ("CONTROL", control_rows)):
        for row in source:
            outcome = row["fixed_horizon_base"][horizon]
            if outcome["label_status"] == "MATURE":
                by_day[(int(row["fold"]), int(row["signal_time"]) // DAY, sample_type)].append(
                    float(outcome["net_return"])
                )
    blocks: list[tuple[list[float], list[float]]] = []
    total_days = 0
    for fold in folds:
        start_day = int(fold["evaluation_start"]) // DAY
        end_day = (int(fold["last_entry_time_exclusive"]) - 1) // DAY
        days = list(range(start_day, end_day + 1))
        total_days += len(days)
        for offset in range(max(0, len(days) - block_days + 1)):
            selected = days[offset : offset + block_days]
            blocks.append(
                (
                    [value for day in selected for value in by_day[(int(fold["fold"]), day, "EVENT")]],
                    [value for day in selected for value in by_day[(int(fold["fold"]), day, "CONTROL")]],
                )
            )
    event_values = [value for key, values in by_day.items() if key[2] == "EVENT" for value in values]
    control_values = [value for key, values in by_day.items() if key[2] == "CONTROL" for value in values]
    if not event_values or not control_values or not blocks:
        return {
            "status": "UNAVAILABLE_INSUFFICIENT_EVENT_OR_CONTROL_DATA",
            "paths": 0,
            "observed_increment": None,
            "bootstrap_nonpositive_probability": None,
        }
    rng = np.random.default_rng(int(settings["seed"]) + int(canonical_hash(candidate_id)[:8], 16))
    draws = []
    blocks_per_path = max(1, math.ceil(total_days / block_days))
    for _ in range(paths):
        event_sample: list[float] = []
        control_sample: list[float] = []
        for index in rng.integers(0, len(blocks), size=blocks_per_path):
            event_block, control_block = blocks[int(index)]
            event_sample.extend(event_block)
            control_sample.extend(control_block)
        if event_sample and control_sample:
            draws.append(fmean(event_sample) - fmean(control_sample))
    if not draws:
        return {
            "status": "UNAVAILABLE_EMPTY_BOOTSTRAP_PATHS",
            "paths": 0,
            "observed_increment": None,
            "bootstrap_nonpositive_probability": None,
        }
    observed = fmean(event_values) - fmean(control_values)
    return {
        "status": "DEV_ONLY_SYNCHRONIZED_DATE_BLOCK_BOOTSTRAP",
        "paths": len(draws),
        "block_days": block_days,
        "observed_increment": observed,
        "q025_increment": float(np.quantile(draws, 0.025)),
        "q50_increment": float(np.quantile(draws, 0.50)),
        "q975_increment": float(np.quantile(draws, 0.975)),
        "bootstrap_nonpositive_probability": sum(value <= 0 for value in draws) / len(draws),
        "interpretation": "Bootstrap confidence mass, not an independently calibrated p-value",
    }


def summarize_event_study(
    rows: list[dict[str, Any]], audit: dict[str, Any], contract: dict[str, Any]
) -> dict[str, Any]:
    primary = int(contract["event_policy"]["primary_horizon_hours"])
    candidates: dict[str, Any] = {}
    raw_tails: dict[str, float] = {}
    for candidate in contract["candidates"]:
        candidate_id = candidate["id"]
        event_rows = [row for row in rows if row["candidate_id"] == candidate_id and row["sample_type"] == "EVENT"]
        control_rows = [
            row for row in rows if row["candidate_id"] == candidate_id and row["sample_type"] == "PRICE_ONLY_CONTROL"
        ]
        base = {str(h): _distribution(event_rows, horizon=h, cost_key="fixed_horizon_base") for h in (1, 6, 24)}
        controls = {
            str(h): _distribution(control_rows, horizon=h, cost_key="fixed_horizon_base") for h in (1, 6, 24)
        }
        double_cost = _distribution(event_rows, horizon=primary, cost_key="fixed_horizon_double_cost")
        by_fold = {
            str(fold["fold"]): _distribution(
                [row for row in event_rows if int(row["fold"]) == int(fold["fold"])],
                horizon=primary,
                cost_key="fixed_horizon_base",
            )
            for fold in audit["folds"]
        }
        by_symbol = {
            symbol: _distribution(
                [row for row in event_rows if row["symbol"] == symbol],
                horizon=primary,
                cost_key="fixed_horizon_base",
            )
            for symbol in CORE_SYMBOLS
        }
        bootstrap = _block_bootstrap_increment(event_rows, control_rows, audit["folds"], contract, candidate_id)
        if bootstrap["bootstrap_nonpositive_probability"] is not None:
            raw_tails[candidate_id] = float(bootstrap["bootstrap_nonpositive_probability"])
        candidates[candidate_id] = {
            "hypothesis": candidate["hypothesis"],
            "event_fixed_horizon": base,
            "price_only_control": controls,
            "event_double_cost_6h": double_cost,
            "by_fold_6h": by_fold,
            "by_symbol_6h": by_symbol,
            "control_increment_uncertainty": bootstrap,
        }

    adjusted: dict[str, float | None] = {candidate["id"]: None for candidate in contract["candidates"]}
    running = 0.0
    ordered = sorted(raw_tails, key=raw_tails.get)
    family_size = len(contract["candidates"])
    for rank, candidate_id in enumerate(ordered):
        value = min(1.0, (family_size - rank) * raw_tails[candidate_id])
        running = max(running, value)
        adjusted[candidate_id] = running

    gate = contract["preliminary_gate"]
    for candidate_id, item in candidates.items():
        base = item["event_fixed_horizon"][str(primary)]
        stress = item["event_double_cost_6h"]
        bootstrap = item["control_increment_uncertainty"]
        positive_folds = sum(
            fold["mean_net_return"] is not None and fold["mean_net_return"] > 0
            for fold in item["by_fold_6h"].values()
        )
        checks = {
            "mature_events": base["mature"] >= int(gate["mature_events_min"]),
            "base_mean_net_return": base["mean_net_return"] is not None
            and base["mean_net_return"] > float(gate["base_mean_net_return_min"]),
            "double_cost_mean_net_return": stress["mean_net_return"] is not None
            and stress["mean_net_return"] > float(gate["double_cost_mean_net_return_min"]),
            "positive_folds": positive_folds >= int(gate["positive_folds_min"]),
            "control_increment": bootstrap["observed_increment"] is not None
            and bootstrap["observed_increment"] > float(gate["control_increment_min"]),
            "holm_adjusted_tail_probability": adjusted[candidate_id] is not None
            and adjusted[candidate_id] <= float(gate["holm_adjusted_tail_probability_max"]),
        }
        item["positive_folds"] = positive_folds
        item["holm_adjusted_tail_probability"] = adjusted[candidate_id]
        item["preliminary_gate_checks"] = checks
        item["preliminary_gate_passed"] = all(checks.values())
        item["next_action"] = (
            "ELIGIBLE_FOR_DEV_MODEL_AND_PORTFOLIO_REPLAY"
            if item["preliminary_gate_passed"]
            else "REJECT_EVENT_DEFINITION_OR_MARK_INSUFFICIENT_EVIDENCE"
        )
    result = {
        "status": "DEV_ONLY_EXPOSED_EVENT_STUDY",
        "contract_hash": contract["contract_hash"],
        "event_dataset_hash": audit["event_dataset_hash"],
        "candidates": candidates,
        "multiple_testing": {
            "method": "holm_adjustment_of_bootstrap_nonpositive_probability",
            "family_size": family_size,
            "adjusted_values": adjusted,
            "not_a_calibrated_p_value": True,
        },
        "qualified_candidates": [key for key, value in candidates.items() if value["preliminary_gate_passed"]],
        "claims": contract["claims"],
    }
    result["result_hash"] = canonical_hash(result)
    return result


def replay_event_candidate(
    rows: list[dict[str, Any]],
    dataset: EventDataset,
    fold: dict[str, int],
    contract: dict[str, Any],
    candidate_id: str,
    *,
    cost_multiplier: float = 1.0,
) -> dict[str, Any]:
    """Replay event signals from closed-bar state only; future labels are never admission inputs."""
    signals: defaultdict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if (
            row["candidate_id"] == candidate_id
            and row["sample_type"] == "EVENT"
            and int(row["fold"]) == int(fold["fold"])
            and fold["evaluation_start"] <= row["signal_time"] < fold["last_entry_time_exclusive"]
        ):
            signals[int(row["signal_time"])].append(row)
    bars = {symbol: {bar.start: bar for bar in dataset.base.bars[symbol]["5m"]} for symbol in CORE_SYMBOLS}
    policy = contract["portfolio"]
    fee = float(contract["costs"]["spot"]["fee_bps_per_side"]) * cost_multiplier / 10000.0
    slippage = float(contract["costs"]["spot"]["slippage_bps_per_side"]) * cost_multiplier / 10000.0
    cash = float(policy["research_capital"])
    positions: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    marks: dict[str, float] = {}
    day = None
    day_start_equity = cash
    paused_day = False
    loss_streak = 0
    pause_until = 0

    def equity() -> float:
        return cash + math.fsum(
            position["quantity"] * marks.get(symbol, position["entry_price"]) * (1.0 - fee - slippage)
            for symbol, position in positions.items()
        )

    def close(symbol: str, reference: float, time: int, reason: str, *, label_status: str = "MATURE") -> None:
        nonlocal cash, loss_streak, pause_until
        position = positions.pop(symbol)
        exit_price = reference * (1.0 - slippage)
        exit_fee = position["quantity"] * exit_price * fee
        net_pnl = position["quantity"] * (exit_price - position["entry_price"]) - exit_fee - position["entry_fee"]
        cash += position["quantity"] * exit_price - exit_fee
        trade = {
            **position,
            "exit_time": time,
            "exit_reference": reference,
            "exit_price": exit_price,
            "exit_fee": exit_fee,
            "fees": position["entry_fee"] + exit_fee,
            "exit_reason": reason,
            "label_status": label_status,
            "net_pnl": net_pnl,
            "net_r": net_pnl / position["risk_amount"] if position["risk_amount"] > 0 else None,
            "cost_multiplier": cost_multiplier,
            "execution_source": "historical_next_5m_open_proxy",
        }
        trades.append(trade)
        events.append({"time": time, "event": "EXIT", "sample_id": position["sample_id"], "reason": reason})
        if label_status == "MATURE":
            loss_streak = loss_streak + 1 if net_pnl < 0 else 0
            if loss_streak >= int(policy["loss_streak"]):
                pause_until = time + int(policy["pause_hours"]) * HOUR
                loss_streak = 0

    for stamp in range(int(fold["evaluation_start"]), int(fold["evaluation_end_exclusive"]), FIVE_MINUTES):
        current = {symbol: bars[symbol].get(stamp) for symbol in CORE_SYMBOLS}
        for symbol, bar in current.items():
            if bar is not None:
                marks.setdefault(symbol, bar.open)
        current_day = stamp // DAY
        if day != current_day:
            day = current_day
            day_start_equity = equity()
            paused_day = False

        for symbol in list(positions):
            bar = current[symbol]
            if bar is None:
                positions[symbol]["path_gap"] = True
                continue
            position = positions[symbol]
            if position.pop("path_gap", False):
                close(symbol, min(bar.open, position["stop"]), stamp, "data_gap", label_status="CENSORED")
            elif bar.open <= position["stop"]:
                close(symbol, bar.open, stamp, "gap_stop")
            elif bar.open >= position["target"]:
                close(symbol, bar.open, stamp, "gap_target")

        if equity() <= day_start_equity * (1.0 - float(policy["daily_loss_limit"])):
            paused_day = True
        for row in sorted(signals.get(stamp, []), key=lambda item: CORE_SYMBOLS.index(item["symbol"])):
            symbol = row["symbol"]
            bar = current[symbol]
            reason = None
            if paused_day:
                reason = "daily_loss_pause"
            elif stamp < pause_until:
                reason = "loss_streak_pause"
            elif symbol in positions:
                reason = "symbol_already_exposed"
            elif len(positions) >= int(policy["max_positions"]):
                reason = "position_limit"
            elif bar is None:
                reason = "missing_entry_bar"
            elif bar.open <= float(row["stop"]) or bar.open >= float(row["target"]):
                reason = "entry_open_outside_frozen_plan"
            if reason:
                events.append({"time": stamp, "event": "ENTRY_REJECTED", "sample_id": row["sample_id"], "reason": reason})
                continue
            entry_reference = float(bar.open)
            entry_price = entry_reference * (1.0 + slippage)
            stop_fill = float(row["stop"]) * (1.0 - slippage)
            unit_risk = entry_price - stop_fill + fee * (entry_price + stop_fill)
            current_equity = equity()
            open_risk = math.fsum(item["risk_amount"] for item in positions.values())
            budget = min(
                current_equity * float(policy["risk_per_trade"]),
                current_equity * float(policy["max_open_risk"]) - open_risk,
            )
            quantity = min(
                max(0.0, budget) / unit_risk,
                current_equity * float(policy["max_symbol_notional"]) / entry_price,
                cash / (entry_price * (1.0 + fee)),
            )
            if quantity <= 0:
                events.append({"time": stamp, "event": "ENTRY_REJECTED", "sample_id": row["sample_id"], "reason": "risk_or_cash_unavailable"})
                continue
            entry_fee = quantity * entry_price * fee
            cash -= quantity * entry_price + entry_fee
            positions[symbol] = {
                "sample_id": row["sample_id"],
                "candidate_id": candidate_id,
                "fold": int(fold["fold"]),
                "symbol": symbol,
                "signal_time": stamp,
                "entry_time": stamp,
                "entry_reference": entry_reference,
                "entry_price": entry_price,
                "entry_fee": entry_fee,
                "quantity": quantity,
                "stop": float(row["stop"]),
                "target": float(row["target"]),
                "expires_at": stamp + int(contract["trade_plan"]["max_holding_hours"]) * HOUR,
                "base_r_per_unit": unit_risk,
                "risk_amount": quantity * unit_risk,
            }
            events.append({"time": stamp, "event": "ENTRY", "sample_id": row["sample_id"]})

        for symbol in list(positions):
            bar = current[symbol]
            if bar is None:
                continue
            position = positions[symbol]
            if bar.low <= position["stop"]:
                close(symbol, position["stop"], stamp + FIVE_MINUTES, "stop")
            elif bar.high >= position["target"]:
                close(symbol, position["target"], stamp + FIVE_MINUTES, "target")
            elif stamp + FIVE_MINUTES >= position["expires_at"]:
                close(symbol, bar.close, stamp + FIVE_MINUTES, "time_exit")

        for symbol, bar in current.items():
            if bar is not None:
                marks[symbol] = bar.close
        if equity() <= day_start_equity * (1.0 - float(policy["daily_loss_limit"])):
            paused_day = True
        curve.append({"time": stamp + FIVE_MINUTES, "equity": equity()})

    for symbol in list(positions):
        close(symbol, marks[symbol], int(fold["evaluation_end_exclusive"]), "terminal_liquidation", label_status="CENSORED")
    mature = [trade for trade in trades if trade["label_status"] == "MATURE"]
    return {
        "status": "DEV_ONLY_EVENT_PORTFOLIO_REPLAY",
        "candidate_id": candidate_id,
        "fold": fold,
        "cost_multiplier": cost_multiplier,
        "trades": trades,
        "events": events,
        "equity_curve": curve,
        "metrics": _performance_metrics(mature, curve),
        "censored_trades": len(trades) - len(mature),
        "claims": {"independent_oos": False, "execution_evidence": False},
    }


def reprice_fixed_sequence_double_cost(
    trades: list[dict[str, Any]], contract: dict[str, Any]
) -> list[dict[str, Any]]:
    """Reprice base fills at double costs while retaining the BASE risk denominator."""
    multiplier = float(contract["costs"]["stress_multiplier"])
    fee = float(contract["costs"]["spot"]["fee_bps_per_side"]) * multiplier / 10000.0
    slippage = float(contract["costs"]["spot"]["slippage_bps_per_side"]) * multiplier / 10000.0
    result = []
    for trade in trades:
        entry = float(trade["entry_reference"]) * (1.0 + slippage)
        exit_price = float(trade["exit_reference"]) * (1.0 - slippage)
        fees = fee * (entry + exit_price)
        net_per_unit = exit_price - entry - fees
        result.append(
            {
                **trade,
                "entry_price": entry,
                "exit_price": exit_price,
                "fees": float(trade["quantity"]) * fees,
                "net_pnl": float(trade["quantity"]) * net_per_unit,
                "net_r": net_per_unit / float(trade["base_r_per_unit"]),
                "cost_multiplier": multiplier,
                "risk_denominator": "BASE_R_UNCHANGED",
            }
        )
    return result


def evaluate_qualified_replays(
    rows: list[dict[str, Any]],
    dataset: EventDataset,
    audit: dict[str, Any],
    study: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    qualified = list(study["qualified_candidates"])
    if not qualified:
        result = {
            "status": "SKIPPED_NO_PRELIMINARY_EVENT_GATE",
            "candidate_results": {},
            "execution_enabled": False,
            "admission_enabled": False,
        }
        result["result_hash"] = canonical_hash(result)
        return result
    candidate_results = {}
    for candidate_id in qualified:
        base_replays = [replay_event_candidate(rows, dataset, fold, contract, candidate_id) for fold in audit["folds"]]
        stress_replays = [
            replay_event_candidate(
                rows,
                dataset,
                fold,
                contract,
                candidate_id,
                cost_multiplier=float(contract["costs"]["stress_multiplier"]),
            )
            for fold in audit["folds"]
        ]
        base_trades = [trade for replay in base_replays for trade in replay["trades"] if trade["label_status"] == "MATURE"]
        base_curve = [point for replay in base_replays for point in replay["equity_curve"]]
        stress_trades = [trade for replay in stress_replays for trade in replay["trades"] if trade["label_status"] == "MATURE"]
        stress_curve = [point for replay in stress_replays for point in replay["equity_curve"]]
        fixed_stress_trades = reprice_fixed_sequence_double_cost(base_trades, contract)
        by_symbol = {
            symbol: _performance_metrics([trade for trade in base_trades if trade["symbol"] == symbol], [])
            for symbol in CORE_SYMBOLS
        }
        best_symbol = max(CORE_SYMBOLS, key=lambda symbol: by_symbol[symbol]["net_pnl"])
        without_best = [trade for trade in base_trades if trade["symbol"] != best_symbol]
        without_largest = list(base_trades)
        if without_largest:
            without_largest.pop(max(range(len(without_largest)), key=lambda index: without_largest[index]["net_pnl"]))
        base_metrics = _performance_metrics(base_trades, base_curve)
        full_stress_metrics = _performance_metrics(stress_trades, stress_curve)
        fixed_stress_metrics = _performance_metrics(fixed_stress_trades, [])
        targets = contract["final_targets"]
        checks = {
            "net_payoff": base_metrics["payoff_r"] is not None
            and base_metrics["payoff_r"] >= float(targets["net_payoff_min"]),
            "base_profit_factor": base_metrics["profit_factor_r"] is not None
            and base_metrics["profit_factor_r"] >= float(targets["base_profit_factor_min"]),
            "mean_net_r": base_metrics["mean_net_r"] is not None
            and base_metrics["mean_net_r"] > float(targets["mean_net_r_min"]),
            "double_cost_profit_factor": fixed_stress_metrics["profit_factor_r"] is not None
            and fixed_stress_metrics["profit_factor_r"] >= float(targets["double_cost_profit_factor_min"]),
            "maximum_drawdown": base_metrics["maximum_drawdown_fraction"] is not None
            and base_metrics["maximum_drawdown_fraction"] <= float(targets["maximum_drawdown_fraction_max"]),
            "independent_trade_count": base_metrics["trades"] >= int(targets["independent_trades_min"]),
            "candidate_trade_count": base_metrics["trades"] >= int(targets["trades_per_candidate_min"]),
            "symbol_trade_counts": all(
                item["trades"] >= int(targets["trades_per_symbol_candidate_min"])
                for item in by_symbol.values()
            ),
            "legacy_10r_contract": False,
        }
        candidate_results[candidate_id] = {
            "base": base_metrics,
            "fixed_sequence_double_cost_base_r_denominator": fixed_stress_metrics,
            "full_double_cost": full_stress_metrics,
            "folds": [replay["metrics"] for replay in base_replays],
            "by_symbol": by_symbol,
            "best_symbol": best_symbol,
            "without_best_symbol": _performance_metrics(without_best, []),
            "without_largest_winner": _performance_metrics(without_largest, []),
            "descriptive_target_checks": checks,
            "all_final_targets_met": all(checks.values()),
            "trades": base_trades,
            "equity_curve": base_curve,
            "censored_trades": sum(replay["censored_trades"] for replay in base_replays),
        }
    result = {
        "status": "DEV_ONLY_QUALIFIED_EVENT_REPLAYS",
        "candidate_results": candidate_results,
        "execution_enabled": False,
        "admission_enabled": False,
        "claims": contract["claims"],
    }
    result["result_hash"] = canonical_hash(result)
    return result
