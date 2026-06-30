from pathlib import Path

import pytest

from kquant.mstr_cycle import (
    api_mstr_cycle_history,
    api_mstr_cycle_journal,
    api_mstr_cycle_journal_entry,
    api_mstr_cycle_radar,
    bayesian_bottom_component,
    parse_strategy_tracker_snapshot,
)


def test_mstr_cycle_radar_writes_report_and_uses_live_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("kquant.mstr_cycle.api_stock_candles", fake_candles)
    monkeypatch.setattr(
        "kquant.mstr_cycle.yahoo_quote_snapshot",
        lambda symbol: {"source": "test", "status": "available", "market_cap": 30_000_000_000, "shares_outstanding": 250_000_000},
    )
    monkeypatch.setattr(
        "kquant.mstr_cycle.strategy_btc_holdings_snapshot",
        lambda: {"source": "test", "status": "available", "btc_holdings": 500_000},
    )

    payload = api_mstr_cycle_radar(db_path=tmp_path / "kquant_us.sqlite3", outputs_dir=tmp_path / "outputs")

    assert payload["symbol"] == "MSTR"
    assert payload["btc_reference_symbol"] == "BTC-USD"
    assert payload["fixture_user_visible"] is False
    assert payload["broker_order_wiring_enabled"] is False
    assert payload["llm_signal_core_enabled"] is False
    assert payload["level"] in {"CYCLE ACCUMULATION", "BOTTOM WATCH", "WAIT", "DISTRIBUTION RISK"}
    assert "premium_proxy" in payload["components"]
    assert payload["monte_carlo"]["status"] == "available"
    assert set(payload["monte_carlo"]["horizons"]) == {"6m", "12m", "24m"}
    for horizon in payload["monte_carlo"]["horizons"].values():
        assert {"p10_return_pct", "p50_return_pct", "p90_return_pct", "median_max_drawdown_pct"}.issubset(horizon)
        assert {"probability_2x_pct", "probability_5x_pct", "probability_10x_pct"}.issubset(horizon)
    assert payload["bayesian_bottom"]["bottom_probability"] > 0
    assert payload["bayesian_bottom"]["does_not_override_level"] is True
    assert payload["cycle_dashboard"]["read_only"] is True
    assert payload["cycle_dashboard"]["does_not_issue_trade_instruction"] is True
    assert payload["cycle_dashboard"]["upgrade_triggers"]
    assert payload["cycle_dashboard"]["ten_x_path"]["target_mstr_price_10x"] > 0
    assert payload["cycle_dashboard"]["ten_x_path"]["required_btc_prices"]
    assert payload["trigger_monitor"]["conditions"]
    assert payload["path_stress_test"]["status"] == "available"
    assert payload["path_stress_test"]["rows"]
    assert payload["tracker_provider_status"] in {"available", "stale_cache", "unavailable"}
    assert payload["strategy_tracker_metrics"]["status"] == "available"
    assert payload["strategy_tracker_metrics"]["treasury_snapshot"]["btc_holdings"] == 500_000
    assert payload["premium_nav_metrics"]["basic_mnav"] is not None
    assert payload["share_metrics"]["sats_per_basic_share"] is not None
    assert payload["debt_financing_metrics"]["calculation_method"]
    assert payload["liquidity_metrics"]["source_type"] == "live_yahoo_chart"
    assert payload["benchmark_metrics"]["calculation_method"]
    assert payload["cycle_history_summary"]["run_count"] >= 1
    history = api_mstr_cycle_history(limit=3, db_path=tmp_path / "kquant_us.sqlite3")
    assert history["status"] == "available"
    assert history["records"][0]["run_id"] == payload["run_id"]
    assert (tmp_path / "outputs" / "mstr-cycle-radar-report.json").exists()
    assert (tmp_path / "outputs" / "mstr-cycle-radar-report.md").exists()


