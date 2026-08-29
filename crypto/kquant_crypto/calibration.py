from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from .evaluation_models import stable_hash


@dataclass(frozen=True)
class PredictionRecord:
    probability: float
    outcome: int
    fold: str


@dataclass(frozen=True)
class ProbabilityCalibrator:
    """A validation-fitted probability transform; never an EVAL authority."""

    method: str
    sample_count: int
    slope: float | None = None
    intercept: float | None = None
    thresholds: tuple[float, ...] = ()
    values: tuple[float, ...] = ()
    calibrator_hash: str = ""

    def predict(self, probabilities: Sequence[float]) -> list[float]:
        if self.method == "platt":
            if self.slope is None or self.intercept is None:
                return []
            values = np.asarray([min(1.0 - 1e-6, max(1e-6, float(item))) for item in probabilities])
            logits = np.log(values / (1.0 - values))
            calibrated = 1.0 / (1.0 + np.exp(-np.clip(self.slope * logits + self.intercept, -35.0, 35.0)))
            return [float(item) for item in calibrated]
        if self.method == "isotonic":
            if not self.thresholds or not self.values:
                return []
            return [
                float(np.interp(float(item), np.asarray(self.thresholds), np.asarray(self.values)))
                for item in probabilities
            ]
        raise ValueError(f"Unknown calibration method: {self.method}")

    def as_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "sample_count": self.sample_count,
            "slope": self.slope,
            "intercept": self.intercept,
            "thresholds": list(self.thresholds),
            "values": list(self.values),
            "calibrator_hash": self.calibrator_hash,
            "authority": "validation_only_advisory",
        }


def _validate(records: Sequence[PredictionRecord]) -> None:
    for record in records:
        if not 0.0 <= float(record.probability) <= 1.0:
            raise ValueError("probability must be between 0 and 1")
        if int(record.outcome) not in (0, 1):
            raise ValueError("outcome must be 0 or 1")


def reliability_bins(records: Sequence[PredictionRecord], *, bin_count: int = 10) -> list[dict[str, Any]]:
    _validate(records)
    bins = [{"lower": index / bin_count, "upper": (index + 1) / bin_count, "count": 0, "probability": None, "outcome_rate": None, "gap": None} for index in range(bin_count)]
    grouped: list[list[PredictionRecord]] = [[] for _ in range(bin_count)]
    for record in records:
        index = min(bin_count - 1, int(float(record.probability) * bin_count))
        grouped[index].append(record)
    for index, values in enumerate(grouped):
        if values:
            probability = sum(float(item.probability) for item in values) / len(values)
            outcome_rate = sum(int(item.outcome) for item in values) / len(values)
            bins[index].update({"count": len(values), "probability": probability, "outcome_rate": outcome_rate, "gap": abs(probability - outcome_rate)})
    return bins


def calibration_report(records: Sequence[PredictionRecord], *, bin_count: int = 10) -> dict[str, Any]:
    _validate(records)
    count = len(records)
    if not records:
        return {"sample_count": 0, "brier": None, "climatology_brier": None, "ece": None, "fold_count": 0, "reliability": [], "gate": "insufficient"}
    mean_outcome = sum(int(item.outcome) for item in records) / count
    brier = sum((float(item.probability) - int(item.outcome)) ** 2 for item in records) / count
    climatology_brier = sum((mean_outcome - int(item.outcome)) ** 2 for item in records) / count
    bins = reliability_bins(records, bin_count=bin_count)
    ece = sum((item["count"] / count) * item["gap"] for item in bins if item["count"])
    fold_count = len({item.fold for item in records})
    passed = fold_count >= 3 and brier < climatology_brier and ece <= 0.05
    return {
        "sample_count": count,
        "brier": brier,
        "climatology_brier": climatology_brier,
        "ece": ece,
        "fold_count": fold_count,
        "reliability": bins,
        "gate": "passed" if passed else ("limited" if count >= 30 else "insufficient"),
    }


