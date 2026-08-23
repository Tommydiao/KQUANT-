from __future__ import annotations

from kquant_crypto.backtest import TradeOutcome
from kquant_crypto.validation_store import latest_validation_run, save_validation_run


def test_validation_run_and_trade_are_auditable(settings):
    outcome = TradeOutcome("2026-08-22T00:00:00+00:00", "2026-08-22T01:00:00+00:00", "2026-08-22T02:00:00+00:00", 100, 104, 98, 104, 2.0, "target", 72, ("trend_ema_reclaim",))
    run_id = save_validation_run(
        settings.db_path,
        strategy_version="crypto_early_v1.0.0",
        dataset_version="dataset_test",
        split_config={"train": 0.6, "validation": 0.2, "test": 0.2, "embargo_bars": 8},
        backtest_config={"fee_bps_per_side": 1, "slippage_bps_per_side": 5},
        status="limited",
        report={"sample_count": 1, "evidence_status": "insufficient"},
        outcomes=[outcome],
        symbol="SOLUSDT",
        asset_id="asset:sol",
    )
    latest = latest_validation_run(settings.db_path)
    assert latest is not None
    assert latest["run_id"] == run_id
    assert latest["trades"][0]["realized_r"] == 2.0


def test_validation_run_persists_partition_and_oos_fold_evidence(settings):
    train = TradeOutcome("2026-08-20T00:00:00+00:00", "2026-08-20T01:00:00+00:00", "2026-08-20T02:00:00+00:00", 100, 102, 98, 104, 1.0, "time_exit", 65, ("trend_ema_reclaim",))
    oos = TradeOutcome("2026-08-22T00:00:00+00:00", "2026-08-22T01:00:00+00:00", "2026-08-22T02:00:00+00:00", 100, 104, 98, 104, 2.0, "target", 72, ("trend_ema_reclaim",))
    run_id = save_validation_run(
        settings.db_path,
        strategy_version="crypto_early_v1.0.0",
        dataset_version="dataset_oos",
        split_config={"oos_folds": 3},
        backtest_config={},
        status="limited",
        report={"oos_fold_count": 1},
        outcomes=[],
        partition_outcomes={"train": [train], "validation": [], "test": []},
        oos_outcomes_by_fold={1: [oos]},
    )
    latest = latest_validation_run(settings.db_path)
    assert latest is not None and latest["run_id"] == run_id
    assert {(trade["evidence_partition"], trade["oos_fold"]) for trade in latest["trades"]} == {
        ("train", None),
        ("oos_test", 1),
    }
