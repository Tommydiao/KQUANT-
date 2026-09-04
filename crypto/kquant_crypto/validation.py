from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Sequence

from .backtest import BacktestBar, BacktestConfig, TradeOutcome, run_early_start_backtest, summarize_outcomes
from .evaluation_models import stable_hash
from .factor_registry import FactorRegistry


VALIDATION_GATE_VERSION = "crypto_validation_gate_v1.0.0"


def evaluate_validation_gate(
    report: Mapping[str, Any],
    *,
    minimum_oos_folds: int = 3,
    minimum_test_trades: int = 200,
    minimum_bootstrap_expected_r_lower: float = 0.0,
    minimum_profit_factor: float = 1.25,
    minimum_stress_profit_factor: float = 1.05,
    minimum_average_win_loss_ratio: float = 1.5,
    minimum_unit_trades: int = 30,
    maximum_drawdown_r: float = 10.0,
) -> dict[str, Any]:
    """Evaluate the locked research-performance gate without changing EVAL.

    The gate intentionally reads only the locked test partition for outcome
    metrics.  OOS folds are an independent evidence-chain requirement.  A
    missing metric is a failed check, never an implicit pass.
    """

    test_summary = (
        report.get("partitions", {})
        .get("test", {})
        .get("summary", {})
    )
    bootstrap_interval = test_summary.get("bootstrap_expected_r_interval_95") or ()
    bootstrap_lower = bootstrap_interval[0] if len(bootstrap_interval) >= 1 else None
    observed = {
        "oos_fold_count": report.get("oos_fold_count", 0),
        "test_trade_count": test_summary.get("sample_count", 0),
        "bootstrap_expected_r_lower_95": bootstrap_lower,
        "profit_factor": test_summary.get("profit_factor"),
        "stress_profit_factor": report.get("stress", {}).get("test", {}).get("profit_factor"),
        "average_win_loss_ratio": test_summary.get("average_win_loss_ratio"),
        "best_symbol_removed_expected_r": test_summary.get("best_symbol_removed_expected_r"),
        "max_drawdown_r": test_summary.get("max_drawdown_r"),
    }
    checks = [
        {
            "id": "test_partition_lock",
            "label": "test partition is locked",
            "passed": report.get("test_is_locked") is True,
            "observed": report.get("test_is_locked"),
            "required": {"operator": "==", "value": True},
        },
        {
            "id": "oos_folds",
            "label": "locked OOS fold count",
            "passed": int(observed["oos_fold_count"] or 0) >= minimum_oos_folds,
            "observed": observed["oos_fold_count"],
            "required": {"operator": ">=", "value": minimum_oos_folds},
        },
        {
            "id": "test_trades",
            "label": "locked test trigger count",
            "passed": int(observed["test_trade_count"] or 0) >= minimum_test_trades,
            "observed": observed["test_trade_count"],
            "required": {"operator": ">=", "value": minimum_test_trades},
        },
        {
            "id": "unit_trades",
            "label": "strategy-product-direction unit has enough test trades",
            "passed": int(observed["test_trade_count"] or 0) >= minimum_unit_trades,
            "observed": observed["test_trade_count"],
            "required": {"operator": ">=", "value": minimum_unit_trades},
        },
        {
            "id": "bootstrap_expected_r",
            "label": "locked test bootstrap expected-R lower bound",
            "passed": bootstrap_lower is not None and float(bootstrap_lower) > minimum_bootstrap_expected_r_lower,
            "observed": bootstrap_lower,
            "required": {"operator": ">", "value": minimum_bootstrap_expected_r_lower},
        },
        {
            "id": "profit_factor",
            "label": "locked test profit factor",
            "passed": test_summary.get("profit_factor") is not None and float(test_summary["profit_factor"]) >= minimum_profit_factor,
            "observed": observed["profit_factor"],
            "required": {"operator": ">=", "value": minimum_profit_factor},
        },
        {
            "id": "stress_profit_factor",
            "label": "locked test profit factor under doubled costs",
            "passed": observed["stress_profit_factor"] is not None and float(observed["stress_profit_factor"]) >= minimum_stress_profit_factor,
            "observed": observed["stress_profit_factor"],
            "required": {"operator": ">=", "value": minimum_stress_profit_factor},
        },
        {
            "id": "average_win_loss_ratio",
            "label": "locked test realized win/loss ratio",
            "passed": observed["average_win_loss_ratio"] is not None and float(observed["average_win_loss_ratio"]) >= minimum_average_win_loss_ratio,
            "observed": observed["average_win_loss_ratio"],
            "required": {"operator": ">=", "value": minimum_average_win_loss_ratio},
        },
        {
            "id": "best_symbol_removed",
            "label": "expected R remains positive after removing the best symbol",
            "passed": observed["best_symbol_removed_expected_r"] is not None and float(observed["best_symbol_removed_expected_r"]) > 0.0,
            "observed": observed["best_symbol_removed_expected_r"],
            "required": {"operator": ">", "value": 0.0},
        },
        {
            "id": "max_drawdown",
            "label": "locked test maximum drawdown",
            "passed": test_summary.get("max_drawdown_r") is not None and float(test_summary["max_drawdown_r"]) <= maximum_drawdown_r,
            "observed": observed["max_drawdown_r"],
            "required": {"operator": "<=", "value": maximum_drawdown_r},
        },
    ]
    failed = [item["id"] for item in checks if not item["passed"]]
    return {
        "version": VALIDATION_GATE_VERSION,
        "status": "PASS" if not failed else "NO_GO",
        "passed": not failed,
        "checks": checks,
        "failed_checks": failed,
        "test_is_locked": report.get("test_is_locked") is True,
        "test_evidence_status": test_summary.get("evidence_status", "insufficient"),
        "note": "This performance gate is necessary but not sufficient for execution; EVAL, account risk, Testnet, arming, and reconciliation gates still apply.",
    }


