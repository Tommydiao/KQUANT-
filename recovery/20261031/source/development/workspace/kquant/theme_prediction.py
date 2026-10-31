from __future__ import annotations

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
from .stock_store import connect


THEME_PREDICTION_VERSION = "theme_prediction_v1.0.0"
THEME_PREDICTION_DATASET_CONTRACT = "theme_prediction_dataset_v1.0.0"
THEME_PREDICTION_FEATURE_SCHEMA = "theme_prediction_features_v1.0.0"
THEME_PREDICTION_LABEL_SCHEMA = "theme_prediction_labels_v1.0.0"
CALIBRATION_VERSION = "probability_calibration_v1.0.0"
MIN_OOS_FOLDS_FOR_GATE = 3
BOOTSTRAP_SAMPLES = 200


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _finite(value: Any, *, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DatasetIntegrityError(f"{field} must be a finite number.") from exc
    if not math.isfinite(result):
        raise DatasetIntegrityError(f"{field} must be a finite number.")
    return result


def _normalise_label(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("label")
    if not isinstance(raw, dict):
        raise DatasetIntegrityError("Theme prediction items need a label object.")
    label = dict(raw)
    excess_return = _finite(label.get("excess_return"), field="label.excess_return")
    direction = int(label.get("direction", 1 if excess_return > 0 else 0))
    if direction not in (0, 1):
        raise DatasetIntegrityError("label.direction must be 0 or 1.")
    rank_percentile = _finite(label.get("rank_percentile", 0.5), field="label.rank_percentile")
    if not 0.0 <= rank_percentile <= 1.0:
        raise DatasetIntegrityError("label.rank_percentile must be in [0, 1].")
    quantile = int(label.get("quantile", min(4, max(0, math.floor(rank_percentile * 5)))))
    if quantile < 0 or quantile > 4:
        raise DatasetIntegrityError("label.quantile must be an integer from 0 to 4.")
    label.update({
        "target": float(direction),
        "direction": direction,
        "excess_return": excess_return,
        "rank_percentile": rank_percentile,
        "quantile": quantile,
    })
    return label


def normalise_theme_prediction_item(item: dict[str, Any]) -> dict[str, Any]:
    """Validate the theme item contract before it enters the generic sealed dataset."""

    theme_id = str(item.get("theme_id") or item.get("symbol") or "").strip()
    if not theme_id:
        raise DatasetIntegrityError("Theme prediction items need theme_id.")
    normalized = dict(item)
    normalized["theme_id"] = theme_id
    normalized["symbol"] = theme_id
    normalized["source_snapshot_id"] = str(item.get("source_snapshot_id") or "").strip()
    normalized["label"] = _normalise_label(item)
    if not normalized["source_snapshot_id"]:
        raise DatasetIntegrityError("Theme prediction items need source_snapshot_id.")
    if not isinstance(item.get("features"), dict) or not item["features"]:
        raise DatasetIntegrityError("Theme prediction items need non-empty features.")
    return normalized


def build_theme_prediction_dataset(
    db_path: Path,
    items: Iterable[dict[str, Any]],
    *,
    dataset_id: str | None = None,
    universe_registry_id: str = "",
    source_policy_version: str = "longbridge_pit_theme_v1",
    embargo_days: int = 5,
) -> dict[str, Any]:
    normalized = [normalise_theme_prediction_item(dict(item)) for item in items]
    return build_quant_dataset(
        db_path,
        normalized,
        dataset_id=dataset_id,
        universe_registry_id=universe_registry_id,
        source_policy_version=source_policy_version,
        embargo_days=embargo_days,
        contract_version=THEME_PREDICTION_DATASET_CONTRACT,
        feature_schema_version=THEME_PREDICTION_FEATURE_SCHEMA,
        label_schema_version=THEME_PREDICTION_LABEL_SCHEMA,
    )


def _clamp_probability(value: float) -> float:
    return max(1e-6, min(1 - 1e-6, float(value)))


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - left_mean) ** 2 for a in left) * sum((b - right_mean) ** 2 for b in right))
    return numerator / denominator if denominator else None


