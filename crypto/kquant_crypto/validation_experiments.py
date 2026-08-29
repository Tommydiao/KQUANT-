from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from .backtest import BacktestConfig
from .evaluation_models import stable_hash
from .factor_registry import FactorRegistry
from .validation import ValidationConfig, ValidationSeries, run_walk_forward_validation


@dataclass(frozen=True)
class ValidationCandidate:
    candidate_id: str
    backtest_overrides: Mapping[str, Any]


@dataclass(frozen=True)
class ValidationExperiment:
    experiment_id: str
    selection_partition: str
    selected_candidate_id: str | None
    candidates: tuple[dict[str, Any], ...]
    test_is_locked: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "selection_partition": self.selection_partition,
            "selected_candidate_id": self.selected_candidate_id,
            "candidates": [dict(item) for item in self.candidates],
            "test_is_locked": self.test_is_locked,
            "test_results_used_for_selection": False,
        }


def run_validation_experiment(
    series: Sequence[ValidationSeries],
    *,
    registry: FactorRegistry,
    weights: dict[str, float],
    candidates: Sequence[ValidationCandidate],
    base_config: ValidationConfig,
) -> ValidationExperiment:
    """Select a backtest configuration from validation evidence only.

    The underlying validation runner still computes locked test/OOS evidence
    for each candidate so the existing report contract remains intact, but
    this function deliberately discards those partitions before ranking. A
    caller must launch a separate frozen run after selection to inspect test
    performance.
    """

    if not candidates:
        raise ValueError("At least one validation candidate is required")
    candidate_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        overrides = dict(candidate.backtest_overrides)
        unknown = sorted(set(overrides) - set(BacktestConfig.__dataclass_fields__))
        if unknown:
            raise ValueError(f"Unknown backtest override fields: {', '.join(unknown)}")
        candidate_backtest = replace(base_config.backtest, **overrides)
        candidate_config = replace(base_config, backtest=candidate_backtest)
        result = run_walk_forward_validation(
            series,
            registry=registry,
            weights=weights,
            config=candidate_config,
        )
        validation = result["report"]["partitions"]["validation"]["summary"]
        candidate_rows.append({
            "candidate_id": candidate.candidate_id,
            "backtest_overrides": overrides,
            "sample_count": validation["sample_count"],
            "evidence_status": validation["evidence_status"],
            "average_r": validation["average_r"],
            "profit_factor": validation["profit_factor"],
            "max_drawdown_r": validation["max_drawdown_r"],
            "validation_only": True,
        })

    def rank(row: dict[str, Any]) -> tuple[float, float, int, float]:
        average_r = row["average_r"] if row["average_r"] is not None else float("-inf")
        profit_factor = row["profit_factor"] if row["profit_factor"] is not None else float("-inf")
        return (
            float(average_r),
            float(profit_factor),
            int(row["sample_count"]),
            -float(row["max_drawdown_r"] or 0.0),
        )

    ordered = sorted(candidate_rows, key=rank, reverse=True)
    selected = ordered[0]["candidate_id"] if ordered else None
    experiment_payload = {
        'strategy_version': base_config.strategy_version,
        'dataset_version': base_config.dataset_version,
        'bar_interval': base_config.bar_interval,
        'weights': dict(sorted(weights.items())),
        'candidates': [dict(item) for item in candidate_rows],
    }
    experiment_id = f"experiment_{stable_hash(experiment_payload)[:24]}"
    return ValidationExperiment(
        experiment_id=experiment_id,
        selection_partition="validation",
        selected_candidate_id=selected,
        candidates=tuple(ordered),
    )
