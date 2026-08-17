from __future__ import annotations

"""Point-in-time Stock Quant validation and model comparison.

The module deliberately keeps model selection, performance measurement, and
execution eligibility separate.  A model may rank a historical row, but it
cannot turn a stale quote, an incomplete candle, or a failed data gate into a
trade instruction.
"""

import hashlib
import importlib.util
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .quant_dataset import (
    DatasetIntegrityError,
    _fit_logistic,
    _predict,
    build_quant_dataset,
    read_quant_dataset,
    register_model_artifact,
)
from .stock_quant import (
    MODEL_0_VERSION,
    build_stock_quant_dataset,
    build_model0_label,
    build_model0_features,
)
from .stock_store import connect
from .theme_prediction import _apply_isotonic, _apply_platt, _fit_isotonic, _fit_platt


STOCK_QUANT_VALIDATION_VERSION = "stock_quant_validation_v1.0.0"
STOCK_QUANT_MODEL_VERSION = "stock_quant_models_v1.0.0"
BASELINE_COMMISSION_BPS_PER_SIDE = 1.0
BASELINE_SLIPPAGE_BPS_PER_SIDE = 5.0
BOOTSTRAP_SAMPLES = 500
MIN_TEST_TRADES = 100
MAX_DRAWDOWN_GATE = 8.0


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _finite(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _mean(values: Iterable[float]) -> float | None:
    rows = [float(value) for value in values]
    return sum(rows) / len(rows) if rows else None


def _percentile(values: Iterable[float], percentile: float) -> float | None:
    rows = sorted(float(value) for value in values)
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    position = max(0.0, min(1.0, percentile)) * (len(rows) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return rows[lower]
    weight = position - lower
    return rows[lower] * (1.0 - weight) + rows[upper] * weight


def _bootstrap_interval(values: list[float], *, seed: int) -> list[float | None]:
    if not values:
        return [None, None]
    state = seed & 0xFFFFFFFF
    means: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        selected: list[float] = []
        for _ in values:
            state = (1664525 * state + 1013904223) & 0xFFFFFFFF
            selected.append(values[state % len(values)])
        means.append(sum(selected) / len(selected))
    return [
        round(float(_percentile(means, 0.025)), 8),
        round(float(_percentile(means, 0.975)), 8),
    ]


def _auc(labels: list[int], probabilities: list[float]) -> float | None:
    positives = [prediction for label, prediction in zip(labels, probabilities) if label == 1]
    negatives = [prediction for label, prediction in zip(labels, probabilities) if label == 0]
    if not positives or not negatives:
        return None
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def _ece(labels: list[int], probabilities: list[float], bins: int = 10) -> float | None:
    if not labels:
        return None
    error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            position
            for position, probability in enumerate(probabilities)
            if lower <= probability < upper or (index == bins - 1 and probability == 1.0)
        ]
        if members:
            observed = sum(labels[position] for position in members) / len(members)
            expected = sum(probabilities[position] for position in members) / len(members)
            error += len(members) / len(labels) * abs(observed - expected)
    return error


def _classification_metrics(rows: list[dict[str, Any]], probabilities: list[float], *, seed: int) -> dict[str, Any]:
    if len(rows) != len(probabilities):
        raise DatasetIntegrityError("Classification prediction count does not match dataset rows.")
    if not rows:
        return {"sample_count": 0, "auc": None, "brier": None, "ece": None, "positive_rate": None}
    labels = [int(float(row["label"].get("target", 0.0)) >= 0.5) for row in rows]
    values = [max(1e-6, min(1.0 - 1e-6, float(value))) for value in probabilities]
    auc = _auc(labels, values)
    ece = _ece(labels, values)
    return {
        "sample_count": len(rows),
        "auc": round(auc, 8) if auc is not None else None,
        "brier": round(sum((value - label) ** 2 for value, label in zip(values, labels)) / len(values), 8),
        "ece": round(ece, 8) if ece is not None else None,
        "positive_rate": round(sum(labels) / len(labels), 8),
        "mean_probability": round(sum(values) / len(values), 8),
        "mean_r": round(float(_mean(float(row["label"].get("realized_r") or 0.0) for row in rows) or 0.0), 8),
        "mean_r_bootstrap_95": _bootstrap_interval(
            [float(row["label"].get("realized_r") or 0.0) for row in rows], seed=seed
        ),
    }


def _equity_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _trade_metrics(rows: list[dict[str, Any]], realized_r: list[float], *, seed: int) -> dict[str, Any]:
    if len(rows) != len(realized_r):
        raise DatasetIntegrityError("Trade result count does not match dataset rows.")
    if not rows:
        return {
            "sample_count": 0,
            "win_rate": None,
            "average_r": None,
            "average_win_r": None,
            "average_loss_r": None,
            "profit_factor": None,
            "max_drawdown_r": None,
            "target_first_rate": None,
            "stop_first_rate": None,
            "average_r_bootstrap_95": [None, None],
        }
    winners = [value for value in realized_r if value > 0]
    losers = [value for value in realized_r if value <= 0]
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else None
    return {
        "sample_count": len(rows),
        "win_rate": round(len(winners) / len(realized_r), 8),
        "average_r": round(sum(realized_r) / len(realized_r), 8),
        "average_win_r": round(sum(winners) / len(winners), 8) if winners else None,
        "average_loss_r": round(sum(losers) / len(losers), 8) if losers else None,
        "profit_factor": round(profit_factor, 8) if math.isfinite(profit_factor or 0.0) else "infinite" if profit_factor else None,
        "max_drawdown_r": round(_equity_drawdown(realized_r), 8),
        "target_first_rate": round(sum(bool(row["label"].get("target_first")) for row in rows) / len(rows), 8),
        "stop_first_rate": round(sum(bool(row["label"].get("stop_first")) for row in rows) / len(rows), 8),
        "average_r_bootstrap_95": _bootstrap_interval(realized_r, seed=seed),
        "total_r": round(sum(realized_r), 8),
    }


def _cost_adjusted_r(row: dict[str, Any], *, commission_bps: float, slippage_bps: float) -> float:
    label = row["label"]
    base_commission = float(label.get("commission_bps_per_side") or BASELINE_COMMISSION_BPS_PER_SIDE)
    base_slippage = float(label.get("slippage_bps_per_side") or BASELINE_SLIPPAGE_BPS_PER_SIDE)
    entry = float(label.get("entry_price") or 0.0)
    exit_price = float(label.get("exit_price") or 0.0)
    stop = float(label.get("stop_price") or 0.0)
    risk = max(entry - stop, 1e-9)
    extra_commission = (entry + exit_price) * max(0.0, commission_bps - base_commission) / 10_000
    extra_slippage = (entry + exit_price) * max(0.0, slippage_bps - base_slippage) / 10_000
    return float(label.get("realized_r") or 0.0) - (extra_commission + extra_slippage) / risk


def _sensitivity(rows: list[dict[str, Any]], *, seed: int) -> dict[str, Any]:
    scenarios = {
        "baseline": (BASELINE_COMMISSION_BPS_PER_SIDE, BASELINE_SLIPPAGE_BPS_PER_SIDE),
        "conservative": (3.0, 10.0),
        "stressed": (5.0, 20.0),
    }
    result: dict[str, Any] = {}
    for name, (commission, slippage) in scenarios.items():
        values = [_cost_adjusted_r(row, commission_bps=commission, slippage_bps=slippage) for row in rows]
        result[name] = {
            "commission_bps_per_side": commission,
            "slippage_bps_per_side": slippage,
            "trade_metrics": _trade_metrics(rows, values, seed=seed),
        }
    return result


def _dimension_summary(rows: list[dict[str, Any]], values: list[float], field: str) -> dict[str, Any]:
    groups: dict[str, list[float]] = {}
    for row, value in zip(rows, values):
        group = str(row["label"].get(field) or "unknown")
        groups.setdefault(group, []).append(float(value))
    return {
        key: {
            "sample_count": len(group_values),
            "average_r": round(sum(group_values) / len(group_values), 8),
            "win_rate": round(sum(value > 0 for value in group_values) / len(group_values), 8),
        }
        for key, group_values in sorted(groups.items())
    }


def _concentration(rows: list[dict[str, Any]], values: list[float]) -> dict[str, Any]:
    by_symbol: dict[str, list[float]] = {}
    for row, value in zip(rows, values):
        by_symbol.setdefault(row["symbol"], []).append(float(value))
    symbol_totals = {symbol: sum(items) for symbol, items in by_symbol.items()}
    positive_profit = sum(max(value, 0.0) for value in symbol_totals.values())
    ranked = sorted(symbol_totals.items(), key=lambda pair: (pair[1], pair[0]), reverse=True)
    top_symbol = ranked[0] if ranked else (None, 0.0)
    top_five = {symbol for symbol, _ in ranked[:5]}
    excluded = [value for row, value in zip(rows, values) if row["symbol"] not in top_five]
    return {
        "symbol_count": len(symbol_totals),
        "top_symbol": top_symbol[0],
        "top_symbol_profit_contribution": round(top_symbol[1] / positive_profit, 8) if positive_profit > 0 else None,
        "top_five_symbols": [symbol for symbol, _ in ranked[:5]],
        "top_five_excluded_average_r": round(sum(excluded) / len(excluded), 8) if excluded else None,
        "profit_contribution_basis": "positive_symbol_profit",
    }


def _evidence_level(sample_count: int) -> str:
    if sample_count < 30:
        return "insufficient"
    if sample_count < 100:
        return "limited"
    return "robust_sample_single_oos_fold"


def _select_threshold(rows: list[dict[str, Any]], probabilities: list[float]) -> dict[str, Any]:
    if not rows:
        return {"threshold": 0.5, "validation_sample_count": 0, "selection_status": "no_validation_rows"}
    minimum = max(10, min(30, len(rows) // 10))
    candidates = [round(0.35 + index * 0.05, 2) for index in range(10)]
    evaluated: list[dict[str, Any]] = []
    for threshold in candidates:
        selected = [
            float(row["label"].get("realized_r") or 0.0)
            for row, probability in zip(rows, probabilities)
            if probability >= threshold
        ]
        if len(selected) < minimum:
            continue
        evaluated.append({"threshold": threshold, "sample_count": len(selected), "average_r": sum(selected) / len(selected)})
    if not evaluated:
        return {"threshold": 0.5, "validation_sample_count": len(rows), "selection_status": "fixed_default_no_threshold_met_minimum"}
    chosen = max(evaluated, key=lambda item: (item["average_r"], item["sample_count"], -item["threshold"]))
    return {"threshold": chosen["threshold"], "validation_sample_count": chosen["sample_count"], "selection_status": "validation_only", "candidates": evaluated}


def _model0_probability(row: dict[str, Any]) -> float:
    score = _finite(row["features"].get("model0_total_score"), 0.0) or 0.0
    return max(1e-6, min(1.0 - 1e-6, score / 100.0))


def _return_expectation(train_rows: list[dict[str, Any]], probability: float) -> float:
    winners = [float(row["label"].get("realized_r") or 0.0) for row in train_rows if float(row["label"].get("realized_r") or 0.0) > 0]
    losers = [float(row["label"].get("realized_r") or 0.0) for row in train_rows if float(row["label"].get("realized_r") or 0.0) <= 0]
    positive = _mean(winners) or 0.0
    negative = _mean(losers) or 0.0
    return float(probability) * positive + (1.0 - float(probability)) * negative


def _prediction_interval(train_rows: list[dict[str, Any]], expected: float) -> dict[str, Any]:
    outcomes = [float(row["label"].get("realized_r") or 0.0) for row in train_rows]
    if not outcomes:
        return {"expected_r": expected, "lower_r": None, "upper_r": None, "downside_risk_r": None, "source": "unavailable"}
    lower = _percentile(outcomes, 0.10)
    upper = _percentile(outcomes, 0.90)
    return {
        "expected_r": round(expected, 8),
        "lower_r": round(float(lower), 8) if lower is not None else None,
        "upper_r": round(float(upper), 8) if upper is not None else None,
        "downside_risk_r": round(float(lower), 8) if lower is not None else None,
        "source": "train_outcome_distribution_only",
    }


def _available_lightgbm_models(
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    feature_order: list[str],
    random_seed: int,
) -> list[dict[str, Any]]:
    unavailable = "Optional lightgbm dependency is not installed."
    if importlib.util.find_spec("lightgbm") is None:
        return [
            {"model_name": "lightgbm_classifier", "model_kind": "classification", "status": "not_installed", "reason": unavailable},
            {"model_name": "lightgbm_regressor", "model_kind": "regression", "status": "not_installed", "reason": unavailable},
            {"model_name": "lightgbm_quantile", "model_kind": "quantile", "status": "not_installed", "reason": unavailable},
        ]
    import lightgbm as lgb  # type: ignore[import-not-found]

    matrix = lambda rows: [[float(row["features"].get(feature) or 0.0) for feature in feature_order] for row in rows]
    train_matrix = matrix(train_rows)
    validation_matrix = matrix(validation_rows)
    test_matrix = matrix(test_rows)
    direction = [int(float(row["label"].get("target") or 0.0) >= 0.5) for row in train_rows]
    returns = [float(row["label"].get("realized_r") or 0.0) for row in train_rows]
    reports: list[dict[str, Any]] = []
    if len(set(direction)) >= 2:
        classifier = lgb.LGBMClassifier(
            objective="binary", n_estimators=80, learning_rate=0.05, max_depth=3,
            random_state=random_seed, verbosity=-1,
        )
        classifier.fit(train_matrix, direction)
        reports.append({
            "model_name": "lightgbm_classifier",
            "model_kind": "classification",
            "status": "available",
            "probabilities": {
                "train": [float(value[1]) for value in classifier.predict_proba(train_matrix)],
                "validation": [float(value[1]) for value in classifier.predict_proba(validation_matrix)],
                "test": [float(value[1]) for value in classifier.predict_proba(test_matrix)],
            },
            "artifact": {
                "kind": "lightgbm_classifier",
                "feature_order": feature_order,
                "params": {"n_estimators": 80, "learning_rate": 0.05, "max_depth": 3, "seed": random_seed},
                "model_text": classifier.booster_.model_to_string(),
            },
        })
    else:
        reports.append({"model_name": "lightgbm_classifier", "model_kind": "classification", "status": "not_fit", "reason": "Training labels contain one class only."})
    regressor = lgb.LGBMRegressor(
        objective="regression", n_estimators=80, learning_rate=0.05, max_depth=3,
        random_state=random_seed, verbosity=-1,
    )
    regressor.fit(train_matrix, returns)
    reports.append({
        "model_name": "lightgbm_regressor",
        "model_kind": "regression",
        "status": "available",
        "expected": {
            "train": [float(value) for value in regressor.predict(train_matrix)],
            "validation": [float(value) for value in regressor.predict(validation_matrix)],
            "test": [float(value) for value in regressor.predict(test_matrix)],
        },
        "artifact": {
            "kind": "lightgbm_regressor",
            "feature_order": feature_order,
            "params": {"n_estimators": 80, "learning_rate": 0.05, "max_depth": 3, "seed": random_seed},
            "model_text": regressor.booster_.model_to_string(),
        },
    })
    quantile_models: dict[float, Any] = {}
    for alpha in (0.25, 0.75):
        model = lgb.LGBMRegressor(
            objective="quantile", alpha=alpha, n_estimators=80, learning_rate=0.05,
            max_depth=3, random_state=random_seed, verbosity=-1,
        )
        model.fit(train_matrix, returns)
        quantile_models[alpha] = model
    reports.append({
        "model_name": "lightgbm_quantile",
        "model_kind": "quantile",
        "status": "available",
        "expected": {
            "train": [(_q25 + _q75) / 2 for _q25, _q75 in zip(quantile_models[0.25].predict(train_matrix), quantile_models[0.75].predict(train_matrix))],
            "validation": [(_q25 + _q75) / 2 for _q25, _q75 in zip(quantile_models[0.25].predict(validation_matrix), quantile_models[0.75].predict(validation_matrix))],
            "test": [(_q25 + _q75) / 2 for _q25, _q75 in zip(quantile_models[0.25].predict(test_matrix), quantile_models[0.75].predict(test_matrix))],
        },
        "intervals": {
            "train": [[float(a), float(b)] for a, b in zip(quantile_models[0.25].predict(train_matrix), quantile_models[0.75].predict(train_matrix))],
            "validation": [[float(a), float(b)] for a, b in zip(quantile_models[0.25].predict(validation_matrix), quantile_models[0.75].predict(validation_matrix))],
            "test": [[float(a), float(b)] for a, b in zip(quantile_models[0.25].predict(test_matrix), quantile_models[0.75].predict(test_matrix))],
        },
        "artifact": {
            "kind": "lightgbm_quantile_pair",
            "feature_order": feature_order,
            "params": {"alphas": [0.25, 0.75], "n_estimators": 80, "learning_rate": 0.05, "max_depth": 3, "seed": random_seed},
            "model_text": {"q25": quantile_models[0.25].booster_.model_to_string(), "q75": quantile_models[0.75].booster_.model_to_string()},
        },
    })
    return reports


def _calibrate(
    validation_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    validation_probabilities: list[float],
    test_probabilities: list[float],
    *,
    seed: int,
) -> dict[str, Any]:
    labels = [int(float(row["label"].get("target") or 0.0) >= 0.5) for row in validation_rows]
    if not validation_rows or len(set(labels)) < 2:
        return {"status": "not_available", "reason": "Validation labels need both classes for calibration."}
    candidates: list[dict[str, Any]] = []
    for method, fitter, applier in (("platt", _fit_platt, _apply_platt), ("isotonic", _fit_isotonic, _apply_isotonic)):
        parameters = fitter(validation_probabilities, labels)
        validation_calibrated = applier(parameters, validation_probabilities)
        test_calibrated = applier(parameters, test_probabilities)
        validation_metrics = _classification_metrics(validation_rows, validation_calibrated, seed=seed)
        test_metrics = _classification_metrics(test_rows, test_calibrated, seed=seed + 1)
        candidates.append({"method": method, "parameters": parameters, "validation_metrics": validation_metrics, "test_metrics": test_metrics})
    chosen = min(candidates, key=lambda item: (float(item["validation_metrics"].get("brier") or 999.0), float(item["validation_metrics"].get("ece") or 999.0), item["method"]))
    return {"status": "validation_only", "selected_method": chosen["method"], "candidates": candidates}


def _segment_metrics(rows: list[dict[str, Any]], values: list[float]) -> dict[str, Any]:
    return {
        "sector": _dimension_summary(rows, values, "sector"),
        "market_regime": _dimension_summary(rows, values, "market_regime"),
        "volatility_bucket": _dimension_summary(rows, values, "volatility_bucket"),
    }


def _build_report(
    candidate: dict[str, Any],
    *,
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    random_seed: int,
) -> dict[str, Any]:
    name = str(candidate["model_name"])
    kind = str(candidate["model_kind"])
    if candidate.get("status") not in {None, "available", "verified"}:
        return {"model_name": name, "model_kind": kind, "status": candidate.get("status", "unavailable"), "evidence_level": "insufficient", "reason": candidate.get("reason", "Model could not be fit.")}
    probabilities = candidate.get("probabilities")
    expected = candidate.get("expected")
    if probabilities is None:
        if name == "model0_rule":
            probabilities = {split: [_model0_probability(row) for row in rows] for split, rows in (("train", train_rows), ("validation", validation_rows), ("test", test_rows))}
        else:
            artifact = candidate["artifact"]
            probabilities = {split: [float(_predict(artifact, row)) for row in rows] for split, rows in (("train", train_rows), ("validation", validation_rows), ("test", test_rows))}
    if expected is None:
        expected = {
            split: [_return_expectation(train_rows, probability) for probability in values]
            for split, values in probabilities.items()
        }
    calibration = _calibrate(validation_rows, test_rows, list(probabilities["validation"]), list(probabilities["test"]), seed=random_seed)
    selected_probabilities = list(probabilities["test"])
    selected_validation_probabilities = list(probabilities["validation"])
    if calibration.get("status") == "validation_only":
        selected_method = str(calibration["selected_method"])
        selected_candidate = next(item for item in calibration["candidates"] if item["method"] == selected_method)
        parameters = selected_candidate["parameters"]
        if selected_method == "platt":
            selected_validation_probabilities = _apply_platt(parameters, selected_validation_probabilities)
            selected_probabilities = _apply_platt(parameters, selected_probabilities)
        else:
            selected_validation_probabilities = _apply_isotonic(parameters, selected_validation_probabilities)
            selected_probabilities = _apply_isotonic(parameters, selected_probabilities)
    selection = _select_threshold(validation_rows, selected_validation_probabilities)
    threshold = float(selection["threshold"])
    selected_test_rows: list[dict[str, Any]]
    selected_test_values: list[float]
    if kind == "classification":
        selected_validation_pairs = [(row, probability) for row, probability in zip(validation_rows, selected_validation_probabilities) if probability >= threshold]
        selected_validation_rows = [row for row, _ in selected_validation_pairs]
        selected_validation_values = [float(row["label"].get("realized_r") or 0.0) for row in selected_validation_rows]
        selected_pairs = [(row, probability) for row, probability in zip(test_rows, selected_probabilities) if probability >= threshold]
        selected_test_rows = [row for row, _ in selected_pairs]
        selected_test_values = [float(row["label"].get("realized_r") or 0.0) for row in selected_test_rows]
    else:
        # Regression and quantile models are ranked by expected return; the
        # same validation-only top-half rule keeps model comparison explicit.
        validation_expected = [float(value) for value in expected["validation"]]
        rank_cut = _percentile(validation_expected, 0.50) or 0.0
        selected_validation_pairs = [(row, value) for row, value in zip(validation_rows, expected["validation"]) if float(value) >= rank_cut]
        selected_validation_rows = [row for row, _ in selected_validation_pairs]
        selected_validation_values = [float(row["label"].get("realized_r") or 0.0) for row in selected_validation_rows]
        selected_pairs = [(row, value) for row, value in zip(test_rows, expected["test"]) if float(value) >= rank_cut]
        selected_test_rows = [row for row, _ in selected_pairs]
        selected_test_values = [float(row["label"].get("realized_r") or 0.0) for row in selected_test_rows]
        selection = {"selection_rule": "validation_expected_return_median", "validation_cut": rank_cut, "validation_sample_count": len(validation_rows), "selection_status": "validation_only"}
    all_test_values = [float(row["label"].get("realized_r") or 0.0) for row in test_rows]
    validation_selection_metrics = _trade_metrics(selected_validation_rows, selected_validation_values, seed=random_seed + 9)
    all_test_trade_metrics = _trade_metrics(test_rows, all_test_values, seed=random_seed + 10)
    selected_trade_metrics = _trade_metrics(selected_test_rows, selected_test_values, seed=random_seed + 11)
    classification_by_split = {
        split: _classification_metrics(split_rows, list(probabilities[split]), seed=random_seed + offset)
        for offset, (split, split_rows) in enumerate((("train", train_rows), ("validation", validation_rows), ("test", test_rows)))
    } if kind == "classification" else {"train": None, "validation": None, "test": None}
    expected_intervals = {
        split: _prediction_interval(train_rows, float(_mean(expected[split]) or 0.0))
        for split in ("train", "validation", "test")
    }
    gate_checks = {
        "minimum_test_trades": selected_trade_metrics["sample_count"] >= MIN_TEST_TRADES,
        "average_r_bootstrap_lower_gt_zero": bool(selected_trade_metrics["average_r_bootstrap_95"][0] is not None and selected_trade_metrics["average_r_bootstrap_95"][0] > 0),
        "profit_factor_at_least_1_25": selected_trade_metrics["profit_factor"] == "infinite" or bool(selected_trade_metrics["profit_factor"] is not None and float(selected_trade_metrics["profit_factor"]) >= 1.25),
        "max_drawdown_at_most_8_r": bool(selected_trade_metrics["max_drawdown_r"] is not None and float(selected_trade_metrics["max_drawdown_r"]) <= MAX_DRAWDOWN_GATE),
    }
    return {
        "model_name": name,
        "model_kind": kind,
        "status": "verified",
        "evidence_level": _evidence_level(int(selected_trade_metrics["sample_count"])),
        "selection": selection,
        "validation_selection_metrics": validation_selection_metrics,
        "calibration": calibration,
        "classification_metrics": classification_by_split,
        "expected_return_intervals": expected_intervals,
        "all_test_trades": all_test_trade_metrics,
        "selected_test_trades": selected_trade_metrics,
        "cost_sensitivity": _sensitivity(selected_test_rows, seed=random_seed + 12),
        "segments": _segment_metrics(selected_test_rows, selected_test_values),
        "concentration": _concentration(selected_test_rows, selected_test_values),
        "gate_checks": gate_checks,
        "gate_status": "pass" if all(gate_checks.values()) else "no_go",
        "test_partition_used_for_selection": False,
        "model_version": STOCK_QUANT_MODEL_VERSION,
    }


def _model_candidates(dataset: dict[str, Any], random_seed: int) -> list[dict[str, Any]]:
    rows = dataset["items"]
    train_rows = [row for row in rows if row["split_name"] == "train"]
    validation_rows = [row for row in rows if row["split_name"] == "validation"]
    test_rows = [row for row in rows if row["split_name"] == "test"]
    feature_order = sorted({key for row in rows for key in row["features"]})
    logistic = _fit_logistic(train_rows, feature_order, random_seed)
    return [
        {"model_name": "model0_rule", "model_kind": "classification", "status": "available", "artifact": {"kind": "model0_score_probability", "model_version": MODEL_0_VERSION, "feature_id": "model0_total_score"}},
        {"model_name": "logistic", "model_kind": "classification", "status": "available", "artifact": logistic},
        *_available_lightgbm_models(train_rows, validation_rows, test_rows, feature_order, random_seed),
    ]


def run_stock_quant_validation(db_path: Path, dataset_id: str, *, random_seed: int = 20260817) -> dict[str, Any]:
    dataset = read_quant_dataset(db_path, dataset_id)
    if dataset["contract_version"] != "stock_quant_dataset_v1.0.0":
        raise DatasetIntegrityError("Stock Quant validation requires the sealed Model 0 dataset contract.")
    if dataset["integrity_status"] != "verified":
        raise DatasetIntegrityError("Stock Quant validation is blocked by dataset integrity.")
    if any("yahoo" in str(row["source_snapshot_id"]).lower() for row in dataset["items"]):
        raise DatasetIntegrityError("Yahoo reference rows cannot enter the Stock Quant validation dataset.")
    rows = dataset["items"]
    train_rows = [row for row in rows if row["split_name"] == "train"]
    validation_rows = [row for row in rows if row["split_name"] == "validation"]
    test_rows = [row for row in rows if row["split_name"] == "test"]
    if not train_rows or not validation_rows or not test_rows:
        raise DatasetIntegrityError("Stock Quant validation requires non-empty train, validation, and test partitions.")
    reports: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    for candidate in _model_candidates(dataset, random_seed):
        report = _build_report(candidate, train_rows=train_rows, validation_rows=validation_rows, test_rows=test_rows, random_seed=random_seed)
        if report["status"] == "verified":
            artifact = dict(candidate.get("artifact") or {})
            feature_order = sorted({key for row in rows for key in row["features"]})
            registered = register_model_artifact(
                db_path,
                dataset_id=dataset_id,
                model_name=str(candidate["model_name"]),
                model_version=f"{candidate['model_name']}_{STOCK_QUANT_VALIDATION_VERSION}",
                feature_order=feature_order,
                train_config={
                    "selection_partitions": ["train", "validation"],
                    "test_partition_used_for_selection": False,
                    "validation_threshold_or_cut": report["selection"],
                    "calibration_selection": report["calibration"].get("selected_method") if isinstance(report.get("calibration"), dict) else None,
                    "cost_config": {"commission_bps_per_side": BASELINE_COMMISSION_BPS_PER_SIDE, "slippage_bps_per_side": BASELINE_SLIPPAGE_BPS_PER_SIDE},
                    "random_seed": random_seed,
                },
                random_seed=random_seed,
                artifact=artifact,
                metrics={
                    "train": report["classification_metrics"].get("train") or {},
                    "validation": report["classification_metrics"].get("validation") or {},
                    "test": {**(report["classification_metrics"].get("test") or {}), **{f"selected_{key}": value for key, value in report["selected_test_trades"].items() if isinstance(value, (int, float))}},
                },
            )
            report["artifact_id"] = registered["artifact_id"]
            artifacts.append({"artifact_id": registered["artifact_id"], "model_name": candidate["model_name"]})
        reports.append(report)
    verified = [report for report in reports if report["status"] == "verified"]
    selection_candidates = [
        report for report in verified
        if report["selection"].get("validation_sample_count", 0) > 0
    ]
    selected_model = None
    if selection_candidates:
        selected_model = max(
            selection_candidates,
            key=lambda report: (
                float((report.get("validation_selection_metrics") or {}).get("average_r") or 0.0),
                float((report.get("validation_selection_metrics") or {}).get("sample_count") or 0),
                report["model_name"],
            ),
        )["model_name"]
    selected_report = next((report for report in reports if report["model_name"] == selected_model), None)
    gate_status = "pass" if selected_report and selected_report.get("gate_status") == "pass" else "no_go"
    summary_seed = {
        "validation_version": STOCK_QUANT_VALIDATION_VERSION,
        "model_version": STOCK_QUANT_MODEL_VERSION,
        "dataset_id": dataset_id,
        "dataset_hash": dataset["content_hash"],
        "test_partition_hash": dataset["test_partition_hash"],
        "oos_fold_count": 1,
        "random_seed": random_seed,
        "models": reports,
        "selected_model_by_train_validation": selected_model,
        "test_partition_used_for_selection": False,
        "gate_status": gate_status,
        "overall_gate_checks": {
            "selected_model_exists": selected_report is not None,
            "minimum_test_trades": bool(selected_report and selected_report.get("gate_checks", {}).get("minimum_test_trades")),
            "average_r_bootstrap_lower_gt_zero": bool(selected_report and selected_report.get("gate_checks", {}).get("average_r_bootstrap_lower_gt_zero")),
            "profit_factor_at_least_1_25": bool(selected_report and selected_report.get("gate_checks", {}).get("profit_factor_at_least_1_25")),
            "max_drawdown_at_most_8_r": bool(selected_report and selected_report.get("gate_checks", {}).get("max_drawdown_at_most_8_r")),
            "oos_fold_count_gate": False,
        },
        "artifacts": artifacts,
        "read_only_research": True,
    }
    content_hash = _hash(summary_seed)
    run_id = f"sqv_{content_hash[:24]}"
    created_at = _now()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO stock_quant_validation_runs(
              run_id, dataset_id, validation_version, status, gate_status,
              summary_json, content_hash, test_partition_hash, created_at
            ) VALUES (?, ?, ?, 'materialized', ?, ?, ?, ?, ?)
            """,
            (run_id, dataset_id, STOCK_QUANT_VALIDATION_VERSION, gate_status, _canonical(summary_seed), content_hash, dataset["test_partition_hash"], created_at),
        )
        for report in reports:
            report_hash = _hash({"run_id": run_id, **report})
            conn.execute(
                """
                INSERT OR IGNORE INTO stock_quant_validation_reports(
                  run_id, model_name, model_kind, status, evidence_level,
                  summary_json, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, report["model_name"], report["model_kind"], report["status"], report.get("evidence_level", "insufficient"), _canonical(report), report_hash, created_at),
            )
        conn.commit()
    return stock_quant_validation_detail(db_path, run_id)


def stock_quant_validation_detail(db_path: Path, run_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM stock_quant_validation_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown stock quant validation run: {run_id}")
        reports = [dict(item) for item in conn.execute("SELECT * FROM stock_quant_validation_reports WHERE run_id = ? ORDER BY model_name", (run_id,)).fetchall()]
    dataset = read_quant_dataset(db_path, str(row["dataset_id"]))
    if str(row["test_partition_hash"]) != dataset["test_partition_hash"]:
        raise DatasetIntegrityError("Stock Quant validation test partition hash does not match its dataset.")
    return {
        "status": row["status"],
        "run_id": row["run_id"],
        "dataset_id": row["dataset_id"],
        "validation_version": row["validation_version"],
        "gate_status": row["gate_status"],
        "summary": json.loads(row["summary_json"]),
        "reports": [{**report, "summary": json.loads(report.pop("summary_json"))} for report in reports],
        "content_hash": row["content_hash"],
        "test_partition_hash": row["test_partition_hash"],
        "dataset_integrity_status": dataset["integrity_status"],
        "read_only_research": True,
    }


def latest_stock_quant_validation(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT run_id FROM stock_quant_validation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if row is None:
        return {"status": "not_materialized", "runs": [], "read_only_research": True}
    return {"status": "materialized", "run": stock_quant_validation_detail(db_path, str(row["run_id"])), "read_only_research": True}


def _market_rows(conn: Any, symbol: str, interval: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT symbol, interval, open_time, open, high, low, close, volume, bar_state
        FROM market_candles
        WHERE symbol = ? AND interval = ? AND primary_source = 'longbridge_candles'
          AND provider_status = 'available' AND bar_state = 'closed_candle'
        ORDER BY open_time
        """,
        (symbol, interval),
    ).fetchall()
    return [dict(row) for row in rows]


def _market_return(rows: list[dict[str, Any]], periods: int) -> float | None:
    if len(rows) <= periods:
        return None
    current = _finite(rows[-1].get("close"))
    previous = _finite(rows[-1 - periods].get("close"))
    if current is None or previous is None or previous <= 0:
        return None
    return current / previous - 1.0


def _metadata(conn: Any, symbol: str) -> dict[str, Any]:
    row = conn.execute("SELECT sector, layer, tags_json FROM stock_universe WHERE symbol = ?", (symbol,)).fetchone()
    if row is None:
        return {"sector": "unknown", "layer": "unknown"}
    return {"sector": str(row["sector"] or "unknown"), "layer": str(row["layer"] or "unknown")}


def _volatility_bucket(snapshot: dict[str, Any]) -> str:
    atr_pct = _finite((snapshot.get("values") or {}).get("risk_atr_pct_20"))
    if atr_pct is None:
        return "unknown"
    if atr_pct <= 3.5:
        return "low"
    if atr_pct <= 7.0:
        return "medium"
    return "high"


def _market_regime(daily_benchmarks: dict[str, list[dict[str, Any]]], as_of: str) -> str:
    values: dict[str, float | None] = {}
    for symbol, rows in daily_benchmarks.items():
        eligible = [row for row in rows if str(row.get("open_time")) <= as_of]
        values[symbol] = _market_return(eligible, 20)
    spy, qqq = values.get("SPY"), values.get("QQQ")
    if spy is not None and qqq is not None and spy > 0 and qqq > 0:
        return "risk_on"
    if spy is not None and qqq is not None and spy < 0 and qqq < 0:
        return "risk_off"
    return "data_caution"


def build_stock_quant_cache_dataset(
    db_path: Path,
    *,
    symbols: Iterable[str] | None = None,
    dataset_id: str = "",
    universe_registry_id: str = "stock_universe_active_v1",
    max_items_per_symbol: int = 40,
    stride: int = 5,
    min_daily_bars: int = 220,
    min_confirmation_bars: int = 20,
    horizon_bars: int = 5,
    embargo_days: int = 5,
) -> dict[str, Any]:
    """Build a bounded, Longbridge-only historical Model 0 dataset.

    The cache is intentionally explicit about its limitations: it uses only
    canonical Longbridge candles, excludes forming bars and Yahoo rows, and
    stores a source id for every signal date.  It does not invent historical
    universe membership or corporate-action data.
    """

    requested = {str(symbol).upper().strip() for symbol in (symbols or ()) if str(symbol).strip()}
    with connect(db_path) as conn:
        universe = [str(row["symbol"]).upper() for row in conn.execute("SELECT symbol FROM stock_universe WHERE active = 1 ORDER BY rank, symbol").fetchall()]
        selected_symbols = [symbol for symbol in universe if not requested or symbol in requested]
        benchmark_rows = {symbol: _market_rows(conn, symbol, "1d") for symbol in ("SPY", "QQQ")}
        build_stats = {"universe_symbols": len(selected_symbols), "eligible_symbols": 0, "skipped_symbols": {}, "candidate_items": 0, "items": 0}
        items: list[dict[str, Any]] = []
        for symbol in selected_symbols:
            daily = _market_rows(conn, symbol, "1d")
            confirmation = _market_rows(conn, symbol, "1h")
            candidates = list(range(max(0, min_daily_bars - 1), max(0, len(daily) - horizon_bars - 1), max(1, stride)))
            build_stats["candidate_items"] += len(candidates)
            if len(daily) < min_daily_bars:
                build_stats["skipped_symbols"][symbol] = "daily_history_below_minimum"
                continue
            if len(confirmation) < min_confirmation_bars:
                build_stats["skipped_symbols"][symbol] = "confirmation_history_below_minimum"
                continue
            if len(benchmark_rows["SPY"]) < 25 or len(benchmark_rows["QQQ"]) < 25:
                build_stats["skipped_symbols"][symbol] = "benchmark_history_missing"
                continue
            candidate_items: list[dict[str, Any]] = []
            metadata = _metadata(conn, symbol)
            for index in candidates:
                signal_time = str(daily[index]["open_time"])
                # Build the feature snapshot first so the ATR-based plan is
                # derived only from information available at signal time.
                feature_snapshot = build_model0_features(
                    symbol,
                    daily[: index + 1],
                    confirmation,
                    benchmark_bars=benchmark_rows,
                    as_of_time=signal_time,
                    source="longbridge_candles",
                    confirmation_timeframe="1H",
                )
                if not feature_snapshot.get("eligibility", {}).get("eligible"):
                    continue
                close = _finite(daily[index].get("close"))
                atr_pct = _finite((feature_snapshot.get("values") or {}).get("risk_atr_pct_20"))
                if close is None or atr_pct is None or atr_pct <= 0:
                    continue
                risk_pct = max(1.5, atr_pct * 1.5)
                stop_price = close * (1.0 - risk_pct / 100.0)
                target_price = close * (1.0 + risk_pct * 2.0 / 100.0)
                label = build_model0_label(
                    daily,
                    index,
                    stop_price,
                    target_price,
                    horizon_bars=horizon_bars,
                    commission_bps_per_side=BASELINE_COMMISSION_BPS_PER_SIDE,
                    slippage_bps_per_side=BASELINE_SLIPPAGE_BPS_PER_SIDE,
                )
                if not label.get("completed"):
                    continue
                item = {
                    "item_id": f"{symbol}-{feature_snapshot['signal_time']}",
                    "symbol": symbol,
                    "signal_time": feature_snapshot["signal_time"],
                    "feature_available_at": feature_snapshot["feature_available_at"],
                    "label_end_time": label["label_end_time"],
                    "source_snapshot_id": f"lb_market_candles:{symbol}:1d:{signal_time}",
                    "features": {str(key): value for key, value in (feature_snapshot.get("values") or {}).items()},
                    "label": label,
                    "feature_snapshot": feature_snapshot,
                    "model_version": MODEL_0_VERSION,
                }
                item["label"].update({
                    "sector": metadata["sector"],
                    "layer": metadata["layer"],
                    "market_regime": _market_regime(benchmark_rows, signal_time),
                    "volatility_bucket": _volatility_bucket(item["feature_snapshot"]),
                    "plan_config": {"atr_multiple": 1.5, "target_r_multiple": 2.0},
                })
                candidate_items.append(item)
            if max_items_per_symbol > 0 and len(candidate_items) > max_items_per_symbol:
                candidate_items = candidate_items[-max_items_per_symbol:]
            if candidate_items:
                build_stats["eligible_symbols"] += 1
                build_stats["items"] += len(candidate_items)
                items.extend(candidate_items)
            else:
                build_stats["skipped_symbols"][symbol] = "no_point_in_time_eligible_items"
    if not items:
        raise DatasetIntegrityError("Longbridge cache did not produce any eligible Stock Quant items.")
    if len({str(item["signal_time"])[:10] for item in items}) < 30:
        raise DatasetIntegrityError("Longbridge cache needs at least 30 distinct signal dates for the 60/20/20 split with embargo.")
    computed_id = dataset_id or f"stock-model0-lb-{_hash({'items': items, 'config': build_stats})[:20]}"
    dataset = build_stock_quant_dataset(
        db_path,
        items,
        dataset_id=computed_id,
        universe_registry_id=universe_registry_id,
        source_policy_version="longbridge_pit_stock_quant_v1",
        embargo_days=embargo_days,
    )
    return {"status": "sealed", "dataset": dataset, "build": build_stats, "source_policy": "longbridge_only_no_yahoo", "read_only_research": True}


__all__ = [
    "STOCK_QUANT_VALIDATION_VERSION",
    "build_stock_quant_cache_dataset",
    "run_stock_quant_validation",
    "latest_stock_quant_validation",
    "stock_quant_validation_detail",
]