def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor + 1
        while end < len(order) and values[order[end]] == values[order[cursor]]:
            end += 1
        rank = (cursor + end - 1) / 2 + 1
        for index in order[cursor:end]:
            ranks[index] = rank
        cursor = end
    return ranks


def _rank_ic(predictions: list[float], outcomes: list[float]) -> float | None:
    return _pearson(_ranks(predictions), _ranks(outcomes))


def _auc(labels: list[int], predictions: list[float]) -> float | None:
    positives = [prediction for label, prediction in zip(labels, predictions) if label == 1]
    negatives = [prediction for label, prediction in zip(labels, predictions) if label == 0]
    if not positives or not negatives:
        return None
    wins = sum(1.0 if positive > negative else 0.5 if positive == negative else 0.0 for positive in positives for negative in negatives)
    return wins / (len(positives) * len(negatives))


def _ece(labels: list[int], predictions: list[float], bins: int = 10) -> float | None:
    if not labels:
        return None
    total = len(labels)
    calibration_error = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [position for position, prediction in enumerate(predictions) if lower <= prediction < upper or (index == bins - 1 and prediction == 1.0)]
        if members:
            actual = sum(labels[position] for position in members) / len(members)
            expected = sum(predictions[position] for position in members) / len(members)
            calibration_error += len(members) / total * abs(actual - expected)
    return calibration_error


def _bootstrap_mean_ci(values: list[float], seed: int) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    state = seed & 0xFFFFFFFF
    samples: list[float] = []
    for _ in range(BOOTSTRAP_SAMPLES):
        selected: list[float] = []
        for _ in values:
            state = (1664525 * state + 1013904223) & 0xFFFFFFFF
            selected.append(values[state % len(values)])
        samples.append(sum(selected) / len(selected))
    samples.sort()
    return samples[int(0.025 * (len(samples) - 1))], samples[int(0.975 * (len(samples) - 1))]


def prediction_metrics(rows: list[dict[str, Any]], predictions: list[float], *, seed: int) -> dict[str, Any]:
    if len(rows) != len(predictions):
        raise DatasetIntegrityError("Prediction count does not match dataset rows.")
    if not rows:
        return {
            "sample_count": 0,
            "auc": None,
            "brier": None,
            "ece": None,
            "rank_ic": None,
            "top_decile_excess": None,
            "mean_excess_return": None,
            "mean_absolute_error": None,
            "confidence_interval_mean_excess": [None, None],
        }
    labels = [int(row["label"].get("direction", row["label"].get("target", 0))) for row in rows]
    outcomes = [_finite(row["label"].get("excess_return"), field="label.excess_return") for row in rows]
    probability_ready = all(0.0 <= prediction <= 1.0 for prediction in predictions)
    probabilities = [_clamp_probability(prediction) for prediction in predictions]
    order = sorted(range(len(rows)), key=lambda index: (predictions[index], index), reverse=True)
    top_count = max(1, math.ceil(len(rows) * 0.10))
    top_excess = _mean([outcomes[index] for index in order[:top_count]])
    overall_excess = _mean(outcomes)
    lower, upper = _bootstrap_mean_ci(outcomes, seed)
    return {
        "sample_count": len(rows),
        "auc": round(_auc(labels, probabilities), 8) if probability_ready and _auc(labels, probabilities) is not None else None,
        "brier": round(sum((prediction - label) ** 2 for prediction, label in zip(probabilities, labels)) / len(rows), 8) if probability_ready else None,
        "ece": round(_ece(labels, probabilities), 8) if probability_ready and _ece(labels, probabilities) is not None else None,
        "rank_ic": round(_rank_ic(predictions, outcomes), 8) if _rank_ic(predictions, outcomes) is not None else None,
        "top_decile_excess": round(top_excess, 8) if top_excess is not None else None,
        "mean_excess_return": round(overall_excess, 8) if overall_excess is not None else None,
        "mean_absolute_error": round(sum(abs(prediction - outcome) for prediction, outcome in zip(predictions, outcomes)) / len(rows), 8),
        "positive_rate": round(sum(labels) / len(labels), 8),
        "mean_prediction": round(sum(predictions) / len(predictions), 8),
        "confidence_interval_mean_excess": [round(lower, 8) if lower is not None else None, round(upper, 8) if upper is not None else None],
        "probability_metrics_available": probability_ready,
    }


