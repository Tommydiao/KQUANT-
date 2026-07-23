from __future__ import annotations

from pathlib import Path

from kquant.backtest_audit import build_backtest_audit, write_backtest_audit


def test_backtest_audit_fingerprint_is_stable_and_writes_reports(tmp_path: Path) -> None:
    payload = {
        "dataset_id": "dataset-1",
        "policy_version": "policy-1",
        "strategy_versions": {"swing_long_v1": "swing_long_v1.1.0"},
        "strategy_config_hashes": {"swing_long_v1": "abc"},
        "config": {"commission_bps_per_side": 1},
        "symbols": ["NVDA"],
        "trades": [{"symbol": "NVDA", "signal_time": "2026-01-01", "entry_price": 10, "exit_price": 11}],
    }
    first = build_backtest_audit(**payload)
    second = build_backtest_audit(**payload)
    assert first["reproducibility_fingerprint"] == second["reproducibility_fingerprint"]
    paths = write_backtest_audit(first, {"sample_count": 1, "win_rate": 100}, tmp_path, run_id="run-1")
    assert Path(paths["json"]).exists()
    assert "reproducibility fingerprint" in Path(paths["markdown"]).read_text(encoding="utf-8").lower()
