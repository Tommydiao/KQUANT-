from pathlib import Path
import json

from kquant.stock_signals import api_stock_candles, api_stock_signals, api_stock_signals_latest
from kquant.stock_store import connect
from kquant.stock_universe import stock_universe


def test_default_stock_universe_has_100_symbols() -> None:
    stocks = stock_universe("default")
    assert len(stocks) == 100
    assert stocks[0].symbol == "SPY"
    assert "NVDA" in {stock.symbol for stock in stocks}


def test_fixture_stock_candles_are_deterministic(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant_us.sqlite3"
    first = api_stock_candles("NVDA", "1y", "1d", "fixture", db_path)
    second = api_stock_candles("NVDA", "1y", "1d", "fixture", db_path)
    assert first["provider_status"] == "fixture_read_only"
    assert len(first["candles"]) == 252
    assert first["candles"] == second["candles"]


def test_fixture_stock_signal_run_writes_report(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant_us.sqlite3"
    outputs_dir = tmp_path / "outputs"
    payload = api_stock_signals(
        source="fixture",
        universe="default",
        profile="swing_long_v1",
        db_path=db_path,
        outputs_dir=outputs_dir,
        limit=12,
    )
    assert payload["counts"]["total"] == 12
    assert payload["profile"]["buy_setup_threshold"] == 82
    assert payload["profile"]["watch_threshold"] == 65
    assert "historical_validation" in payload
    assert payload["llm_signal_core_enabled"] is False
    assert payload["broker_order_wiring_enabled"] is False
    assert (outputs_dir / "stock-signals-report.json").exists()
    with connect(db_path) as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('stock_features', 'stock_labels', 'stock_backtest_runs')"
            )
        }
        assert tables == {"stock_features", "stock_labels", "stock_backtest_runs"}
        assert conn.execute("SELECT COUNT(*) AS count FROM stock_features").fetchone()["count"] == 12
        assert conn.execute("SELECT COUNT(*) AS count FROM stock_backtest_runs").fetchone()["count"] == 1


def test_live_stock_candles_use_stale_cache_without_fixture_fallback(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "kquant_us.sqlite3"

    class Response:
        def __init__(self, status_code: int, body: dict | None = None) -> None:
            self.status_code = status_code
            self._body = body or {}

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self) -> dict:
            return self._body

    body = {
        "chart": {
            "result": [
                {
                    "timestamp": [1_718_000_000, 1_718_086_400, 1_718_172_800],
                    "indicators": {
                        "quote": [
                            {
                                "open": [100, 101, 102],
                                "high": [102, 103, 104],
                                "low": [99, 100, 101],
                                "close": [101, 102, 103],
                                "volume": [1000, 1100, 1200],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }

    monkeypatch.setattr("kquant.stock_signals.requests.get", lambda *args, **kwargs: Response(200, body))
    live = api_stock_candles("SPY", "1y", "1d", "live", db_path)
    assert live["provider_status"] == "available"
    assert live["source_type"] == "live_yahoo_chart"

    monkeypatch.setattr("kquant.stock_signals.requests.get", lambda *args, **kwargs: Response(429))
    stale = api_stock_candles("SPY", "1y", "1d", "live", db_path)
    assert stale["provider_status"] == "stale_cache"
    assert stale["source_type"] == "stale_yahoo_chart_cache"
    assert stale["live_does_not_fallback_to_fixture"] is True
    assert all(candle["source"] != "fixture" for candle in stale["candles"])


def test_latest_stock_signals_do_not_cross_mix_source(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant_us.sqlite3"
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    (outputs_dir / "stock-signals-report.json").write_text(
        json.dumps(
            {
                "run_id": "mock-live",
                "source": "live",
                "universe": "default",
                "profile": {"name": "swing_long_v1"},
                "counts": {"total": 1},
                "signals": [],
            }
        ),
        encoding="utf-8",
    )

    fixture_latest = api_stock_signals_latest(
        source="fixture",
        universe="default",
        profile="swing_long_v1",
        db_path=db_path,
        outputs_dir=outputs_dir,
    )
    assert fixture_latest["source"] == "fixture"
    assert fixture_latest["counts"]["total"] == 100