def _logit(value: float) -> float:
    probability = _clamp_probability(value)
    return math.log(probability / (1 - probability))


def _fit_platt(predictions: list[float], labels: list[int]) -> dict[str, Any]:
    if not predictions or len(predictions) != len(labels):
        raise DatasetIntegrityError("Platt calibration needs validation predictions and labels.")
    slope = 1.0
    intercept = 0.0
    inputs = [_logit(value) for value in predictions]
    for _ in range(250):
        slope_gradient = 0.0
        intercept_gradient = 0.0
        for value, label in zip(inputs, labels):
            probability = 1 / (1 + math.exp(-max(-30.0, min(30.0, slope * value + intercept))))
            error = probability - label
            slope_gradient += error * value
            intercept_gradient += error
        divisor = len(inputs)
        slope -= 0.05 * slope_gradient / divisor
        intercept -= 0.05 * intercept_gradient / divisor
    return {"method": "platt", "slope": round(slope, 10), "intercept": round(intercept, 10), "version": CALIBRATION_VERSION}


def _apply_platt(parameters: dict[str, Any], predictions: list[float]) -> list[float]:
    return [
        1 / (1 + math.exp(-max(-30.0, min(30.0, float(parameters["slope"]) * _logit(value) + float(parameters["intercept"])))))
        for value in predictions
    ]


def _fit_isotonic(predictions: list[float], labels: list[int]) -> dict[str, Any]:
    if not predictions or len(predictions) != len(labels):
        raise DatasetIntegrityError("Isotonic calibration needs validation predictions and labels.")
    blocks: list[dict[str, Any]] = []
    for prediction, label in sorted(zip(predictions, labels), key=lambda pair: pair[0]):
        blocks.append({"left": prediction, "right": prediction, "count": 1, "sum": float(label)})
        while len(blocks) >= 2:
            previous, current = blocks[-2], blocks[-1]
            if previous["sum"] / previous["count"] <= current["sum"] / current["count"]:
                break
            merged = {
                "left": previous["left"],
                "right": current["right"],
                "count": previous["count"] + current["count"],
                "sum": previous["sum"] + current["sum"],
            }
            blocks[-2:] = [merged]
    return {
        "method": "isotonic",
        "thresholds": [round(float(block["right"]), 10) for block in blocks],
        "values": [round(float(block["sum"]) / float(block["count"]), 10) for block in blocks],
        "version": CALIBRATION_VERSION,
    }


def _apply_isotonic(parameters: dict[str, Any], predictions: list[float]) -> list[float]:
    thresholds = [float(value) for value in parameters["thresholds"]]
    values = [float(value) for value in parameters["values"]]
    result: list[float] = []
    for prediction in predictions:
        index = next((position for position, threshold in enumerate(thresholds) if prediction <= threshold), len(thresholds) - 1)
        result.append(_clamp_probability(values[index]))
    return result


def _calibration_result(
    validation_rows: list[dict[str, Any]],
    test_rows: list[dict[str, Any]],
    validation_predictions: list[float],
    test_predictions: list[float],
    *,
    model_name: str,
    seed: int,
) -> list[dict[str, Any]]:
    labels = [int(row["label"].get("direction", row["label"].get("target", 0))) for row in validation_rows]
    results = []
    for method, fitter, applier in (("platt", _fit_platt, _apply_platt), ("isotonic", _fit_isotonic, _apply_isotonic)):
        parameters = fitter(validation_predictions, labels)
        calibrated_validation = applier(parameters, validation_predictions)
        calibrated_test = applier(parameters, test_predictions)
        validation_metrics = prediction_metrics(validation_rows, calibrated_validation, seed=seed)
        test_metrics = prediction_metrics(test_rows, calibrated_test, seed=seed + 1)
        ece = validation_metrics.get("ece")
        gate_status = "blocked_insufficient_oos_folds" if MIN_OOS_FOLDS_FOR_GATE > 1 else "candidate"
        if ece is not None and ece <= 0.05 and gate_status != "blocked_insufficient_oos_folds":
            gate_status = "pass"
        results.append({
            "model_name": model_name,
            "method": method,
            "parameters": parameters,
            "validation_metrics": validation_metrics,
            "test_metrics": test_metrics,
            "gate_status": gate_status,
        })
    return results


