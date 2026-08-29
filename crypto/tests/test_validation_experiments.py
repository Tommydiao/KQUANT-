from __future__ import annotations

from kquant_crypto.validation import ValidationConfig
from kquant_crypto.validation_experiments import ValidationCandidate, run_validation_experiment


def test_parameter_experiment_selects_from_validation_only(monkeypatch, settings):
    def fake_runner(_series, *, registry, weights, config):
        score = float(config.backtest.setup_threshold)
        return {
            "report": {
                "partitions": {
                    "validation": {
                        "summary": {
                            "sample_count": 40,
                            "evidence_status": "limited",
                            "average_r": score,
                            "profit_factor": score + 1.0,
                            "max_drawdown_r": 2.0,
                        }
                    },
                    "test": {"summary": {"average_r": 999.0}},
                }
            }
        }

    monkeypatch.setattr("kquant_crypto.validation_experiments.run_walk_forward_validation", fake_runner)
    experiment = run_validation_experiment(
        (),
        registry=object(),
        weights={"trend_ema_reclaim": 1.0},
        candidates=(
            ValidationCandidate("low", {"setup_threshold": 40}),
            ValidationCandidate("high", {"setup_threshold": 70}),
        ),
        base_config=ValidationConfig(),
    )

    assert experiment.selection_partition == "validation"
    assert experiment.selected_candidate_id == "high"
    assert all("test" not in row for row in experiment.candidates)
    assert experiment.as_dict()["test_results_used_for_selection"] is False


def test_parameter_experiment_rejects_unknown_backtest_field(settings):
    try:
        run_validation_experiment(
            (),
            registry=object(),
            weights={},
            candidates=(ValidationCandidate("bad", {"future_field": 1}),),
            base_config=ValidationConfig(),
        )
    except ValueError as exc:
        assert "future_field" in str(exc)
    else:
        raise AssertionError("unknown backtest fields must fail closed")