@dataclass(frozen=True)
class ValidationSeries:
    """One point-in-time series included in a shared date split."""

    asset_id: str
    symbol: str
    bars: tuple[BacktestBar, ...]
    benchmark_bars: Mapping[str, Sequence[BacktestBar]] | None = None
    derivative_series: Sequence[Mapping[str, float | None]] | None = None
    instrument_id: str = ""
    asset_type: str = "crypto_spot"
    instrument_data_status: str = ""
    underlying_proxy_used: bool = False


@dataclass(frozen=True)
class ValidationConfig:
    strategy_version: str = "crypto_early_v1.0.0"
    dataset_version: str = "crypto_dataset_v1.0.0"
    feature_scope: str = "full_realtime"
    bar_interval: str = "1m"
    train_ratio: float = 0.60
    validation_ratio: float = 0.20
    embargo_bars: int = 8
    backtest: BacktestConfig = BacktestConfig()
    bootstrap_iterations: int = 1000
    bootstrap_seed: int = 7
    oos_folds: int = 3
    market_type: str = "spot"
    direction: str = "long"


def _partition_dates(dates: Sequence[str], train_ratio: float, validation_ratio: float) -> dict[str, tuple[str, ...]]:
    unique = tuple(sorted(set(dates)))
    if len(unique) < 3:
        return {"train": unique, "validation": (), "test": ()}
    train_end = min(len(unique) - 2, max(1, int(len(unique) * train_ratio)))
    validation_end = min(len(unique) - 1, max(train_end + 1, int(len(unique) * (train_ratio + validation_ratio))))
    return {
        "train": unique[:train_end],
        "validation": unique[train_end:validation_end],
        "test": unique[validation_end:],
    }