def test_mstr_cycle_journal_persists_without_execution_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("kquant.mstr_cycle.api_stock_candles", fake_candles)
    monkeypatch.setattr(
        "kquant.mstr_cycle.yahoo_quote_snapshot",
        lambda symbol: {"source": "test", "status": "available", "market_cap": 30_000_000_000, "shares_outstanding": 250_000_000},
    )
    monkeypatch.setattr(
        "kquant.mstr_cycle.strategy_btc_holdings_snapshot",
        lambda: {"source": "test", "status": "available", "btc_holdings": 500_000},
    )
    db_path = tmp_path / "kquant_us.sqlite3"
    payload = api_mstr_cycle_radar(db_path=db_path, outputs_dir=tmp_path / "outputs")

    saved = api_mstr_cycle_journal_entry(
        {
            "run_id": payload["run_id"],
            "status": "reviewed",
            "notes": "Reviewed weekly BTC and MSTR structure.",
            "outcome": "Still waiting.",
        },
        db_path=db_path,
    )
    journal = api_mstr_cycle_journal(db_path=db_path)

    assert saved["status"] == "saved"
    assert journal["entries"][0]["status"] == "reviewed"
    assert journal["entries"][0]["notes"] == "Reviewed weekly BTC and MSTR structure."
    serialized = str(journal).lower()
    assert "broker" not in serialized
    assert "order" not in serialized
    assert "paper_order" not in serialized
    assert "live_order" not in serialized


def test_mstr_cycle_rejects_fixture_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="live-only"):
        api_mstr_cycle_radar(source="fixture", db_path=tmp_path / "kquant_us.sqlite3", outputs_dir=tmp_path / "outputs")


def test_mstr_cycle_btc_failure_disables_highest_level(tmp_path: Path, monkeypatch) -> None:
    def candles(symbol: str, range_value: str, interval: str, source: str, db_path: Path):
        if symbol == "BTC-USD":
            return unavailable(symbol, range_value, interval)
        return fake_candles(symbol, range_value, interval, source, db_path)

    monkeypatch.setattr("kquant.mstr_cycle.api_stock_candles", candles)
    monkeypatch.setattr(
        "kquant.mstr_cycle.yahoo_quote_snapshot",
        lambda symbol: {"source": "test", "status": "available", "market_cap": 30_000_000_000, "shares_outstanding": 250_000_000},
    )
    monkeypatch.setattr(
        "kquant.mstr_cycle.strategy_btc_holdings_snapshot",
        lambda: {"source": "test", "status": "available", "btc_holdings": 500_000},
    )

    payload = api_mstr_cycle_radar(db_path=tmp_path / "kquant_us.sqlite3", outputs_dir=tmp_path / "outputs")

    assert payload["provider_status"] == "degraded"
    assert payload["level"] != "CYCLE ACCUMULATION"
    assert any("btc_" in error for error in payload["provider_errors"])


