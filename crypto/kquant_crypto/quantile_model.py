from __future__ import annotations

"""Small NumPy-only quantile regression baseline.

It is intentionally non-authoritative.  The result is a research artifact
until an independent OOS and calibration gate passes.
"""

from dataclasses import dataclass
from math import isfinite
from typing import Any, Sequence

import numpy as np

from .evaluation_models import stable_hash


def _matrix(samples: Sequence[Any], feature_order: Sequence[str]) -> np.ndarray:
    return np.asarray([[float(sample.features[name]) for name in feature_order] for sample in samples], dtype=float)


@dataclass(frozen=True)
class QuantileRegressionBaseline:
    feature_order: tuple[str, ...]
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    quantile: float
    model_hash: str

    def predict(self, samples: Sequence[Any]) -> list[float]:
        if not samples:
            return []
        matrix = _matrix(samples, self.feature_order)
        normalized = (matrix - np.asarray(self.mean)) / np.asarray(self.scale)
        return [float(value) for value in normalized @ np.asarray(self.coefficients) + self.intercept]


def fit_quantile_regression(
    samples: Sequence[Any],
    *,
    feature_order: Sequence[str],
    quantile: float = 0.5,
    iterations: int = 900,
    learning_rate: float = 0.03,
    l2: float = 0.01,
) -> QuantileRegressionBaseline | None:
    if len(samples) < 10 or not 0.0 < float(quantile) < 1.0:
        return None
    order = tuple(str(name) for name in feature_order)
    matrix = _matrix(samples, order)
    labels = np.asarray([float(sample.realized_r) for sample in samples], dtype=float)
    if not np.isfinite(matrix).all() or not np.isfinite(labels).all():
        return None
    mean = matrix.mean(axis=0)
    scale = np.where(matrix.std(axis=0) < 1e-12, 1.0, matrix.std(axis=0))
    normalized = (matrix - mean) / scale
    coefficients = np.zeros(len(order), dtype=float)
    intercept = float(np.quantile(labels, quantile))
    count = float(len(samples))
    q = float(quantile)
    for _ in range(max(100, int(iterations))):
        residual = labels - (normalized @ coefficients + intercept)
        gradient = np.where(residual >= 0.0, -q, 1.0 - q)
        coefficients -= float(learning_rate) * (normalized.T @ gradient / count + float(l2) * coefficients)
        intercept -= float(learning_rate) * float(gradient.mean())
    payload = {
        "feature_order": list(order),
        "mean": [float(value) for value in mean],
        "scale": [float(value) for value in scale],
        "coefficients": [float(value) for value in coefficients],
        "intercept": float(intercept),
        "quantile": q,
        "iterations": max(100, int(iterations)),
        "learning_rate": float(learning_rate),
        "l2": float(l2),
    }
    return QuantileRegressionBaseline(
        feature_order=order,
        mean=tuple(float(value) for value in mean),
        scale=tuple(float(value) for value in scale),
        coefficients=tuple(float(value) for value in coefficients),
        intercept=float(intercept),
        quantile=q,
        model_hash=stable_hash(payload),
    )


def quantile_partition_metrics(samples: Sequence[Any], predictions: Sequence[float], quantile: float) -> dict[str, Any]:
    if samples and not predictions:
        return {
            "sample_count": 0,
            "eligible_sample_count": len(samples),
            "coverage": None,
            "target_quantile": float(quantile),
            "mean_prediction": None,
            "mean_realized_r": None,
            "mae": None,
        }
    if len(samples) != len(predictions):
        raise ValueError("prediction count does not match sample count")
    if not samples:
        return {"sample_count": 0, "coverage": None, "mean_prediction": None, "mean_realized_r": None, "mae": None}
    residuals = [float(sample.realized_r) - float(prediction) for sample, prediction in zip(samples, predictions)]
    return {
        "sample_count": len(samples),
        "coverage": sum(residual <= 0.0 for residual in residuals) / len(residuals),
        "target_quantile": float(quantile),
        "mean_prediction": sum(float(value) for value in predictions) / len(predictions),
        "mean_realized_r": sum(float(sample.realized_r) for sample in samples) / len(samples),
        "mae": sum(abs(residual) for residual in residuals) / len(residuals),
    }


__all__ = ["QuantileRegressionBaseline", "fit_quantile_regression", "quantile_partition_metrics"]