def _rolling_oos_partitions(dates: Sequence[str], fold_count: int) -> list[dict[str, tuple[str, ...]]]:
    """Build expanding-train, fixed validation/test windows by date.

    Test windows are disjoint and ordered. A fold never uses a date after its
    test window to construct its train or validation partition.
    """

    unique = tuple(sorted(set(dates)))
    requested = max(1, int(fold_count))
    window = max(1, len(unique) // (requested + 4))
    initial_train = len(unique) - (requested + 1) * window
    if initial_train < 1:
        return []
    partitions: list[dict[str, tuple[str, ...]]] = []
    for index in range(requested):
        validation_start = initial_train + index * window
        test_start = validation_start + window
        test_end = min(len(unique), test_start + window)
        if test_start >= len(unique) or test_start >= test_end:
            break
        partitions.append({
            "train": unique[:validation_start],
            "validation": unique[validation_start:test_start],
            "test": unique[test_start:test_end],
        })
    return partitions


def _dataset_hash(series: Sequence[ValidationSeries], config: ValidationConfig, weights: dict[str, float]) -> str:
    payload: list[dict[str, Any]] = []
    for item in sorted(series, key=lambda value: value.asset_id):
        payload.append({
            "asset_id": item.asset_id,
            "symbol": item.symbol,
            "bars": [bar.__dict__ for bar in item.bars],
            "benchmarks": {
                key: [bar.__dict__ for bar in value]
                for key, value in sorted((item.benchmark_bars or {}).items())
            },
            "derivative_series": list(item.derivative_series or ()),
        })
    return stable_hash({
        "series": payload,
        "strategy_version": config.strategy_version,
        "dataset_version": config.dataset_version,
        "feature_scope": config.feature_scope,
        "market_type": config.market_type,
        "direction": config.direction,
        "bar_interval": config.bar_interval,
        "weights": dict(sorted(weights.items())),
        "backtest": config.backtest.__dict__,
        "split": {
            "train_ratio": config.train_ratio,
            "validation_ratio": config.validation_ratio,
            "embargo_bars": config.embargo_bars,
            "oos_folds": config.oos_folds,
        },
    })


def _run_partition(
    series: ValidationSeries,
    dates: tuple[str, ...],
    *,
    registry: FactorRegistry,
    weights: dict[str, float],
    config: ValidationConfig,
    score_policy: Callable[[FactorRegistry, Mapping[str, float | None]], Mapping[str, Any]] | None = None,
) -> tuple[list[TradeOutcome], int, int]:
    if not dates or not series.bars:
        return [], 0, 0
    wanted = set(dates)
    indices = [index for index, bar in enumerate(series.bars) if bar.start_time[:10] in wanted]
    if not indices:
        return [], 0, 0
    start = min(indices)
    end = max(indices) + 1
    embargoed_count = min(max(0, config.embargo_bars), max(0, end - start))
    start += embargoed_count
    if start >= end:
        return [], 0, embargoed_count
    outcomes = run_early_start_backtest(
        # The full history is passed for warm-up, while signal indices are
        # restricted to the partition dates.
        registry=registry,
        bars=series.bars,
        benchmark_bars=series.benchmark_bars,
        derivative_series=series.derivative_series,
        weights=weights,
        config=config.backtest,
        signal_start_index=start,
        signal_end_index=end,
        asset_id=series.asset_id,
        symbol=series.symbol,
        score_policy=score_policy,
    )
    last_date = dates[-1]
    kept: list[TradeOutcome] = []
    censored = 0
    for outcome in outcomes:
        if outcome.exit_time[:10] > last_date:
            censored += 1
            continue
        kept.append(outcome)
    return kept, censored, embargoed_count


def run_walk_forward_validation(
    series: Sequence[ValidationSeries],
    *,
    registry: FactorRegistry,
    weights: dict[str, float],
    config: ValidationConfig | None = None,
    score_policy: Callable[[FactorRegistry, Mapping[str, float | None]], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a deterministic date-level 60/20/20 validation report.

    Each partition receives the complete pre-partition history for indicator
    warm-up, but signals are generated only inside its dates. Trades crossing
    a partition boundary are censored instead of being assigned future data.
    The test partition is reported, never used to choose parameters.
    """

    policy = config or ValidationConfig()
    clean_series = tuple(sorted(series, key=lambda value: value.asset_id))
    all_dates = [bar.start_time[:10] for item in clean_series for bar in item.bars]
    partitions = _partition_dates(all_dates, policy.train_ratio, policy.validation_ratio)
    report: dict[str, Any] = {
        "strategy_version": policy.strategy_version,
        "dataset_version": policy.dataset_version,
        "dataset_hash": _dataset_hash(clean_series, policy, weights),
        "feature_scope": policy.feature_scope,
        "bar_interval": policy.bar_interval,
        "market_type": policy.market_type,
        "direction": policy.direction,
        "feature_factor_ids": sorted(weights),
        "excluded_factor_ids": sorted(registry.ids - set(weights)),
        "feature_scope_limitations": (
            [
                "Public Binance spot klines provide OHLCV only for this replay.",
                "CVD, open interest, funding, and live spread factors are excluded.",
                "This is limited historical evidence and is not equivalent to the live policy.",
            ]
            if policy.feature_scope == "ohlcv_only_limited"
            else [
                "Funding and Open Interest are sourced from a public historical REST replay.",
                "available_at is currently a source-time proxy, not an exchange publication-time proof.",
                "CVD and live spread factors remain excluded; this is limited evidence, not live policy evidence.",
            ]
            if policy.feature_scope == "ohlcv_plus_derivatives_limited"
            else []
        ),
        "split_config": {
            "train_ratio": policy.train_ratio,
            "validation_ratio": policy.validation_ratio,
            "test_ratio": round(1.0 - policy.train_ratio - policy.validation_ratio, 8),
            "embargo_bars": policy.embargo_bars,
            "oos_folds": policy.oos_folds,
            "dates": {key: list(value) for key, value in partitions.items()},
        },
        "backtest_config": policy.backtest.__dict__,
        "weights": dict(weights),
        "partitions": {},
        "oos_folds": [],
        "oos_fold_count": 0,
    }
    all_outcomes: list[TradeOutcome] = []
    partition_outcomes: dict[str, list[TradeOutcome]] = {}
    for name in ("train", "validation", "test"):
        outcomes: list[TradeOutcome] = []
        censored = 0
        embargoed = 0
        for item in clean_series:
            partition_config = policy if name != "train" else ValidationConfig(
                strategy_version=policy.strategy_version,
                dataset_version=policy.dataset_version,
                feature_scope=policy.feature_scope,
                bar_interval=policy.bar_interval,
                train_ratio=policy.train_ratio,
                validation_ratio=policy.validation_ratio,
                embargo_bars=0,
                backtest=policy.backtest,
                bootstrap_iterations=policy.bootstrap_iterations,
                bootstrap_seed=policy.bootstrap_seed,
                oos_folds=policy.oos_folds,
                market_type=policy.market_type,
                direction=policy.direction,
            )
            values, count, embargo_count = _run_partition(item, partitions[name], registry=registry, weights=weights, config=partition_config, score_policy=score_policy)
            outcomes.extend(values)
            censored += count
            embargoed += embargo_count
        all_outcomes.extend(outcomes)
        partition_outcomes[name] = list(outcomes)
        summary = summarize_outcomes(
            outcomes,
            bootstrap_iterations=policy.bootstrap_iterations,
            bootstrap_seed=policy.bootstrap_seed,
        )
        report["partitions"][name] = {
            "summary": summary,
            "censored_trade_count": censored,
            "embargoed_bar_count": embargoed,
            "symbols": sorted({item.symbol for item in outcomes if item.symbol}),
        }
    report["overall"] = summarize_outcomes(
        all_outcomes,
        bootstrap_iterations=policy.bootstrap_iterations,
        bootstrap_seed=policy.bootstrap_seed,
    )
    report["test_evidence_status"] = report["partitions"]["test"]["summary"]["evidence_status"]
    report["test_is_locked"] = True

    # Keep the original summary for compatibility, and add an independent
    # expanding walk-forward evidence chain with disjoint OOS test windows.
    oos_outcomes: list[TradeOutcome] = []
    oos_outcomes_by_fold: dict[int, list[TradeOutcome]] = {}
    for fold_number, fold_dates in enumerate(_rolling_oos_partitions(all_dates, policy.oos_folds), start=1):
        fold_outcomes: list[TradeOutcome] = []
        censored = 0
        embargoed = 0
        for item in clean_series:
            values, censored_count, embargoed_count = _run_partition(
                item,
                fold_dates["test"],
                registry=registry,
                weights=weights,
                config=policy,
                score_policy=score_policy,
            )
            fold_outcomes.extend(values)
            censored += censored_count
            embargoed += embargoed_count
        oos_outcomes.extend(fold_outcomes)
        oos_outcomes_by_fold[fold_number] = list(fold_outcomes)
        report["oos_folds"].append({
            "fold": fold_number,
            "dates": {key: list(value) for key, value in fold_dates.items()},
            "summary": summarize_outcomes(
                fold_outcomes,
                bootstrap_iterations=policy.bootstrap_iterations,
                bootstrap_seed=policy.bootstrap_seed,
            ),
            "censored_trade_count": censored,
            "embargoed_bar_count": embargoed,
            "test_is_locked": True,
        })
    report["oos_fold_count"] = len(report["oos_folds"])
    report["oos_summary"] = summarize_outcomes(
        oos_outcomes,
        bootstrap_iterations=policy.bootstrap_iterations,
        bootstrap_seed=policy.bootstrap_seed,
    )
    stress_backtest = replace(
        policy.backtest,
        fee_bps_per_side=policy.backtest.fee_bps_per_side * 2.0,
        slippage_bps_per_side=policy.backtest.slippage_bps_per_side * 2.0,
    )
    stress_config = replace(policy, backtest=stress_backtest)
    stress_outcomes: list[TradeOutcome] = []
    for item in clean_series:
        values, _, _ = _run_partition(
            item,
            partitions["test"],
            registry=registry,
            weights=weights,
            config=stress_config,
            score_policy=score_policy,
        )
        stress_outcomes.extend(values)
    report["stress"] = {
        "cost_multiplier": 2.0,
        "backtest_config": stress_backtest.__dict__,
        "test": summarize_outcomes(
            stress_outcomes,
            bootstrap_iterations=policy.bootstrap_iterations,
            bootstrap_seed=policy.bootstrap_seed,
        ),
    }
    report["validation_gate"] = evaluate_validation_gate(report)
    return {
        "report": report,
        "outcomes": all_outcomes,
        "partition_outcomes": partition_outcomes,
        "oos_outcomes_by_fold": oos_outcomes_by_fold,
    }
