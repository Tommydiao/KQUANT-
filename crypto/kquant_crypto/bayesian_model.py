from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping

from .evaluation_models import stable_hash


BAYESIAN_MODEL_VERSION = "crypto_bayesian_v1.0.0"
BAYESIAN_STATES = ("BULL", "ACCUMULATION", "DISTRIBUTION", "BEAR_STRESS")
VALID_TRUST_STATUS = frozenset({"live", "closed", "complete", "verified"})


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


@dataclass(frozen=True)
class PointInTimeFeatureSnapshot:
    snapshot_id: str
    asset_id: str
    symbol: str
    signal_time: str
    available_at: str
    source_status: str
    features: dict[str, float]
    source_snapshot_ids: tuple[str, ...] = ()
    missing_features: tuple[str, ...] = ()
    content_hash: str = ""

    @classmethod
    def create(
        cls,
        *,
        asset_id: str,
        symbol: str,
        signal_time: str,
        available_at: str,
        source_status: str,
        features: Mapping[str, object],
        source_snapshot_ids: tuple[str, ...] = (),
        required_features: tuple[str, ...] = (),
    ) -> "PointInTimeFeatureSnapshot":
        signal = _parse_time(signal_time)
        available = _parse_time(available_at)
        if available > signal:
            raise ValueError("available_at must not be after signal_time")
        normalized = {str(key): number for key, raw in features.items() if (number := _finite(raw)) is not None}
        missing = tuple(sorted(set(required_features) - set(normalized)))
        payload = {
            "asset_id": asset_id,
            "symbol": symbol,
            "signal_time": signal.isoformat(),
            "available_at": available.isoformat(),
            "source_status": str(source_status).lower(),
            "features": normalized,
            "source_snapshot_ids": list(source_snapshot_ids),
            "missing_features": list(missing),
        }
        content_hash = stable_hash(payload)
        snapshot_id = f"bayes_features_{content_hash[:20]}"
        return cls(
            snapshot_id=snapshot_id,
            asset_id=asset_id,
            symbol=symbol,
            signal_time=signal.isoformat(),
            available_at=available.isoformat(),
            source_status=str(source_status).lower(),
            features=normalized,
            source_snapshot_ids=tuple(source_snapshot_ids),
            missing_features=missing,
            content_hash=content_hash,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "signal_time": self.signal_time,
            "available_at": self.available_at,
            "source_status": self.source_status,
            "features": dict(self.features),
            "source_snapshot_ids": list(self.source_snapshot_ids),
            "missing_features": list(self.missing_features),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True)
class BayesianPosterior:
    snapshot_id: str
    asset_id: str
    symbol: str
    model_version: str
    state_probabilities: dict[str, float]
    most_likely_state: str
    target_before_stop_probability: float | None
    positive_return_probability: float | None
    drawdown_probability: float | None
    data_confidence: float
    evidence_status: str
    feature_order: tuple[str, ...]
    source_snapshot_ids: tuple[str, ...]
    training_window_start: str | None
    training_window_end: str | None
    training_dataset_hash: str
    random_seed: int | None
    content_hash: str
    evidence: tuple[dict[str, Any], ...] = ()
    unsupported_features: tuple[str, ...] = ()

    def to_mapping(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "model_version": self.model_version,
            "state_probabilities": self.state_probabilities,
            "most_likely_state": self.most_likely_state,
            "target_before_stop_probability": self.target_before_stop_probability,
            "positive_return_probability": self.positive_return_probability,
            "drawdown_probability": self.drawdown_probability,
            "data_confidence": self.data_confidence,
            "evidence_status": self.evidence_status,
            "feature_order": list(self.feature_order),
            "feature_order_hash": stable_hash(list(self.feature_order)),
            "source_snapshot_ids": list(self.source_snapshot_ids),
            "training_window_start": self.training_window_start,
            "training_window_end": self.training_window_end,
            "training_dataset_hash": self.training_dataset_hash,
            "random_seed": self.random_seed,
            "content_hash": self.content_hash,
            "evidence": [dict(item) for item in self.evidence],
            "unsupported_features": list(self.unsupported_features),
        }


