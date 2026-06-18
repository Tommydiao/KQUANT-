from pathlib import Path
import json
from datetime import datetime

import pytest

from btc_eth_15m.dashboard.stdlib_server import stock_live_only_source
from kquant.stock_signals import api_stock_candles, api_stock_signals, api_stock_signals_latest
from kquant.stock_store import connect
from kquant.stock_universe import stock_universe


def test_default_stock_universe_has_100_symbols() -> None:
    stocks = stock_universe("default")
    assert len(stocks) == 100
    assert stocks[0].symbol == "SPY"
    assert "NVDA" in {stock.symbol for stock in stocks}


def test_ai_five_layer_universe_is_complete_and_deduped() -> None:
    stocks = stock_universe("ai_five_layer")
    symbols = [stock.symbol for stock in stocks]
    layers = {stock.layer for stock in stocks}
    assert len(symbols) == len(set(symbols))
    assert {"Energy", "Chips", "Infrastructure", "Models", "Applications"}.issubset(layers)
    assert {"NVDA", "CEG", "MSFT", "PLTR", "CRM"}.issubset(set(symbols))
    assert next(stock for stock in stocks if stock.symbol == "NVDA").layer == "Chips"


def test_user_facing_stock_source_is_live_only() -> None:
    assert stock_live_only_source({}) == "live"
    assert stock_live_only_source({"source": ["live"]}) == "live"
    with pytest.raises(ValueError, match="live-only"):
        stock_live_only_source({"source": ["fixture"]})


def test_fixture_stock_candles_are_deterministic(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant_us.sqlite3"
    first = api_stock_candles("NVDA", "1y", "1d", "fixture", db_path)
    second = api_stock_candles("NVDA", "1y", "1d", "fixture", db_path)
    assert first["provider_status"] == "fixture_read_only"
    assert len(first["candles"]) == 252
    assert first["candles"] == second["candles"]
    first_time = datetime.fromisoformat(first["candles"][0]["open_time"])
    last_time = datetime.fromisoformat(first["candles"][-1]["open_time"])
    assert 340 <= (last_time - first_time).days <= 370


def test_fixture_intraday_candles_match_declared_timeframe(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant_us.sqlite3"
    five_day = api_stock_candles("SPY", "5d", "1h", "fixture", db_path)
    assert five_day["interval"] == "1h"
    assert len(five_day["candles"]) == 35
    trading_dates = {candle["open_time"][:10] for candle in five_day["candles"]}
    assert len(trading_dates) == 5
    assert five_day["candles"][0]["open_time"].endswith("13:30:00+00:00")

    coerced = api_stock_candles("SPY", "5d", "15m", "fixture", db_path)
    assert coerced["interval"] == "1h"
    assert len(coerced["candles"]) == 35

    one_day = api_stock_candles("SPY", "1d", "5m", "fixture", db_path)
    assert one_day["interval"] == "5m"
    assert len(one_day["candles"]) == 78


def test_fixture_higher_timeframe_candles_match_declared_timeframe(tmp_path: Path) -> None:
    db_path = tmp_path / "kquant_us.sqlite3"
    weekly = api_stock_candles("SPY", "5y", "1wk", "fixture", db_path)
    assert weekly["range"] == "5y"
    assert weekly["interval"] == "1wk"
    assert len(weekly["candles"]) == 260
    weekly_first = datetime.fromisoformat(weekly["candles"][0]["open_time"])
    weekly_last = datetime.fromisoformat(weekly["candles"][-1]["open_time"])
    assert 1750 <= (weekly_last - weekly_first).days <= 1850

    monthly = api_stock_candles("SPY", "10y", "1mo", "fixture", db_path)
    assert monthly["range"] == "10y"
    assert monthly["interval"] == "1mo"
    assert len(monthly["candles"]) == 120
    monthly_dates = {candle["open_time"][:7] for candle in monthly["candles"]}
    assert len(monthly_dates) == 120

    coerced = api_stock_candles("SPY", "5y", "1d", "fixture", db_path)
    assert coerced["interval"] == "1wk"


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
    assert "score_breakdown" in payload["signals"][0]
    assert "exit_risk" in payload["signals"][0]
    assert "primary_layer" in payload["signals"][0]
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


def test_fixture_ai_five_layer_signal_run_has_transparent_fields(tmp_path: Path) -> None:
    payload = api_stock_signals(
        source="fixture",
        universe="ai_five_layer",
        profile="swing_long_v1",
        db_path=tmp_path / "kquant_us.sqlite3",
        outputs_dir=tmp_path / "outputs",
        limit=10,
    )
    assert payload["universe"] == "ai_five_layer"
    assert payload["counts"]["total"] == 10
    first = payload["signals"][0]
    assert first["primary_layer"] in {"Energy", "Chips", "Infrastructure", "Models", "Applications"}
    assert first["liquidity_tier"] in {"core", "high_beta"}
    assert first["score_breakdown"]["total_score"] == first["score"]
    assert first["exit_risk"]["status"] in {"CLEAR", "DATA CAUTION", "EXIT RISK", "SETUP INVALIDATED", "TAKE PROFIT WATCH"}


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


def test_live_stock_signals_provider_failure_has_no_buy_setup(tmp_path: Path, monkeypatch) -> None:
    class Response:
        status_code = 429

        def raise_for_status(self) -> None:
            raise RuntimeError("HTTP 429")

        def json(self) -> dict:
            return {}

    monkeypatch.setattr("kquant.stock_signals.requests.get", lambda *args, **kwargs: Response())
    payload = api_stock_signals(
        source="live",
        universe="ai_five_layer",
        profile="swing_long_v1",
        db_path=tmp_path / "kquant_us.sqlite3",
        outputs_dir=tmp_path / "outputs",
        limit=3,
    )
    assert payload["fixture_user_visible"] is False
    assert payload["cache_source"] == "none"
    assert payload["counts"]["buy_setup"] == 0
    assert payload["provider_status"] == "degraded"
    assert all(signal["level"] == "PASS" for signal in payload["signals"])


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


def test_live_latest_without_report_is_cache_only(tmp_path: Path) -> None:
    payload = api_stock_signals_latest(
        source="live",
        universe="default",
        profile="swing_long_v1",
        db_path=tmp_path / "kquant_us.sqlite3",
        outputs_dir=tmp_path / "outputs",
    )
    assert payload["source"] == "live"
    assert payload["provider_status"] == "not_scanned"
    assert payload["counts"]["total"] == 0
    assert payload["signals"] == []
