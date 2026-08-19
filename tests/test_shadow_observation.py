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


def test_shadow_observation_exposes_manual_start_only_after_strategy_freeze(tmp_path: Path) -> None:
    db_path = tmp_path / "frozen-shadow.sqlite3"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO strategy_freezes(
              strategy_version, strategy_id, profile_name, strategy_config_hash,
              validation_fingerprint, evidence_score, status, manifest_json, frozen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("swing_long_v1.1.0", "swing_long", "tactical", "config", "fingerprint", 80.0, "frozen", "{}", "2026-08-19T00:00:00+00:00"),
        )

    status = latest_shadow_observation(db_path)

    assert status["start_allowed"] is True
    assert "start" in status["next_action"].lower()
    assert status["go_no_go"] == "NO_GO"
