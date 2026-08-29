from __future__ import annotations

import pytest

from kquant_crypto.shadow_store import (
    get_shadow_observation,
    record_shadow_outcome,
    review_shadow_observation,
    save_shadow_observation,
    shadow_summary,
)


def _payload(day: int = 23):
    date = f"2026-08-{day:02d}"
    timestamp = f"{date}T12:00:00+00:00"
    return {
        "asset_scope": "crypto",
        "asset_id": "asset:ETH",
        "symbol": "ETH",
        "strategy_version": "crypto_roll_v1.0.0",
        "action": "ROLL_BUY",
        "strategy_stage": "ARMED",
        "as_of_time": timestamp,
        "data_cutoff_time": f"{date}T11:59:00+00:00",
        "source_status": "live",
        "coverage": 1.0,
        "hard_veto": False,
        "feature_snapshot_id": "features-1",
        "model_version": "crypto_bayesian_v1.0.0",
        "factor_snapshot_hash": "factor-1",
        "source_snapshot_ids": ["market-1"],
        "entry_zone": [100, 101],
        "stop_zone": [95],
        "target_zone": [110],
        "bayesian": {"most_likely_state": "BULL"},
        "monte_carlo": {"status": "simulation_unavailable"},
        "evaluation_id": "eval-1",
        "roll_id": "roll-1",
    }


def test_shadow_observation_is_idempotent_and_inputs_are_kept(settings):
    first, created = save_shadow_observation(settings.db_path, _payload())
    assert created is True
    duplicate, duplicate_created = save_shadow_observation(settings.db_path, _payload())
    assert duplicate_created is False
    assert duplicate["observation_id"] == first["observation_id"]
    reviewed = review_shadow_observation(
        settings.db_path,
        first["observation_id"],
        user_status="reviewed",
        user_note="manual check",
    )
    assert reviewed["user_status"] == "reviewed"
    assert reviewed["entry_zone"] == [100, 101]
    completed = record_shadow_outcome(
        settings.db_path,
        first["observation_id"],
        outcome_status="completed",
        outcome={"realized_r": 0.8, "target_first": True},
    )
    assert completed["outcome"]["realized_r"] == 0.8
    with pytest.raises(ValueError, match="immutable"):
        record_shadow_outcome(
            settings.db_path,
            first["observation_id"],
            outcome_status="completed",
            outcome={"realized_r": 1.0},
        )


def test_shadow_summary_counts_real_calendar_days(settings):
    for day in range(1, 16):
        save_shadow_observation(settings.db_path, _payload(day))
    summary = shadow_summary(settings.db_path, validation_gate_status="NO_GO")
    assert summary["observed_trading_days"] == 15
    assert summary["status"] == "NO_GO"
    assert get_shadow_observation(settings.db_path, "missing") is None
