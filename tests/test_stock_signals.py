from pathlib import Path

from kquant.stock_signals import api_stock_candles, api_stock_signals
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
    assert payload["llm_signal_core_enabled"] is False
    assert payload["broker_order_wiring_enabled"] is False
    assert (outputs_dir / "stock-signals-report.json").exists()