def _model_predictions(
    dataset: dict[str, Any],
    *,
    random_seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = dataset["items"]
    train_rows = [row for row in rows if row["split_name"] == "train"]
    validation_rows = [row for row in rows if row["split_name"] == "validation"]
    test_rows = [row for row in rows if row["split_name"] == "test"]
    feature_order = sorted({key for row in rows for key in row["features"]})
    logistic_artifact = _fit_logistic(train_rows, feature_order, random_seed)
    prevalence = sum(float(row["label"].get("direction", row["label"].get("target", 0))) for row in train_rows) / len(train_rows)
    candidates: list[dict[str, Any]] = [
        {"model_name": "theme_naive", "model_kind": "classification", "artifact": {"kind": "constant_probability", "probability": round(prevalence, 10)}},
        {"model_name": "capital_rotation_rule", "model_kind": "classification", "artifact": {"kind": "feature_passthrough", "feature_id": "capital_rotation_score"}},
        {"model_name": "theme_logistic", "model_kind": "classification", "artifact": logistic_artifact},
    ]
    if importlib.util.find_spec("lightgbm") is None:
        return candidates, [
            {"model_name": "lightgbm_classifier", "model_kind": "classification", "status": "not_installed", "reason": "Optional lightgbm dependency is not installed."},
            {"model_name": "lightgbm_regressor", "model_kind": "regression", "status": "not_installed", "reason": "Optional lightgbm dependency is not installed."},
            {"model_name": "lightgbm_quantile", "model_kind": "quantile", "status": "not_installed", "reason": "Optional lightgbm dependency is not installed."},
        ]
    import lightgbm as lgb  # type: ignore[import-not-found]

    matrix = [[float(row["features"].get(feature) or 0.0) for feature in feature_order] for row in train_rows]
    validation_matrix = [[float(row["features"].get(feature) or 0.0) for feature in feature_order] for row in validation_rows]
    test_matrix = [[float(row["features"].get(feature) or 0.0) for feature in feature_order] for row in test_rows]
    train_direction = [int(row["label"].get("direction", row["label"].get("target", 0))) for row in train_rows]
    train_excess = [float(row["label"]["excess_return"]) for row in train_rows]
    classifier = lgb.LGBMClassifier(objective="binary", n_estimators=80, learning_rate=0.05, max_depth=3, random_state=random_seed, verbosity=-1)
    classifier.fit(matrix, train_direction)
    candidates.append({
        "model_name": "lightgbm_classifier",
        "model_kind": "classification",
        "status": "available",
        "predictions": {
            "train": [float(value[1]) for value in classifier.predict_proba(matrix)],
            "validation": [float(value[1]) for value in classifier.predict_proba(validation_matrix)],
            "test": [float(value[1]) for value in classifier.predict_proba(test_matrix)],
        },
        "artifact": {"kind": "lightgbm_classifier", "feature_order": feature_order, "params": {"n_estimators": 80, "learning_rate": 0.05, "max_depth": 3, "seed": random_seed}},
    })
    regressor = lgb.LGBMRegressor(objective="regression", n_estimators=80, learning_rate=0.05, max_depth=3, random_state=random_seed, verbosity=-1)
    regressor.fit(matrix, train_excess)
    candidates.append({
        "model_name": "lightgbm_regressor",
        "model_kind": "regression",
        "status": "available",
        "predictions": {"train": [float(value) for value in regressor.predict(matrix)], "validation": [float(value) for value in regressor.predict(validation_matrix)], "test": [float(value) for value in regressor.predict(test_matrix)]},
        "artifact": {"kind": "lightgbm_regressor", "feature_order": feature_order, "params": {"n_estimators": 80, "learning_rate": 0.05, "max_depth": 3, "seed": random_seed}},
    })
    quantile = lgb.LGBMRegressor(objective="quantile", alpha=0.75, n_estimators=80, learning_rate=0.05, max_depth=3, random_state=random_seed, verbosity=-1)
    quantile.fit(matrix, train_excess)
    candidates.append({
        "model_name": "lightgbm_quantile",
        "model_kind": "quantile",
        "status": "available",
        "predictions": {"train": [float(value) for value in quantile.predict(matrix)], "validation": [float(value) for value in quantile.predict(validation_matrix)], "test": [float(value) for value in quantile.predict(test_matrix)]},
        "artifact": {"kind": "lightgbm_quantile", "feature_order": feature_order, "params": {"alpha": 0.75, "n_estimators": 80, "learning_rate": 0.05, "max_depth": 3, "seed": random_seed}},
    })
    return candidates, []


def _predict_for_artifact(artifact: dict[str, Any], rows: list[dict[str, Any]]) -> list[float]:
    return [float(_predict(artifact, row)) for row in rows]


def run_theme_prediction(db_path: Path, dataset_id: str, *, random_seed: int = 20260817) -> dict[str, Any]:
    dataset = read_quant_dataset(db_path, dataset_id)
    if dataset["contract_version"] != THEME_PREDICTION_DATASET_CONTRACT:
        raise DatasetIntegrityError("Theme prediction requires a versioned theme prediction dataset.")
    rows = dataset["items"]
    train_rows = [row for row in rows if row["split_name"] == "train"]
    validation_rows = [row for row in rows if row["split_name"] == "validation"]
    test_rows = [row for row in rows if row["split_name"] == "test"]
    candidates, unavailable = _model_predictions(dataset, random_seed=random_seed)
    model_reports: list[dict[str, Any]] = []
    calibration_reports: list[dict[str, Any]] = []
    for candidate in candidates:
        name = str(candidate["model_name"])
        kind = str(candidate["model_kind"])
        if candidate.get("status") == "not_installed":
            model_reports.append({"model_name": name, "model_kind": kind, "status": "not_installed", "reason": candidate["reason"]})
            continue
        artifact = dict(candidate["artifact"])
        predictions = candidate.get("predictions")
        if predictions is None:
            predictions = {
                "train": _predict_for_artifact(artifact, train_rows),
                "validation": _predict_for_artifact(artifact, validation_rows),
                "test": _predict_for_artifact(artifact, test_rows),
            }
        metrics_by_split = {
            split: prediction_metrics(split_rows, list(predictions[split]), seed=random_seed + offset)
            for offset, (split, split_rows) in enumerate((("train", train_rows), ("validation", validation_rows), ("test", test_rows)))
        }
        artifact_id = register_model_artifact(
            db_path,
            dataset_id=dataset_id,
            model_name=name,
            model_version=f"{name}_v1.0.0",
            feature_order=sorted({key for row in rows for key in row["features"]}),
            train_config={"selection_partitions": ["train", "validation"], "test_partition_used_for_selection": False, "prediction_version": THEME_PREDICTION_VERSION},
            random_seed=random_seed,
            artifact=artifact,
            metrics={split: {key: value for key, value in metrics.items() if isinstance(value, (int, float))} for split, metrics in metrics_by_split.items()},
        )
        model_reports.append({"model_name": name, "model_kind": kind, "status": "verified", "artifact_id": artifact_id["artifact_id"], "metrics": metrics_by_split})
        if kind == "classification":
            calibration_reports.extend(_calibration_result(validation_rows, test_rows, list(predictions["validation"]), list(predictions["test"]), model_name=name, seed=random_seed))
    summary_seed = {
        "prediction_version": THEME_PREDICTION_VERSION,
        "dataset_id": dataset_id,
        "dataset_hash": dataset["content_hash"],
        "random_seed": random_seed,
        "oos_fold_count": 1,
        "models": model_reports,
        "calibrations": calibration_reports,
    }
    content_hash = _hash(summary_seed)
    run_id = f"tpr_{content_hash[:20]}"
    gate_status = "blocked_insufficient_oos_folds"
    if len([report for report in model_reports if report.get("status") == "verified"]) == 0:
        gate_status = "blocked_no_verified_model"
    summary = {
        **summary_seed,
        "gate_status": gate_status,
        "display_probability": False,
        "calibration_gate": {
            "minimum_oos_folds": MIN_OOS_FOLDS_FOR_GATE,
            "observed_oos_folds": 1,
            "status": gate_status,
            "ece_target": 0.05,
        },
        "test_partition_used_for_selection": False,
        "optional_models": unavailable,
        "read_only_research": True,
    }
    created_at = _now()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO theme_prediction_runs(
              run_id, dataset_id, prediction_version, feature_schema_version,
              label_schema_version, oos_fold_count, status, gate_status,
              summary_json, content_hash, test_partition_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'materialized', ?, ?, ?, ?, ?)
            """,
            (run_id, dataset_id, THEME_PREDICTION_VERSION, dataset["feature_schema_version"], dataset["label_schema_version"], 1, gate_status, _canonical(summary), content_hash, dataset["test_partition_hash"], created_at),
        )
        for report in model_reports:
            if report.get("status") != "verified":
                continue
            for split_name, metrics in report["metrics"].items():
                for metric_name, metric_value in metrics.items():
                    numeric = float(metric_value) if isinstance(metric_value, (int, float)) else None
                    conn.execute(
                        "INSERT OR IGNORE INTO theme_prediction_metrics(run_id, model_name, model_kind, split_name, metric_name, metric_value, details_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (run_id, report["model_name"], report["model_kind"], split_name, metric_name, numeric, _canonical({"value": metric_value}), created_at),
                    )
        for calibration in calibration_reports:
            calibration_hash = _hash({"run_id": run_id, "model_name": calibration["model_name"], **calibration})
            conn.execute(
                "INSERT OR IGNORE INTO theme_prediction_calibrations(run_id, model_name, method, validation_metrics_json, test_metrics_json, parameters_json, gate_status, content_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, calibration["model_name"], calibration["method"], _canonical(calibration["validation_metrics"]), _canonical(calibration["test_metrics"]), _canonical(calibration["parameters"]), calibration["gate_status"], calibration_hash, created_at),
            )
        conn.commit()
    return theme_prediction_detail(db_path, run_id)


def theme_prediction_detail(db_path: Path, run_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        run = conn.execute("SELECT * FROM theme_prediction_runs WHERE run_id = ?", (run_id,)).fetchone()
        if run is None:
            raise ValueError(f"Unknown theme prediction run: {run_id}")
        metrics = [dict(row) for row in conn.execute("SELECT * FROM theme_prediction_metrics WHERE run_id = ? ORDER BY model_name, split_name, metric_name", (run_id,)).fetchall()]
        calibrations = [dict(row) for row in conn.execute("SELECT * FROM theme_prediction_calibrations WHERE run_id = ? ORDER BY model_name, method", (run_id,)).fetchall()]
    dataset = read_quant_dataset(db_path, str(run["dataset_id"]))
    if str(run["test_partition_hash"]) != dataset["test_partition_hash"]:
        raise DatasetIntegrityError("Theme prediction test partition hash does not match its dataset.")
    for row in metrics:
        row["details"] = json.loads(row.pop("details_json"))
    for row in calibrations:
        row["validation_metrics"] = json.loads(row.pop("validation_metrics_json"))
        row["test_metrics"] = json.loads(row.pop("test_metrics_json"))
        row["parameters"] = json.loads(row.pop("parameters_json"))
    summary = json.loads(run["summary_json"])
    return {
        "status": run["status"],
        "run_id": run["run_id"],
        "dataset_id": run["dataset_id"],
        "prediction_version": run["prediction_version"],
        "feature_schema_version": run["feature_schema_version"],
        "label_schema_version": run["label_schema_version"],
        "oos_fold_count": run["oos_fold_count"],
        "gate_status": run["gate_status"],
        "summary": summary,
        "metrics": metrics,
        "calibrations": calibrations,
        "content_hash": run["content_hash"],
        "test_partition_hash": run["test_partition_hash"],
        "dataset_integrity_status": dataset["integrity_status"],
        "read_only_research": True,
    }


def latest_theme_prediction(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT run_id FROM theme_prediction_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if row is None:
        return {"status": "not_materialized", "runs": [], "read_only_research": True}
    return theme_prediction_detail(db_path, str(row["run_id"]))
