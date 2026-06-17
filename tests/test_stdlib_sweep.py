from datetime import UTC, datetime, timedelta

from btc_eth_15m.config import AppConfig
from btc_eth_15m.data import connect, interval_to_millis
from btc_eth_15m.stdlib_sweep import ETH_SHORT_VARIANTS, run_stdlib_eth_short_sweep


def test_stdlib_eth_short_sweep_writes_official_sweep_outputs(tmp_path):
    db_path = tmp_path / "market.sqlite3"
    _insert_fixture_bars(db_path)
    config = AppConfig(
        symbols=["ETHUSDT"],
        db_path=db_path,
        runs_dir=tmp_path / "runs",
        outputs_dir=tmp_path / "outputs",
    )

    report = run_stdlib_eth_short_sweep(config, variant_names=["dt_eth_short_hour15_16"])

    assert report.name.endswith("-sweep.md")
    assert (tmp_path / "outputs" / report.name.replace(".md", ".csv")).exists()
    run_dirs = list((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    assert (run_dirs[0] / "summary.json").exists()
    assert (run_dirs[0] / "trades.csv").exists()
    assert (run_dirs[0] / "equity.csv").exists()


def test_stdlib_eth_short_variants_match_requested_branch_names():
    assert [variant[0] for variant in ETH_SHORT_VARIANTS] == [
        "dt_eth_short_gap300",
        "dt_eth_short_volume15",
        "dt_eth_short_mid_atr",
        "dt_eth_short_regime_mid",
        "dt_eth_short_hour15_16",
        "dt_eth_short_hour21_23",
    ]


def _insert_fixture_bars(db_path):
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    interval_ms = interval_to_millis("15m")
    rows = []
    for index in range(260):
        opened = start + timedelta(minutes=15 * index)
        open_time = int(opened.timestamp() * 1000)
        price = 1200.0 - index * 0.5
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
                price - 0.4,
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