def test_mstr_cycle_missing_premium_proxy_disables_highest_level(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("kquant.mstr_cycle.api_stock_candles", fake_candles)
    monkeypatch.setattr("kquant.mstr_cycle.yahoo_quote_snapshot", lambda symbol: {"source": "test", "status": "unavailable"})
    monkeypatch.setattr(
        "kquant.mstr_cycle.strategy_btc_holdings_snapshot",
        lambda: {"source": "test", "status": "missing", "btc_holdings": None},
    )

    payload = api_mstr_cycle_radar(db_path=tmp_path / "kquant_us.sqlite3", outputs_dir=tmp_path / "outputs")

    assert payload["components"]["premium_proxy"]["status"] == "missing"
    assert payload["level"] != "CYCLE ACCUMULATION"
    assert payload["monte_carlo"]["status"] == "unavailable"
    assert payload["monte_carlo"]["horizons"] == {}
    assert payload["bayesian_bottom"]["confidence"] < 70
    assert "Premium proxy is missing; highest accumulation level is disabled." in payload["blockers"]


def test_strategy_tracker_snapshot_parser_reads_official_fields() -> None:
    html = """
    <script id="__NEXT_DATA__" type="application/json">{
      "props": {"pageProps": {"btcTrackerData": [{
        "latest": true,
        "as_of_date": "2026-06-22",
        "btc_holdings": 847363,
        "basic_shares_outstanding": 358892000,
        "ibit_shares": 388617000,
        "debt": 6754000000,
        "pref": 15466860900,
        "cash": 1400000000,
        "annual_dividends": 806.613,
        "avg_cost_per_btc": 70123.45,
        "total_cost_basis": 59400000000,
        "btc_yield_ytd": 18.7,
        "btc_gain_ytd": 102000,
        "strc_metrics": {"shares": 104894705, "dividend": 11.5, "cumulative_notional": 12304980000}
      }]}}
    }</script>
    """

    snapshot = parse_strategy_tracker_snapshot(html)

    assert snapshot is not None
    assert snapshot["status"] == "available"
    assert snapshot["btc_holdings"] == 847363
    assert snapshot["basic_shares_outstanding"] == 358892000
    assert snapshot["assumed_diluted_shares_outstanding"] == 388617000
    assert snapshot["preferred_stock"] == 15466860900
    assert snapshot["avg_cost_per_btc"] == 70123.45
    assert snapshot["total_cost_basis"] == 59400000000
    assert snapshot["btc_yield_ytd"] == 18.7
    assert snapshot["btc_gain_ytd"] == 102000
    assert snapshot["preferred_series"]["strc"]["shares"] == 104894705


def test_bayesian_bottom_probability_rises_with_positive_evidence() -> None:
    weak = bayesian_bottom_component(
        btc_cycle=component({"drawdown_from_ath_pct": -12, "distance_to_ema200_pct": 80, "rsi14": 70, "momentum_4w_pct": -12}),
        mstr_bottom=component({"drawdown_from_ath_pct": -20, "momentum_4w_pct": -24}),
        relative=component({"drawdown_from_ath_pct": -10, "momentum_4w_pct": -10}),
        premium={"status": "available", "premium_to_btc_nav": 3.1},
        financing={"status": "available"},
        distribution={"score": 0},
    )
    strong = bayesian_bottom_component(
        btc_cycle=component({"drawdown_from_ath_pct": -62, "distance_to_ema200_pct": -8, "rsi14": 42, "momentum_4w_pct": -3}),
        mstr_bottom=component({"drawdown_from_ath_pct": -78, "momentum_4w_pct": -8}),
        relative=component({"drawdown_from_ath_pct": -60, "momentum_4w_pct": 4}),
        premium={"status": "available", "premium_to_btc_nav": 1.35},
        financing={"status": "available"},
        distribution={"score": 0},
    )

    assert strong["bottom_probability"] > weak["bottom_probability"]
    assert len(strong["positive_evidence"]) > len(weak["positive_evidence"])


def test_bayesian_bottom_probability_is_capped_by_distribution_risk() -> None:
    payload = bayesian_bottom_component(
        btc_cycle=component({"drawdown_from_ath_pct": -70, "distance_to_ema200_pct": 0, "rsi14": 40, "momentum_4w_pct": 2}),
        mstr_bottom=component({"drawdown_from_ath_pct": -80, "momentum_4w_pct": 4}),
        relative=component({"drawdown_from_ath_pct": -65, "momentum_4w_pct": 5}),
        premium={"status": "available", "premium_to_btc_nav": 1.2},
        financing={"status": "available"},
        distribution={"score": 80},
    )

    assert payload["bottom_probability"] <= 35
    assert any(item["name"] == "Distribution risk elevated" for item in payload["negative_evidence"])


def fake_candles(symbol: str, range_value: str, interval: str, source: str, db_path: Path) -> dict:
    count = {"1d": 252, "1wk": 260, "1mo": 120}.get(interval, 80)
    if symbol == "BTC-USD":
        start = 100_000.0
        trough = 31_000.0
        end = 45_000.0
    else:
        start = 1_200.0
        trough = 190.0
        end = 420.0
    candles = []
    for index in range(count):
        if index < count * 0.65:
            close = start + (trough - start) * (index / max(count * 0.65, 1))
        else:
            close = trough + (end - trough) * ((index - count * 0.65) / max(count * 0.35, 1))
        open_ = close * 0.98
        candles.append(
            {
                "open_time": f"2024-01-{(index % 28) + 1:02d}T00:00:00+00:00",
                "time": 1_700_000_000 + index * 86_400,
                "open": round(open_, 4),
                "high": round(close * 1.04, 4),
                "low": round(close * 0.96, 4),
                "close": round(close, 4),
                "volume": 1_000_000 + index,
                "source": "yahoo_chart",
            }
        )
    return {
        "instrument_type": "stock",
        "symbol": symbol,
        "range": range_value,
        "interval": interval,
        "source_type": "live_yahoo_chart",
        "provider_status": "available",
        "provider_errors": [],
        "freshness": "live",
        "candles": candles,
    }


def component(metrics: dict) -> dict:
    return {"status": "available", "score": 50, "metrics": metrics, "reasons": []}


def unavailable(symbol: str, range_value: str, interval: str) -> dict:
    return {
        "instrument_type": "stock",
        "symbol": symbol,
        "range": range_value,
        "interval": interval,
        "source_type": "live_yahoo_chart",
        "provider_status": "unavailable",
        "provider_errors": ["provider failed"],
        "freshness": "missing",
        "candles": [],
        "live_does_not_fallback_to_fixture": True,
    }
