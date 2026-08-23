from __future__ import annotations

"""Leakage-aware model baselines for the crypto validation evidence chain.

The module deliberately produces metadata and metrics only.  It does not
register a model as executable, change an EVAL decision, or make a signal
eligible for an alert.  Samples are conditional on a deterministic signal
already having been generated, so the resulting probability is not a
population-wide probability of a coin starting.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

import numpy as np

from .backtest import TradeOutcome
from .calibration import (
    PredictionRecord,
    calibration_report,
    fit_isotonic_calibrator,
    fit_platt_calibrator,
)
from .evaluation_models import stable_hash


MODEL_BENCHMARK_VERSION = "crypto_model_benchmark_v1.0.0"


@dataclass(frozen=True)
class BenchmarkSample:
    signal_time: str
    symbol: str | None
    partition: str
    label: int
    realized_r: float
    setup_score: float
    feature_values: tuple[tuple[str, float], ...]

    @property
    def features(self) -> dict[str, float]:
        return dict(self.feature_values)


@dataclass(frozen=True)
class LogisticBaseline:
    feature_order: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    model_hash: str

    def predict(self, samples: Sequence[BenchmarkSample]) -> list[float]:
        if not samples:
            return []
        matrix = _matrix(samples, self.feature_order)
        normalized = (matrix - np.asarray(self.mean)) / np.asarray(self.scale)
        logits = normalized @ np.asarray(self.coefficients) + float(self.intercept)
        return [float(value) for value in _sigmoid(logits)]


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _finite(value: object) -> bool:
    try:
        return isfinite(float(value))
    except (TypeError, ValueError):
        return False


def build_benchmark_samples(
    partition_outcomes: Mapping[str, Sequence[TradeOutcome]],
    *,
    feature_order: Sequence[str],
) -> tuple[BenchmarkSample, ...]:
    """Build complete, point-in-time feature rows from persisted outcomes.

    Rows with an absent factor are excluded and counted by the caller through
    the partition input/output counts.  Imputation is intentionally not done
    here because a future implementation must fit any imputer on train only.
    """

    order = tuple(str(item) for item in feature_order)
    if not order:
        raise ValueError("feature_order must not be empty")
    samples: list[BenchmarkSample] = []
    for partition, outcomes in partition_outcomes.items():
        for outcome in outcomes:
            values = outcome.factor_map
            if any(not _finite(values.get(name)) for name in order):
                continue
            samples.append(BenchmarkSample(
                signal_time=outcome.signal_time,
                symbol=outcome.symbol,
                partition=str(partition),
                label=1 if outcome.realized_r > 0 else 0,
                realized_r=float(outcome.realized_r),
                setup_score=float(outcome.setup_score),
                feature_values=tuple((name, float(values[name])) for name in order),
            ))
    return tuple(samples)


def _matrix(samples: Sequence[BenchmarkSample], feature_order: Sequence[str]) -> np.ndarray:
    return np.asarray(
        [[sample.features[name] for name in feature_order] for sample in samples],
        dtype=float,
    )


def fit_logistic_baseline(
    samples: Sequence[BenchmarkSample],
    *,
    feature_order: Sequence[str],
    iterations: int = 600,
    learning_rate: float = 0.08,
    l2: float = 0.01,
) -> LogisticBaseline | None:
    """Fit a deterministic NumPy-only logistic baseline on train rows."""

    if len(samples) < 4 or len({sample.label for sample in samples}) < 2:
        return None
    order = tuple(feature_order)
    matrix = _matrix(samples, order)
    labels = np.asarray([sample.label for sample in samples], dtype=float)
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale = np.where(scale < 1e-12, 1.0, scale)
    normalized = (matrix - mean) / scale
    coefficients = np.zeros(len(order), dtype=float)
    intercept = 0.0
    count = float(len(samples))
    for _ in range(max(100, int(iterations))):
        probabilities = _sigmoid(normalized @ coefficients + intercept)
        residual = probabilities - labels
        coefficients -= float(learning_rate) * (normalized.T @ residual / count + float(l2) * coefficients)
        intercept -= float(learning_rate) * float(residual.mean())
    payload = {
        "feature_order": list(order),
        "mean": [float(value) for value in mean],
        "scale": [float(value) for value in scale],
        "coefficients": [float(value) for value in coefficients],
        "intercept": float(intercept),
        "iterations": max(100, int(iterations)),
        "learning_rate": float(learning_rate),
        "l2": float(l2),
    }
    return LogisticBaseline(
        feature_order=order,
        mean=tuple(float(value) for value in mean),
        scale=tuple(float(value) for value in scale),
        coefficients=tuple(float(value) for value in coefficients),
        intercept=float(intercept),
        model_hash=stable_hash(payload),
    )


def _auc(labels: Sequence[int], probabilities: Sequence[float]) -> float | None:
    positives = sum(int(value) for value in labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    ordered = sorted(zip(probabilities, labels), key=lambda item: item[0])
    rank_sum = 0.0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        average_rank = (index + 1 + end) / 2.0
        rank_sum += average_rank * sum(label for _, label in ordered[index:end])
        index = end
    return (rank_sum - positives * (positives + 1) / 2.0) / (positives * negatives)


def _partition_metrics(samples: Sequence[BenchmarkSample], probabilities: Sequence[float]) -> dict[str, Any]:
    labels = [sample.label for sample in samples]
    if samples and not probabilities:
        return {
            "status": "not_evaluated",
            "sample_count": 0,
            "eligible_sample_count": len(samples),
            "positive_rate": None,
            "brier": None,
            "auc": None,
            "mean_realized_r": None,
            "calibration": calibration_report([]),
        }
    if len(labels) != len(probabilities):
        raise ValueError("prediction count does not match sample count")
    if not samples:
        return {
            "sample_count": 0,
            "positive_rate": None,
            "brier": None,
            "auc": None,
            "mean_realized_r": None,
            "calibration": calibration_report([]),
        }
    brier = sum((float(probability) - label) ** 2 for probability, label in zip(probabilities, labels)) / len(labels)
    return {
        "sample_count": len(samples),
        "positive_rate": sum(labels) / len(labels),
        "brier": brier,
        "auc": _auc(labels, probabilities),
        "mean_realized_r": sum(sample.realized_r for sample in samples) / len(samples),
        "calibration": calibration_report([
            PredictionRecord(float(probability), int(label), sample.partition)
            for sample, probability, label in zip(samples, probabilities, labels)
        ]),
    }


def _partition_samples(samples: Sequence[BenchmarkSample], name: str) -> tuple[BenchmarkSample, ...]:
    return tuple(sample for sample in samples if sample.partition == name)


def _model_report(
    model_type: str,
    status: str,
    samples_by_partition: Mapping[str, Sequence[BenchmarkSample]],
    predictions_by_partition: Mapping[str, Sequence[float]],
    *,
    notes: Sequence[str] = (),
    model_hash: str | None = None,
) -> dict[str, Any]:
    return {
        "model_type": model_type,
        "status": status,
        "model_hash": model_hash,
        "calibration_gate": "closed",
        "notes": list(notes),
        "partitions": {
            name: _partition_metrics(samples_by_partition.get(name, ()), predictions_by_partition.get(name, ()))
            for name in ("train", "validation", "test")
        },
    }


def run_model_benchmark(
    partition_outcomes: Mapping[str, Sequence[TradeOutcome]],
    *,
    feature_order: Sequence[str],
    dataset_hash: str = "",
    strategy_version: str = "",
) -> dict[str, Any]:
    """Compare non-authoritative baselines without selecting a production model."""

    samples = build_benchmark_samples(partition_outcomes, feature_order=feature_order)
    by_partition = {name: _partition_samples(samples, name) for name in ("train", "validation", "test")}
    train = by_partition["train"]
    train_prior = sum(sample.label for sample in train) / len(train) if train else None
    reports: list[dict[str, Any]] = []

    if train_prior is None:
        reports.append(_model_report(
            "naive_train_rate",
            "insufficient",
            by_partition,
            {name: [] for name in by_partition},
            notes=("train partition has no complete factor rows",),
        ))
    else:
        reports.append(_model_report(
            "naive_train_rate",
            "baseline_only",
            by_partition,
            {name: [float(train_prior)] * len(values) for name, values in by_partition.items()},
            notes=("probability is the train positive rate; no parameters were selected from validation or test",),
        ))

    reports.append(_model_report(
        "rules_score_uncalibrated",
        "baseline_only",
        by_partition,
        {name: [min(0.99, max(0.01, sample.setup_score / 100.0)) for sample in values] for name, values in by_partition.items()},
        notes=("setup_score is a deterministic score, not a calibrated probability",),
    ))

    logistic = fit_logistic_baseline(train, feature_order=feature_order)
    if logistic is None:
        reports.append(_model_report(
            "logistic_numpy",
            "insufficient",
            by_partition,
            {name: [] for name in by_partition},
            notes=("train needs at least four complete rows and both outcome classes",),
        ))
    else:
        logistic_report = _model_report(
            "logistic_numpy",
            "available_non_authoritative",
            by_partition,
            {name: logistic.predict(values) for name, values in by_partition.items()},
            notes=("fit on train only; no calibration or model selection is applied",),
            model_hash=logistic.model_hash,
        )
        raw_validation = logistic.predict(by_partition["validation"])
        validation_records = [
            PredictionRecord(probability, sample.label, "validation")
            for sample, probability in zip(by_partition["validation"], raw_validation)
        ]
        raw_test = logistic.predict(by_partition["test"])
        calibration_rows: dict[str, Any] = {}
        for method, calibrator in (
            ("platt", fit_platt_calibrator(validation_records)),
            ("isotonic", fit_isotonic_calibrator(validation_records)),
        ):
            if calibrator is None:
                calibration_rows[method] = {
                    "status": "insufficient_validation_samples",
                    "fit_partition": "validation",
                    "minimum_samples": 20,
                    "test_is_locked": True,
                }
                continue
            calibrated_test = calibrator.predict(raw_test)
            calibration_rows[method] = {
                "status": "available_non_authoritative",
                "fit_partition": "validation",
                "test_is_locked": True,
                "calibrator": calibrator.as_dict(),
                "test": _partition_metrics(by_partition["test"], calibrated_test),
                "eval_integration": "disabled",
            }
        logistic_report["calibration"] = calibration_rows
        reports.append(logistic_report)

    try:
        import lightgbm  # type: ignore  # noqa: F401
    except ImportError:
        lightgbm_status = "optional_dependency_missing"
        lightgbm_note = "LightGBM is optional and is not installed in this environment."
    else:
        lightgbm_status = "deferred_backend"
        lightgbm_note = "LightGBM backend is present but deliberately deferred until the baseline Gate is reviewed."
    reports.append(_model_report(
        "lightgbm",
        lightgbm_status,
        by_partition,
        {name: [] for name in by_partition},
        notes=(lightgbm_note, "no model may influence EVAL until an OOS and calibration Gate passes"),
    ))
    reports.append(_model_report(
        "quantile",
        "not_implemented",
        by_partition,
        {name: [] for name in by_partition},
        notes=("quantile return and downside models remain a later validation phase",),
    ))

    return {
        "benchmark_version": MODEL_BENCHMARK_VERSION,
        "dataset_hash": dataset_hash,
        "strategy_version": strategy_version,
        "feature_order": list(feature_order),
        "feature_order_hash": stable_hash(list(feature_order)),
        "label": "realized_r > 0 conditional on a deterministic signal",
        "selection_partition": "none",
        "test_is_locked": True,
        "test_results_used_for_selection": False,
        "sample_counts": {
            name: {
                "complete_factor_rows": len(values),
                "raw_trade_rows": len(partition_outcomes.get(name, ())),
            }
            for name, values in by_partition.items()
        },
        "models": reports,
        "evidence_status": "insufficient" if len(by_partition["test"]) < 30 else "limited" if len(by_partition["test"]) < 100 else "robust",
        "eval_integration": "disabled_until_oos_calibration_and_model_registry_gate",
    }
