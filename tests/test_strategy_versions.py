from __future__ import annotations

from pathlib import Path

import pytest

from kquant.stock_signals import api_stock_signals, persist_ai_action_event, profile_config
from kquant.stock_store import connect
from kquant.strategy_versions import ensure_strategy_version, strategy_version


def test_strategy_version_is_deterministic_for_frozen_profile() -> None:
    first = strategy_version(profile_config("swing_long_v1"))
    second = strategy_version(profile_config("swing_long_v1"))

    assert first.version == "swing_long_v1.0.0"
    assert first.lifecycle == "active_validation"
    assert first.config_hash == second.config_hash
    assert first.config_snapshot["name"] == "swing_long_v1"


def test_strategy_version_rejects_silent_config_mutation(tmp_path: Path) -> None:
    db = tmp_path / "kquant_us.sqlite3"
    baseline = profile_config("swing_long_v1")
    changed = {**baseline, "buy_setup_threshold": int(baseline["buy_setup_threshold"]) + 1}

    with connect(db) as conn:
        initial = ensure_strategy_version(conn, baseline)
        conn.commit()
        assert ensure_strategy_version(conn, baseline).config_hash == initial.config_hash
        with pytest.raises(ValueError, match="Immutable strategy version conflict"):
            ensure_strategy_version(conn, changed)


def test_signal_run_persists_strategy_version_across_derived_records(tmp_path: Path) -> None:
    db = tmp_path / "kquant_us.sqlite3"
    outputs = tmp_path / "outputs"
    payload = api_stock_signals(
        source="fixture",
        universe="default",
        profile="swing_long_v1",
        db_path=db,
        outputs_dir=outputs,
        limit=1,
    )
    expected = strategy_version(profile_config("swing_long_v1"))

    with connect(db) as conn:
        for table in ("stock_signal_runs", "stock_signals", "stock_features", "stock_backtest_runs"):
            row = conn.execute(
                f"SELECT strategy_version, strategy_config_hash FROM {table} LIMIT 1"
            ).fetchone()
            assert row is not None
            assert row["strategy_version"] == expected.version
            assert row["strategy_config_hash"] == expected.config_hash

    assert payload["strategy_version"]["config_hash"] == expected.config_hash


def test_ai_action_event_persists_strategy_version(tmp_path: Path) -> None:
    db = tmp_path / "kquant_us.sqlite3"
    key = persist_ai_action_event(
        db,
        symbol="NVDA",
        profile="swing_long_v1",
        signal={
            "features": {"close": 100},
            "data_status": {"daily_candle_time": "2026-07-18T20:00:00+00:00", "source": "longbridge_candles"},
        },
        decision={"action": "AI_WAIT"},
        market_regime={"regime": "RISK_ON"},
    )
    expected = strategy_version(profile_config("swing_long_v1"))

    with connect(db) as conn:
        row = conn.execute(
            "SELECT strategy_version, strategy_config_hash FROM ai_action_events WHERE event_key = ?",
            (key,),
        ).fetchone()
    assert row is not None
    assert row["strategy_version"] == expected.version
    assert row["strategy_config_hash"] == expected.config_hash
