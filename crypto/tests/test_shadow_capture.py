from __future__ import annotations

import pytest

from kquant_crypto.shadow_capture import capture_shadow_observations, shadow_payload_from_evaluation


def _evaluation(*, allowed_shadow: bool = True):
    return {
        "evaluation_id": "eval-1",
        "plan_id": "plan-1",
        "asset_id": "asset:ETH",
        "symbol": "ETH",
        "strategy_version": "crypto_roll_v1.0.0",
        "evaluated_at": "2026-08-24T12:00:00+00:00",
        "allowed_shadow": allowed_shadow,
        "strategy_stage": "ARMED",
        "factor_snapshot_hash": "factor-1",
        "source_snapshot_ids": ["market-1"],
        "entry_zone": [100, 101],
        "stop_zone": [95],
        "target_zone": [110],
    }


def _plan():
    return {
        "asset_id": "asset:ETH",
        "symbol": "ETH",
        "strategy_version": "crypto_roll_v1.0.0",
        "data_cutoff_time": "2026-08-24T11:59:00+00:00",
        "coverage": 1.0,
        "data_quality_status": "live",
        "action": "ROLL_BUY",
        "payload": {"bayesian": {"most_likely_state": "BULL"}, "monte_carlo": {"status": "simulation_unavailable"}},
    }


def test_shadow_capture_requires_persisted_point_in_time_fields():
    payload = shadow_payload_from_evaluation(_evaluation(), _plan())
    assert payload["action"] == "ROLL_BUY"
    assert payload["data_cutoff_time"] == "2026-08-24T11:59:00+00:00"

    missing_cutoff = _plan()
    missing_cutoff.pop("data_cutoff_time")
    with pytest.raises(ValueError, match="data_cutoff_time"):
        shadow_payload_from_evaluation(_evaluation(), missing_cutoff)


def test_shadow_capture_rejects_non_eligible_evaluation():
    with pytest.raises(ValueError, match="not shadow eligible"):
        shadow_payload_from_evaluation(_evaluation(allowed_shadow=False), _plan())


def test_shadow_capture_empty_database_creates_no_synthetic_day(settings):
    result = capture_shadow_observations(settings.db_path)
    assert result == {
        "eligible_evaluations": 0,
        "created": 0,
        "duplicates": 0,
        "skipped": [],
        "synthetic_days_created": 0,
        "research_only": True,
    }