def model_evidence_gate(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check the immutable metadata needed before a probability can matter."""

    reasons: list[str] = []
    if payload.get("model_integrity_ok") is False:
        reasons.append("model_integrity_failed")
    for actual, expected, reason in (
        ("model_hash", "expected_model_hash", "model_hash_mismatch"),
        ("feature_order_hash", "expected_feature_order_hash", "feature_order_mismatch"),
        ("test_partition_hash", "expected_test_partition_hash", "test_partition_hash_mismatch"),
    ):
        if payload.get(expected) is not None and payload.get(actual) != payload.get(expected):
            reasons.append(reason)
    if payload.get("test_partition_locked") is False or payload.get("dataset_hash_mismatch"):
        reasons.append("dataset_integrity_failed")
    if payload.get("model_probability") is not None and payload.get("calibration_gate_passed") is not True:
        reasons.append("calibration_gate_closed")
    return not reasons, reasons


def _calibration_inputs(records: Sequence[PredictionRecord], *, min_samples: int) -> tuple[np.ndarray, np.ndarray] | None:
    _validate(records)
    if len(records) < max(4, int(min_samples)) or len({int(item.outcome) for item in records}) < 2:
        return None
    probabilities = np.asarray([min(1.0 - 1e-6, max(1e-6, float(item.probability))) for item in records], dtype=float)
    outcomes = np.asarray([int(item.outcome) for item in records], dtype=float)
    return probabilities, outcomes


def fit_platt_calibrator(records: Sequence[PredictionRecord], *, min_samples: int = 20, iterations: int = 600) -> ProbabilityCalibrator | None:
    """Fit a one-dimensional logistic calibration on validation only."""

    inputs = _calibration_inputs(records, min_samples=min_samples)
    if inputs is None:
        return None
    probabilities, outcomes = inputs
    logits = np.log(probabilities / (1.0 - probabilities))
    slope = 1.0
    intercept = 0.0
    count = float(len(records))
    for _ in range(max(100, int(iterations))):
        fitted = 1.0 / (1.0 + np.exp(-np.clip(slope * logits + intercept, -35.0, 35.0)))
        residual = fitted - outcomes
        slope -= 0.05 * float(np.dot(residual, logits) / count)
        intercept -= 0.05 * float(residual.mean())
    payload = {"method": "platt", "sample_count": len(records), "slope": float(slope), "intercept": float(intercept), "iterations": max(100, int(iterations))}
    return ProbabilityCalibrator(
        method="platt",
        sample_count=len(records),
        slope=float(slope),
        intercept=float(intercept),
        calibrator_hash=stable_hash(payload),
    )


def fit_isotonic_calibrator(records: Sequence[PredictionRecord], *, min_samples: int = 20) -> ProbabilityCalibrator | None:
    """Fit pool-adjacent-violators calibration on validation only."""

    inputs = _calibration_inputs(records, min_samples=min_samples)
    if inputs is None:
        return None
    probabilities, outcomes = inputs
    order = np.argsort(probabilities, kind="mergesort")
    blocks: list[dict[str, float]] = []
    for index in order:
        blocks.append({"lower": float(probabilities[index]), "upper": float(probabilities[index]), "sum": float(outcomes[index]), "count": 1.0})
        while len(blocks) >= 2:
            previous, current = blocks[-2], blocks[-1]
            previous_value = previous["sum"] / previous["count"]
            current_value = current["sum"] / current["count"]
            if previous_value <= current_value:
                break
            merged = {
                "lower": previous["lower"],
                "upper": current["upper"],
                "sum": previous["sum"] + current["sum"],
                "count": previous["count"] + current["count"],
            }
            blocks[-2:] = [merged]
    thresholds = tuple(block["upper"] for block in blocks)
    values = tuple(block["sum"] / block["count"] for block in blocks)
    payload = {"method": "isotonic", "sample_count": len(records), "thresholds": thresholds, "values": values}
    return ProbabilityCalibrator(
        method="isotonic",
        sample_count=len(records),
        thresholds=thresholds,
        values=values,
        calibrator_hash=stable_hash(payload),
    )
