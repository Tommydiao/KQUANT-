from __future__ import annotations

from kquant_crypto.bayesian_model import PointInTimeFeatureSnapshot, infer_bayesian_posterior
from kquant_crypto.monte_carlo import MonteCarloConfig, simulate_monte_carlo


def _features():
    return {
        "trend_score": 0.8,
        "relative_strength": 0.6,
        "momentum": 0.5,
        "volume_pressure": 0.4,
    }


def test_point_in_time_snapshot_rejects_future_available_at():
    try:
        PointInTimeFeatureSnapshot.create(
            asset_id="asset:BTC",
            symbol="BTC",
            signal_time="2026-08-23T12:00:00+00:00",
            available_at="2026-08-23T12:01:00+00:00",
            source_status="live",
            features=_features(),
        )
    except ValueError as exc:
        assert "available_at" in str(exc)
    else:
        raise AssertionError("future available_at must be rejected")


def test_bayesian_posterior_is_versioned_and_normalized():
    snapshot = PointInTimeFeatureSnapshot.create(
        asset_id="asset:BTC",
        symbol="BTC",
        signal_time="2026-08-23T12:00:00+00:00",
        available_at="2026-08-23T11:59:00+00:00",
        source_status="live",
        features=_features(),
        required_features=("trend_score", "relative_strength"),
    )
    posterior = infer_bayesian_posterior(snapshot)
    assert posterior.model_version == "crypto_bayesian_v1.0.0"
    assert abs(sum(posterior.state_probabilities.values()) - 1.0) < 1e-9
    assert posterior.evidence_status == "complete"
    assert posterior.target_before_stop_probability is not None
    assert posterior.to_mapping()["feature_order_hash"]
    assert {item["feature_id"] for item in posterior.evidence} == set(_features())
    assert posterior.evidence[0]["distribution"]["BULL"]["sigma"] > 0


def test_bayesian_training_window_is_point_in_time_and_hashed():
    snapshot = PointInTimeFeatureSnapshot.create(
        asset_id="asset:BTC",
        symbol="BTC",
        signal_time="2026-08-23T12:00:00+00:00",
        available_at="2026-08-23T11:59:00+00:00",
        source_status="live",
        features=_features(),
    )
    posterior = infer_bayesian_posterior(
        snapshot,
        training_window_start="2026-01-01T00:00:00+00:00",
        training_window_end="2026-08-23T11:00:00+00:00",
        training_dataset_hash="dataset-v1",
        random_seed=7,
    )
    assert posterior.training_dataset_hash == "dataset-v1"
    assert posterior.random_seed == 7
    assert posterior.training_window_end == "2026-08-23T11:00:00+00:00"
    try:
        infer_bayesian_posterior(snapshot, training_window_end="2026-08-23T12:01:00+00:00")
    except ValueError as exc:
        assert "signal_time" in str(exc)
    else:
        raise AssertionError("future training window must be rejected")


def test_missing_or_stale_bayesian_inputs_do_not_expose_probabilities():
    snapshot = PointInTimeFeatureSnapshot.create(
        asset_id="asset:BTC",
        symbol="BTC",
        signal_time="2026-08-23T12:00:00+00:00",
        available_at="2026-08-23T11:59:00+00:00",
        source_status="stale",
        features={"trend_score": 0.8},
        required_features=("trend_score", "relative_strength", "momentum"),
    )
    posterior = infer_bayesian_posterior(snapshot)
    assert posterior.evidence_status == "data_caution"
    assert posterior.target_before_stop_probability is None
    assert posterior.data_confidence < 0.75


def test_unregistered_bayesian_feature_is_explicit_data_caution():
    snapshot = PointInTimeFeatureSnapshot.create(
        asset_id="asset:BTC",
        symbol="BTC",
        signal_time="2026-08-23T12:00:00+00:00",
        available_at="2026-08-23T11:59:00+00:00",
        source_status="live",
        features={**_features(), "hidden_factor": 0.9},
    )
    posterior = infer_bayesian_posterior(snapshot)
    assert posterior.evidence_status == "data_caution"
    assert posterior.target_before_stop_probability is None
    assert posterior.unsupported_features == ("hidden_factor",)
    assert posterior.to_mapping()["unsupported_features"] == ["hidden_factor"]


def test_monte_carlo_is_reproducible_and_reports_all_horizons():
    returns = [0.002, -0.001, 0.004, -0.002, 0.001] * 12
    config = MonteCarloConfig(paths=300, block_size=3, seed=11)
    first = simulate_monte_carlo(returns, config=config)
    second = simulate_monte_carlo(returns, config=config)
    assert first.status == "available"
    assert first.result_hash == second.result_hash
    assert first.input_hash == second.input_hash
    assert first.to_mapping()["input_hash"]
    assert set(first.horizons) == {"5", "20", "60"}
    assert 0 <= first.horizons["20"]["p_target_before_stop"] <= 1


def test_monte_carlo_short_history_is_explicitly_unavailable():
    result = simulate_monte_carlo([0.01, -0.01], config=MonteCarloConfig(paths=100))
    assert result.status == "simulation_unavailable"
    assert result.horizons == {}
    assert "no_probability_is_reported" in result.limitations


def test_monte_carlo_can_condition_on_a_regime_and_keeps_ruin_a_probability():
    values = [0.01, 0.02, -0.01, 0.03] * 20
    labels = ["BULL", "BULL", "BEAR_STRESS", "BULL"] * 20
    first = simulate_monte_carlo(values, regime_labels=labels, target_regime="BULL")
    second = simulate_monte_carlo(values, regime_labels=labels, target_regime="BULL")
    assert first.status == "available"
    assert first.result_hash == second.result_hash
    assert first.target_regime == "BULL"
    assert first.to_mapping()["target_regime"] == "BULL"
    assert "regime_conditioned" in first.limitations
    assert all(0.0 <= row["risk_of_ruin"] <= 1.0 for row in first.horizons.values())


def test_leveraged_etf_model_uses_supplied_returns_and_friction():
    returns = [0.01, -0.008, 0.012, -0.004] * 10
    config = MonteCarloConfig(
        paths=100,
        instrument_type="leveraged_etf",
        instrument_id="listed:US:ETHU",
        instrument_data_status="actual",
        daily_leverage=2.0,
        management_fee_bps=100,
        spread_bps=8,
    )
    result = simulate_monte_carlo(returns, config=config)
    assert result.status == "available"
    assert result.config["instrument_type"] == "leveraged_etf"
    assert result.config["daily_leverage"] == 2.0


def test_leveraged_etf_without_actual_series_is_unavailable():
    returns = [0.01, -0.008, 0.012, -0.004] * 10
    result = simulate_monte_carlo(
        returns,
        config=MonteCarloConfig(paths=100, instrument_type="leveraged_etf", daily_leverage=2.0),
    )
    assert result.status == "simulation_unavailable"
    assert result.horizons == {}
    assert "actual_listed_instrument_series_required" in result.limitations