# Fixed likelihood parameters are deliberately versioned. They are a
# transparent baseline, not a claim that a production probability has been
# trained or calibrated.
DEFAULT_PRIORS = {"BULL": 0.25, "ACCUMULATION": 0.30, "DISTRIBUTION": 0.25, "BEAR_STRESS": 0.20}
FEATURE_DISTRIBUTIONS: dict[str, dict[str, tuple[float, float]]] = {
    "trend_score": {"BULL": (0.75, 0.35), "ACCUMULATION": (0.35, 0.35), "DISTRIBUTION": (-0.25, 0.40), "BEAR_STRESS": (-0.70, 0.35)},
    "relative_strength": {"BULL": (0.65, 0.40), "ACCUMULATION": (0.20, 0.45), "DISTRIBUTION": (-0.20, 0.45), "BEAR_STRESS": (-0.65, 0.40)},
    "momentum": {"BULL": (0.55, 0.45), "ACCUMULATION": (0.10, 0.45), "DISTRIBUTION": (-0.15, 0.50), "BEAR_STRESS": (-0.55, 0.45)},
    "volume_pressure": {"BULL": (0.50, 0.45), "ACCUMULATION": (0.25, 0.50), "DISTRIBUTION": (-0.10, 0.50), "BEAR_STRESS": (-0.45, 0.45)},
    "funding_stress": {"BULL": (0.05, 0.55), "ACCUMULATION": (0.00, 0.55), "DISTRIBUTION": (0.25, 0.55), "BEAR_STRESS": (0.55, 0.50)},
    "drawdown_risk": {"BULL": (-0.35, 0.40), "ACCUMULATION": (-0.10, 0.45), "DISTRIBUTION": (0.30, 0.45), "BEAR_STRESS": (0.70, 0.40)},
    "gap_risk": {"BULL": (-0.30, 0.45), "ACCUMULATION": (-0.10, 0.50), "DISTRIBUTION": (0.35, 0.45), "BEAR_STRESS": (0.70, 0.40)},
    "volume_decay": {"BULL": (-0.35, 0.40), "ACCUMULATION": (-0.05, 0.45), "DISTRIBUTION": (0.40, 0.45), "BEAR_STRESS": (0.65, 0.40)},
    "abnormal_volatility": {"BULL": (-0.20, 0.50), "ACCUMULATION": (-0.15, 0.45), "DISTRIBUTION": (0.35, 0.50), "BEAR_STRESS": (0.70, 0.45)},
    "oi_change": {"BULL": (0.45, 0.50), "ACCUMULATION": (0.15, 0.45), "DISTRIBUTION": (-0.10, 0.50), "BEAR_STRESS": (-0.55, 0.45)},
    "basis_signal": {"BULL": (0.25, 0.50), "ACCUMULATION": (0.05, 0.45), "DISTRIBUTION": (0.20, 0.55), "BEAR_STRESS": (-0.30, 0.55)},
    "deleveraging_risk": {"BULL": (-0.45, 0.40), "ACCUMULATION": (-0.15, 0.45), "DISTRIBUTION": (0.35, 0.45), "BEAR_STRESS": (0.75, 0.35)},
}


def _log_pdf(value: float, mean: float, sigma: float) -> float:
    return -0.5 * ((value - mean) / sigma) ** 2 - math.log(sigma)


def _softmax(values: Mapping[str, float]) -> dict[str, float]:
    maximum = max(values.values())
    exponents = {key: math.exp(value - maximum) for key, value in values.items()}
    total = sum(exponents.values())
    return {key: value / total for key, value in exponents.items()}


