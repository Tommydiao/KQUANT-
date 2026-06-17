import json
import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import yaml

from btc_eth_15m.data import connect, interval_to_millis
from btc_eth_15m.dashboard.app import create_app


def test_research_replay_trades_and_chart_default_to_best_run(tmp_path):
    config_path = _write_replay_fixture(tmp_path)
    app = create_app(config_path)

    trades = _get_json(app, "/api/research/trades?limit=10")

    assert trades["run_id"] == "run-1"
    assert trades["total"] == 2
    assert trades["trades"][0]["id"] == "run-1:0"
    assert trades["trades"][0]["symbol"] == "ETHUSDT"
    assert trades["trades"][0]["entry_price"] == 100.0

    chart = _get_json(app, "/api/research/chart?trade_id=run-1:0&pre_bars=12&post_bars=12")

    assert chart["run_id"] == "run-1"
    assert chart["symbol"] == "ETHUSDT"
    assert chart["selected_trade"]["id"] == "run-1:0"
    assert len(chart["candles"]) >= 3
    assert chart["trades"][0]["id"] == "run-1:0"
    assert chart["window"]["interval"] == "15m"


def test_research_replay_rejects_bad_run_id(tmp_path):
    config_path = _write_replay_fixture(tmp_path)
    app = create_app(config_path)

    bad = _get_json(app, "/api/research/trades?run_id=../bad", expected_status=400)
    missing = _get_json(app, "/api/research/trades?run_id=missing", expected_status=404)

    assert bad["detail"] == "Invalid run_id."
    assert missing["detail"] == "Missing trades file for run_id: missing"


def _get_json(app, path: str, *, expected_status: int = 200):
    async def request():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(path)
            assert response.status_code == expected_status
            return response.json()

    return asyncio.run(request())


def _write_replay_fixture(tmp_path):
    outputs_dir = tmp_path / "outputs"
    runs_dir = tmp_path / "runs"
    db_path = tmp_path / "market.sqlite3"
    outputs_dir.mkdir()
    run_dir = runs_dir / "run-1"
    run_dir.mkdir(parents=True)
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["ETHUSDT"],
                "interval": "15m",
                "db_path": str(db_path),
                "runs_dir": str(runs_dir),
                "outputs_dir": str(outputs_dir),
            }
        ),
        encoding="utf-8",
    )
    (outputs_dir / "20260608T000000Z-sweep.csv").write_text(
        "\n".join(
            [
                "sweep_id,variant,run_id,trade_count,final_equity,total_return_pct,max_drawdown_pct,win_rate_pct,profit_factor,expectancy,avg_r,avg_daily_return_pct,target_range_hit_rate_pct,above_target_min_rate_pct,loss_day_rate_pct,strategy_overrides,app_overrides",
                "sweep-1,daily_target_eth_short_htf,run-1,2,10050,0.5,-1.0,50.0,1.2,10.0,0.2,0.01,0.0,0.0,0.0,{},{}",
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "trades.csv").write_text(
        "\n".join(
            [
                "symbol,side,entry_time,exit_time,entry_price,exit_price,qty,stop,target,gross_pnl,fees,net_pnl,r_multiple,exit_reason,hold_bars,signal_time,signal_close,signal_rsi,signal_atr_pct,signal_regime_atr_pct,signal_volume_ratio,signal_htf_gap_bps,signal_distance_ema_mid_atr,signal_hour_utc",
                "ETHUSDT,long,2026-01-01 01:00:00+00:00,2026-01-01 02:00:00+00:00,100,106,1,96,108,6,0.2,5.8,1.45,target,4,2026-01-01 00:45:00+00:00,99,55,0.01,0.01,1.2,200,1.1,1",
                "ETHUSDT,short,2026-01-01 04:00:00+00:00,2026-01-01 05:00:00+00:00,110,115,1,114,102,-5,0.2,-5.2,-1.3,stop,4,2026-01-01 03:45:00+00:00,111,45,0.01,0.01,1.0,210,-1.0,4",
            ]
        ),
        encoding="utf-8",
    )
    _insert_candles(db_path)
    return config_path


def _insert_candles(db_path):
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    interval_ms = interval_to_millis("15m")
    rows = []
    for index in range(28):
        opened = start + timedelta(minutes=15 * index)
        open_time = int(opened.timestamp() * 1000)
        price = 98.0 + index * 0.5
        rows.append(
            (
                "ETHUSDT",
                "15m",
                open_time,
                opened.isoformat(),
                open_time + interval_ms - 1,
                price,
                price + 2.0,
                price - 2.0,
                price + 0.5,
                1000.0 + index,
                100000.0 + index,
                100 + index,
                datetime.now(tz=UTC).isoformat(),
            )
        )
    with connect(db_path) as connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO klines (
                symbol, interval, open_time, open_time_iso, close_time,
                open, high, low, close, volume, quote_volume, trades, fetched_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.commit()
