from __future__ import annotations

import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from kquant.stock_signals import api_stock_signal_journal_entry, api_stock_signals, profile_config
from kquant.strategy_registry import (
    StrategyVersionConflict,
    definition_for_profile,
    register_strategy_version,
)


def test_strategy_versions_are_content_addressed_and_immutable(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant.sqlite3"
    baseline = definition_for_profile("swing_long_v1", profile_config("swing_long_v1"))

    first = register_strategy_version(db_path, baseline)
    repeated = register_strategy_version(db_path, baseline)

    assert first.strategy_version == "swing_long_v1.0.0"
    assert repeated.config_hash == first.config_hash

    changed_config = deepcopy(profile_config("swing_long_v1"))
    changed_config["watch_threshold"] = 66
    changed = definition_for_profile(
        "swing_long_v1",
        changed_config,
        strategy_version="swing_long_v1.0.1",
    )
    changed_record = register_strategy_version(db_path, changed)

    assert changed_record.config_hash != first.config_hash
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT strategy_version, config_hash FROM strategy_versions ORDER BY strategy_version"
        ).fetchall()
    assert rows == [
        ("swing_long_v1.0.0", first.config_hash),
        ("swing_long_v1.0.1", changed_record.config_hash),
    ]

    with pytest.raises(StrategyVersionConflict):
        register_strategy_version(
            db_path,
            definition_for_profile("swing_long_v1", changed_config),
        )


def test_signal_run_persists_strategy_version_and_hash(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant.sqlite3"
    payload = api_stock_signals(
        source="fixture",
        universe="default",
        profile="swing_long_v1",
        db_path=db_path,
        outputs_dir=tmp_path / "outputs",
        limit=1,
    )

    assert payload["strategy_version"] == "swing_long_v1.0.0"
    assert len(payload["strategy_config_hash"]) == 64
    with sqlite3.connect(db_path) as conn:
        run = conn.execute(
            "SELECT strategy_version, strategy_config_hash FROM stock_signal_runs WHERE run_id = ?",
            (payload["run_id"],),
        ).fetchone()
        signal = conn.execute(
            "SELECT strategy_version, strategy_config_hash FROM stock_signals WHERE run_id = ?",
            (payload["run_id"],),
        ).fetchone()
        feature = conn.execute(
            "SELECT strategy_version, strategy_config_hash FROM stock_features WHERE run_id = ?",
            (payload["run_id"],),
        ).fetchone()
        backtest = conn.execute(
            "SELECT strategy_version, strategy_config_hash FROM stock_backtest_runs WHERE run_id = ?",
            (payload["run_id"],),
        ).fetchone()

    expected = (payload["strategy_version"], payload["strategy_config_hash"])
    assert run == expected
    assert signal == expected
    assert feature == expected
    assert backtest == expected


def test_journal_entry_binds_the_current_strategy_version(tmp_path: Path) -> None:
    entry = api_stock_signal_journal_entry(
        {
            "symbol": "NVDA",
            "strategy_profile": "swing_long_v1",
            "status": "paper-observed",
            "notes": "Version binding regression test.",
        },
        db_path=tmp_path / "kquant.sqlite3",
    )["entry"]

    assert entry["strategy_version"] == "swing_long_v1.0.0"
    assert len(entry["strategy_config_hash"]) == 64