def infer_bayesian_posterior(
    snapshot: PointInTimeFeatureSnapshot,
    *,
    priors: Mapping[str, float] | None = None,
    training_window_start: str | None = None,
    training_window_end: str | None = None,
    training_dataset_hash: str = "",
    random_seed: int | None = None,
) -> BayesianPosterior:
    """Compute a fixed, point-in-time Bayesian state posterior.

    The current model uses versioned fixed likelihoods rather than fitting a
    production model. Optional training metadata is nevertheless validated
    and hashed so later fitted variants cannot silently bind future data.
    """

    signal_time = _parse_time(snapshot.signal_time)
    window_start = _parse_time(training_window_start) if training_window_start else None
    window_end = _parse_time(training_window_end) if training_window_end else None
    if window_start and window_end and window_start > window_end:
        raise ValueError("training_window_start must not be after training_window_end")
    if signal_time and ((window_start and window_start > signal_time) or (window_end and window_end > signal_time)):
        raise ValueError("training window must not extend after signal_time")
    normalized_seed = int(random_seed) if random_seed is not None else None

    prior_values = dict(priors or DEFAULT_PRIORS)
    if set(prior_values) != set(BAYESIAN_STATES) or any(value <= 0 for value in prior_values.values()):
        raise ValueError("priors must contain positive values for all Bayesian states")
    log_posteriors = {state: math.log(float(prior_values[state])) for state in BAYESIAN_STATES}
    evidence: list[dict[str, Any]] = []
    for feature_name in sorted(snapshot.features):
        distributions = FEATURE_DISTRIBUTIONS.get(feature_name)
        if distributions is None:
            continue
        value = snapshot.features[feature_name]
        for state in BAYESIAN_STATES:
            log_posteriors[state] += _log_pdf(value, *distributions[state])
        evidence.append({
            "feature_id": feature_name,
            "value": value,
            "source": "pit_feature_snapshot",
            "distribution": {
                state: {"mean": parameters[0], "sigma": parameters[1]}
                for state, parameters in distributions.items()
            },
        })
    unsupported_features = tuple(sorted(set(snapshot.features) - set(FEATURE_DISTRIBUTIONS)))
    probabilities = _softmax(log_posteriors)
    state = max(probabilities, key=probabilities.get)
    target_probability = (
        probabilities["BULL"] * 0.72
        + probabilities["ACCUMULATION"] * 0.58
        + probabilities["DISTRIBUTION"] * 0.35
        + probabilities["BEAR_STRESS"] * 0.18
    )
    positive_probability = (
        probabilities["BULL"] * 0.78
        + probabilities["ACCUMULATION"] * 0.60
        + probabilities["DISTRIBUTION"] * 0.40
        + probabilities["BEAR_STRESS"] * 0.22
    )
    drawdown_probability = (
        probabilities["BULL"] * 0.16
        + probabilities["ACCUMULATION"] * 0.28
        + probabilities["DISTRIBUTION"] * 0.52
        + probabilities["BEAR_STRESS"] * 0.82
    )
    feature_count = len(snapshot.features)
    known_count = len(set(snapshot.features) & set(FEATURE_DISTRIBUTIONS))
    confidence = min(1.0, known_count / 4.0)
    if snapshot.source_status not in VALID_TRUST_STATUS:
        confidence *= 0.35
    if snapshot.missing_features:
        confidence *= max(0.0, 1.0 - min(0.75, 0.12 * len(snapshot.missing_features)))
    if feature_count == 0:
        confidence = 0.0
    evidence_status = "complete" if (
        confidence >= 0.75
        and snapshot.source_status in VALID_TRUST_STATUS
        and not snapshot.missing_features
        and not unsupported_features
    ) else "data_caution"
    payload = {
        "model_version": BAYESIAN_MODEL_VERSION,
        "snapshot": snapshot.to_mapping(),
        "state_probabilities": probabilities,
        "target_before_stop_probability": target_probability,
        "positive_return_probability": positive_probability,
        "drawdown_probability": drawdown_probability,
        "data_confidence": confidence,
        "feature_order": sorted(snapshot.features),
        "training_window_start": window_start.isoformat() if window_start else None,
        "training_window_end": window_end.isoformat() if window_end else None,
        "training_dataset_hash": str(training_dataset_hash or ""),
        "random_seed": normalized_seed,
        "evidence": evidence,
        "unsupported_features": list(unsupported_features),
    }
    return BayesianPosterior(
        snapshot_id=snapshot.snapshot_id,
        asset_id=snapshot.asset_id,
        symbol=snapshot.symbol,
        model_version=BAYESIAN_MODEL_VERSION,
        state_probabilities=probabilities,
        most_likely_state=state,
        target_before_stop_probability=target_probability if evidence_status == "complete" else None,
        positive_return_probability=positive_probability if evidence_status == "complete" else None,
        drawdown_probability=drawdown_probability if evidence_status == "complete" else None,
        data_confidence=confidence,
        evidence_status=evidence_status,
        feature_order=tuple(sorted(snapshot.features)),
        source_snapshot_ids=snapshot.source_snapshot_ids,
        training_window_start=window_start.isoformat() if window_start else None,
        training_window_end=window_end.isoformat() if window_end else None,
        training_dataset_hash=str(training_dataset_hash or ""),
        random_seed=normalized_seed,
        content_hash=stable_hash(payload),
        evidence=tuple(evidence),
        unsupported_features=unsupported_features,
    )


__all__ = [
    "BAYESIAN_MODEL_VERSION",
    "BAYESIAN_STATES",
    "PointInTimeFeatureSnapshot",
    "BayesianPosterior",
    "infer_bayesian_posterior",
]
