from __future__ import annotations

from pathlib import Path

from kquant.forward_pilot import MINIMUM_COMPLETE_MARKET_DAYS
from kquant.shadow_observation import latest_shadow_observation
from kquant.stock_store import connect


def test_shadow_observation_is_explicitly_not_started_without_real_days(tmp_path: Path) -> None:
    status = latest_shadow_observation(tmp_path / "shadow.sqlite3")

    assert status["status"] == "not_started"
    assert status["market_day_count"] == 0
    assert status["observed_trading_days"] == 0
    assert status["target_trading_days"] == 20
    assert status["minimum_market_days"] == 20
    assert status["start_allowed"] is False
    assert status["go_no_go"] == "NO_GO"
    assert status["real_money_allowed"] is not True


def test_forward_observation_gate_is_not_the_older_fifteen_day_threshold() -> None:
    assert MINIMUM_COMPLETE_MARKET_DAYS == 20


def _insert_frozen_strategy(db_path: Path, fingerprint: str = "fingerprint") -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO strategy_freezes(
              strategy_version, strategy_id, profile_name, strategy_config_hash,
              validation_fingerprint, evidence_score, status, manifest_json, frozen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("swing_long_v1.1.0", "swing_long", "tactical", "config", fingerprint, 80.0, "frozen", "{}", "2026-08-19T00:00:00+00:00"),
        )


def _eligible_stock_quant_validation(fingerprint: str = "fingerprint") -> dict:
    return {
        "status": "materialized",
        "run": {
            "run_id": "sqv-pass",
            "content_hash": fingerprint,
            "validation_version": "stock_quant_validation_test",
            "gate_status": "pass",
            "dataset_integrity_status": "verified",
            "summary": {
                "deployment_status": "eligible",
                "deployment_model": "logistic",
                "deployment_blockers": [],
                "overall_gate_checks": {"phase_five": True},
            },
        },
    }


def test_shadow_observation_blocks_generic_freeze_without_stock_quant_validation(tmp_path: Path) -> None:
    db_path = tmp_path / "frozen-shadow.sqlite3"
    _insert_frozen_strategy(db_path)

    status = latest_shadow_observation(db_path)

    assert status["start_allowed"] is False
    assert status["shadow_start"]["code"] == "stock_quant_validation_not_passed"
    assert status["go_no_go"] == "NO_GO"


def test_shadow_observation_allows_manual_start_only_with_matching_stock_quant_validation(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "eligible-shadow.sqlite3"
    _insert_frozen_strategy(db_path, fingerprint="matching-validation")
    monkeypatch.setattr(
        "kquant.forward_pilot.latest_stock_quant_validation",
        lambda _db_path: _eligible_stock_quant_validation("matching-validation"),
    )

    status = latest_shadow_observation(db_path)

    assert status["start_allowed"] is True
    assert status["shadow_start"]["code"] == "ready"
    assert "linked" in status["next_action"].lower()


def test_shadow_observation_blocks_mismatched_validation_manifest(monkeypatch, tmp_path: Path) -> None:
    db_path = tmp_path / "mismatched-shadow.sqlite3"
    _insert_frozen_strategy(db_path, fingerprint="old-validation")
    monkeypatch.setattr(
        "kquant.forward_pilot.latest_stock_quant_validation",
        lambda _db_path: _eligible_stock_quant_validation("new-validation"),
    )

    status = latest_shadow_observation(db_path)

    assert status["start_allowed"] is False
    assert status["shadow_start"]["code"] == "freeze_validation_mismatch"
