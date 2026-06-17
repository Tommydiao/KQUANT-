import csv
import json

from btc_eth_15m.config import AppConfig
from btc_eth_15m.dashboard.research import research_runs
from btc_eth_15m.replay_sweep import write_replay_filter_sweep


def test_replay_filter_sweep_writes_fixed_eth_short_branches(tmp_path):
    runs_dir = tmp_path / "runs"
    outputs_dir = tmp_path / "outputs"
    run_dir = runs_dir / "run-1"
    run_dir.mkdir(parents=True)
    outputs_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "final_equity": 10_015.0,
                "by_symbol": {"ETHUSDT": {"net_pnl": 15.0}},
                "daily_return_stats": {"trading_days": 10},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "trades.csv").write_text(
        "\n".join(
            [
                "symbol,side,entry_time,exit_time,entry_price,exit_price,qty,stop,target,gross_pnl,fees,net_pnl,r_multiple,exit_reason,hold_bars,signal_time,signal_close,signal_rsi,signal_atr_pct,signal_regime_atr_pct,signal_volume_ratio,signal_htf_gap_bps,signal_distance_ema_mid_atr,signal_hour_utc",
                "ETHUSDT,short,2026-01-01 15:00:00+00:00,2026-01-01 16:00:00+00:00,100,90,1,105,80,10,0,10,2,target,4,2026-01-01 14:45:00+00:00,100,45,0.006,0.006,1.6,350,-1,15",
                "ETHUSDT,short,2026-01-02 21:00:00+00:00,2026-01-02 22:00:00+00:00,100,105,1,104,90,-5,0,-5,-1,stop,4,2026-01-02 20:45:00+00:00,100,45,0.02,0.02,1.0,210,-1,21",
            ]
        ),
        encoding="utf-8",
    )
    config = AppConfig(
        symbols=["ETHUSDT"],
        runs_dir=runs_dir,
        outputs_dir=outputs_dir,
        db_path=tmp_path / "market.sqlite3",
    )

    report = write_replay_filter_sweep(config, "run-1")

    assert report.name.endswith("-replay-filter.md")
    csv_path = outputs_dir / report.name.replace(".md", ".csv")
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    assert {row["variant"] for row in rows} == {
        "dt_eth_short_gap300",
        "dt_eth_short_volume15",
        "dt_eth_short_mid_atr",
        "dt_eth_short_regime_mid",
        "dt_eth_short_hour15_16",
        "dt_eth_short_hour21_23",
    }
    assert "not a fresh backtest" in report.read_text(encoding="utf-8")

    runs = research_runs(config)
    assert runs["runs"][0]["type"] == "replay_filter_sweep"
