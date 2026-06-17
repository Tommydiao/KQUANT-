from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from btc_eth_15m.dashboard.app import create_app
from btc_eth_15m.options_lab import (
    AI_OPTION_SYMBOLS,
    ALL_OPTION_SYMBOLS,
    ATM_ALERT,
    ATM_PASS,
    ATM_WATCH,
    DEFAULT_OPTION_SYMBOLS,
    RECOMMEND_NO_TRADE,
    RECOMMEND_OBSERVE,
    RECOMMEND_TRADE,
    options_atm_alerts,
    options_atm_alerts_latest,
    options_chain,
    options_contract,
    options_daily_candidates,
    options_live_pilot_status,
    options_model_surface,
    options_price_history,
    options_underlyings,
    options_worthiness_report,
)
from btc_eth_15m.options_pilot_journal import load_pilot_journal, record_pilot_journal_entry


def test_options_underlyings_include_spy_and_qqq():
    payload = options_underlyings(source="fixture")

    assert payload["source_type"] == "fixture_read_only"
    assert len(payload["symbols"]) == 50
    assert payload["symbols"] == DEFAULT_OPTION_SYMBOLS
    assert payload["symbols"][:2] == ["SPY", "QQQ"]
    assert {"SPY", "QQQ", "NVDA", "UBER"} <= {item["symbol"] for item in payload["underlyings"]}


def test_options_ai_universe_is_fixed_and_fixture_ready():
    payload = options_underlyings(source="fixture", universe="ai")

    assert payload["universe"] == "ai"
    assert payload["symbols"] == AI_OPTION_SYMBOLS
    assert len(payload["symbols"]) == 30
    assert {"ARM", "TSM", "ASML", "CRWD", "AI", "PATH"} <= set(payload["symbols"])
    by_symbol = {item["symbol"]: item for item in payload["underlyings"]}
    assert "ai_compute" in by_symbol["NVDA"]["theme_tags"]
    assert "ai_security" in by_symbol["CRWD"]["theme_tags"]

    chain = options_chain("ARM", source="fixture")
    option_symbol = chain["contracts"][0]["option_symbol"]
    underlying_history = options_price_history(
        instrument="underlying",
        symbol="ARM",
        source="fixture",
        range_value="1d",
        interval="5m",
    )
    option_history = options_price_history(
        instrument="option",
        option_symbol=option_symbol,
        source="fixture",
        range_value="1d",
        interval="5m",
    )

    assert chain["underlying"]["symbol"] == "ARM"
    assert chain["contracts"]
    assert underlying_history["range"] == "1d"
    assert underlying_history["interval"] == "5m"
    assert underlying_history["candles"]
    assert option_history["candles"]


def test_options_all_universe_keeps_default_and_ai_union():
    payload = options_underlyings(source="fixture", universe="all")

    assert payload["universe"] == "all"
    assert payload["symbols"] == ALL_OPTION_SYMBOLS
    assert len(payload["symbols"]) == 65
    assert payload["universes"]["default"]["symbols"] == DEFAULT_OPTION_SYMBOLS
    assert payload["universes"]["ai"]["symbols"] == AI_OPTION_SYMBOLS


def test_options_chain_exposes_required_contract_fields():
    payload = options_chain("NVDA", source="fixture")
    contract = payload["contracts"][0]

    assert payload["source_type"] == "fixture_read_only"
    assert payload["underlying"]["symbol"] == "NVDA"
    assert payload["expiration_groups"]
    assert payload["chain_rows"]
    for key in ["bid", "ask", "mid", "spread_pct", "volume", "open_interest", "implied_volatility", "delta", "gamma", "theta", "dte"]:
        assert key in contract
    for key in ["side", "moneyness", "data_quality", "quote_updated_at", "model_inputs"]:
        assert key in contract


def test_options_daily_candidates_expose_scan_time_and_quality():
    payload = options_daily_candidates(["SPY"], source="fixture")
    candidate = payload["candidates"][0]

    assert payload["source_type"] == "fixture_read_only"
    assert payload["symbols"] == ["SPY"]
    assert candidate["symbol"] == "SPY"
    assert candidate["scan_time"]
    assert candidate["quote_updated_at"]
    assert candidate["preferred_side"] in {"call", "put", "observe"}
    assert candidate["data_quality"] == "fixture"
    assert candidate["suggested_observation_window"]["label"]


def test_options_contract_detail_scores_selected_contract():
    chain = options_chain("SPY", source="fixture")
    option_symbol = chain["contracts"][0]["option_symbol"]

    payload = options_contract(option_symbol, source="fixture")

    assert payload["option_symbol"] == option_symbol
    assert payload["contract"]["option_symbol"] == option_symbol
    assert payload["score"]["total_score"] >= 0
    assert payload["agent_reason"]
    assert payload["safety"]["order_submission_wired"] is False


def test_options_model_surface_returns_grid_and_safety_payload():
    chain = options_chain("SPY", source="fixture")
    option_symbol = chain["contracts"][0]["option_symbol"]

    payload = options_model_surface(option_symbol, source="fixture")
    model = payload["model"]

    assert payload["option_symbol"] == option_symbol
    assert model["model_type"] == "black_scholes_surface_v1"
    assert len(model["price_axis"]) == 9
    assert len(model["iv_axis"]) == 7
    assert len(model["surface"]) == 7
    assert len(model["surface"][0]["points"]) == 9
    assert model["base"]["theoretical_price"] > 0
    assert model["summary"]["max_pnl_per_contract"] >= model["summary"]["min_pnl_per_contract"]
    assert model["next_3d_inputs"]["z"] == "pnl_per_contract"
    assert model["decision_lens"]["model_type"] == "scenario_weighted_buy_lens_v1"
    assert model["decision_lens"]["decision"] in {"BUY CANDIDATE", "WATCH", "AVOID"}
    assert isinstance(model["decision_lens"]["should_buy"], bool)
    assert "expected_pnl_per_contract" in model["decision_lens"]["metrics"]
    assert model["decision_lens"]["visual_scale"]["metric"] == "pnl_per_contract"
    assert any(band["label"] == "strong edge" for band in model["decision_lens"]["visual_scale"]["bands"])
    assert model["decision_lens"]["safety"]["order_submission_wired"] is False
    assert payload["safety"]["order_submission_wired"] is False


def test_options_model_surface_handles_zero_dte_contract(monkeypatch):
    chain = options_chain("SPY", source="fixture")
    contract = dict(chain["contracts"][0])
    contract["option_symbol"] = "SPY260610C00535000"
    contract["option_type"] = "call"
    contract["dte"] = 0
    contract["expiration"] = "2026-06-10"
    contract["implied_volatility"] = 1.25
    contract["underlying_price"] = 542.18
    underlying = chain["underlying"]

    monkeypatch.setattr(
        "btc_eth_15m.options_lab.options_contract",
        lambda option_symbol, source="live", timeout=8.0: {
            "generated_at": "2026-06-10T00:00:00+00:00",
            "source_type": "fixture_read_only",
            "option_symbol": option_symbol,
            "underlying": underlying,
            "contract": contract,
            "score": None,
            "provider_errors": [],
            "safety": {"live_locked": True, "order_submission_wired": False},
        },
    )

    payload = options_model_surface(contract["option_symbol"], source="fixture")

    assert payload["model"]["base"]["dte"] == 0
    assert payload["model"]["base"]["model_dte"] == 1
    assert any("DTE is 0-1" in note for note in payload["model"]["risk_notes"])


def test_options_worthiness_report_writes_artifacts_and_stays_read_only(tmp_path):
    payload = options_worthiness_report(outputs_dir=tmp_path / "outputs", source="fixture")

    assert payload["overall_recommendation"] in {RECOMMEND_TRADE, RECOMMEND_OBSERVE, RECOMMEND_NO_TRADE}
    assert payload["safety"]["broker_key_required"] is False
    assert payload["safety"]["order_submission_wired"] is False
    assert payload["safety"]["live_locked"] is True
    assert payload["report_path"].endswith("options-worthiness-report.md")
    assert payload["report_json_path"].endswith("options-worthiness-report.json")
    report_md = (tmp_path / "outputs" / "options-worthiness-report.md").read_text(encoding="utf-8")
    assert "US Options Trade Worthiness Report" in report_md
    assert "Data Freshness / Provider Status" in report_md
    assert len(payload["evaluations"]) == 50
    assert {"SPY", "QQQ", "NVDA", "UBER"} <= {item["symbol"] for item in payload["evaluations"]}


def test_options_atm_alerts_fixture_returns_manual_signal_pack(tmp_path):
    payload = options_atm_alerts(symbols=["SPY", "QQQ", "NVDA", "COST", "MSFT"], outputs_dir=tmp_path / "outputs", source="fixture", profile="strict")

    assert payload["module"] == "ATM Options Manual Signal Assistant v1"
    assert payload["strategy_id"] == "atm-manual-options-strict-local-v1"
    assert payload["profile_id"] == "strict_local_v1"
    assert payload["run_id"].startswith("atm-strict_local_v1-")
    assert payload["overall_alert_level"] in {ATM_ALERT, ATM_WATCH, ATM_PASS}
    assert payload["live_pilot_review"]["phase"] == "3_trading_day_live_observation"
    assert payload["live_pilot_review"]["planned_trading_days"] == 3
    assert payload["live_pilot_review"]["review_allowed"] is False
    assert payload["llm_policy"]["llm_signal_core_enabled"] is False
    assert payload["llm_policy"]["external_llm_calls_enabled"] is False
    assert "alert_score" in payload["llm_policy"]["blocked_uses"]
    assert payload["safety"]["llm_signal_core_enabled"] is False
    assert payload["atm_alerts"]
    alert = payload["atm_alerts"][0]
    for key in [
        "symbol",
        "side",
        "option_symbol",
        "strike",
        "dte",
        "moneyness_pct",
        "delta",
        "mid",
        "spread_pct",
        "volume",
        "open_interest",
        "alert_score",
        "alert_level",
        "alert_reasons",
        "why_now",
        "risk_warnings",
        "manual_checklist",
        "model_lens_summary",
        "confidence_label",
    ]:
        assert key in alert
    assert alert["alert_level"] in {ATM_ALERT, ATM_WATCH, ATM_PASS}
    assert alert["model_lens_summary"]["decision"] in {"BUY CANDIDATE", "WATCH", "AVOID"}
    for high_priority in [item for item in payload["atm_alerts"] if item["alert_level"] == ATM_ALERT]:
        assert high_priority["alert_score"] >= 82
        assert high_priority["moneyness_pct"] <= 1
        assert 0.40 <= abs(high_priority["delta"]) <= 0.60
        assert 2 <= high_priority["dte"] <= 21
        assert high_priority["spread_pct"] <= 8
        assert high_priority["volume"] >= 500
        assert high_priority["open_interest"] >= 1000
        assert high_priority["model_lens_summary"]["decision"] != "AVOID"
    assert payload["safety"]["broker_key_required"] is False
    assert payload["safety"]["order_submission_wired"] is False
    assert payload["report_path"].endswith("options-atm-alerts-report.md")
    assert payload["report_json_path"].endswith("options-atm-alerts-report.json")
    report_md = (tmp_path / "outputs" / "options-atm-alerts-report.md").read_text(encoding="utf-8")
    assert "ATM Options Daily Signal Report" in report_md
    assert "Live Pilot Review" in report_md
    assert "Top ATM Alerts" in report_md
    assert "Rejected / PASS Reasons" in report_md
    assert "LLM / AI Review Policy" in report_md
    assert "LLM signal core enabled: `False`" in report_md
    assert "No broker key" in report_md


def test_options_pilot_journal_records_manual_review(tmp_path):
    outputs_dir = tmp_path / "outputs"
    option_symbol = "SPY260626C00530000"

    saved = record_pilot_journal_entry(
        outputs_dir,
        {
            "symbol": "SPY",
            "option_symbol": option_symbol,
            "status": "reviewed",
            "notes": "Stock K-Line confirmed; option spread acceptable.",
            "outcome": "Paper observe after close.",
            "source_type": "fixture_read_only",
            "profile_id": "strict_local_v1",
            "alert_level": ATM_ALERT,
            "alert_score": 84.5,
            "market_date": "2026-06-15",
            "stock_kline_checked": True,
            "option_kline_checked": True,
            "lens_checked": False,
        },
    )
    updated = record_pilot_journal_entry(
        outputs_dir,
        {
            "symbol": "SPY",
            "option_symbol": option_symbol,
            "status": "paper-observed",
            "notes": "Updated after manual review.",
            "source_type": "fixture_read_only",
            "profile_id": "strict_local_v1",
            "market_date": "2026-06-15",
            "stock_kline_checked": True,
            "option_kline_checked": True,
            "lens_checked": True,
        },
    )
    journal = load_pilot_journal(outputs_dir)

    assert saved["entry"]["status"] == "reviewed"
    assert updated["entry"]["status"] == "paper-observed"
    assert len(journal["entries"]) == 1
    assert journal["entries"][0]["option_symbol"] == option_symbol
    assert journal["entries"][0]["stock_kline_checked"] is True
    assert journal["entries"][0]["option_kline_checked"] is True
    assert journal["entries"][0]["lens_checked"] is True
    assert journal["entries"][0]["review_step_complete"] is True
    assert journal["summary"]["paper_observed_count"] == 1
    assert journal["summary"]["review_step_complete_count"] == 1
    assert journal["safety"]["order_submission_wired"] is False


def test_options_price_history_fixture_underlying_and_option():
    chain = options_chain("SPY", source="fixture")
    option_symbol = chain["contracts"][0]["option_symbol"]

    underlying = options_price_history(instrument="underlying", symbol="SPY", source="fixture", range_value="1mo", interval="1d")
    option = options_price_history(instrument="option", option_symbol=option_symbol, source="fixture", range_value="1mo", interval="1d")

    assert underlying["source_type"] == "fixture_read_only"
    assert underlying["instrument_type"] == "underlying"
    assert underlying["range"] == "1mo"
    assert underlying["interval"] == "1d"
    assert len(underlying["candles"]) >= 20
    assert {"open_time", "open", "high", "low", "close", "volume"} <= set(underlying["candles"][0])
    assert option["source_type"] == "fixture_read_only"
    assert option["instrument_type"] == "option"
    assert option["option_symbol"] == option_symbol
    assert len(option["candles"]) == len(underlying["candles"])
    assert option["safety"]["order_submission_wired"] is False


def test_options_api_endpoints(tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(config_path))

    missing_snapshot = client.get("/api/options/snapshots/latest?symbol=MSFT").json()
    underlyings = client.get("/api/options/underlyings?source=fixture").json()
    candidates = client.get("/api/options/daily-candidates?symbols=SPY&source=fixture").json()
    atm_alerts = client.get("/api/options/atm-alerts?symbols=SPY&symbols=QQQ&source=fixture&profile=strict").json()
    chain = client.get("/api/options/chain?symbol=QQQ&source=fixture").json()
    contract = client.get(
        f"/api/options/contract?option_symbol={chain['contracts'][0]['option_symbol']}&source=fixture"
    ).json()
    surface = client.get(
        f"/api/options/model/surface?option_symbol={chain['contracts'][0]['option_symbol']}&source=fixture"
    ).json()
    underlying_history = client.get("/api/options/price-history?instrument=underlying&symbol=SPY&source=fixture").json()
    option_history = client.get(
        f"/api/options/price-history?instrument=option&option_symbol={chain['contracts'][0]['option_symbol']}&source=fixture"
    ).json()
    option_history_1d = client.get(
        f"/api/options/price-history?instrument=option&option_symbol={chain['contracts'][0]['option_symbol']}&range=1d&interval=5m&source=fixture"
    ).json()
    option_history_5d = client.get(
        f"/api/options/price-history?instrument=option&option_symbol={chain['contracts'][0]['option_symbol']}&range=5d&interval=15m&source=fixture"
    ).json()
    option_history_1mo = client.get(
        f"/api/options/price-history?instrument=option&option_symbol={chain['contracts'][0]['option_symbol']}&range=1mo&interval=1d&source=fixture"
    ).json()
    history_3mo = client.get(
        "/api/options/price-history?instrument=underlying&symbol=SPY&range=3mo&interval=1d&source=fixture"
    ).json()
    history_1y = client.get(
        "/api/options/price-history?instrument=underlying&symbol=SPY&range=1y&interval=1d&source=fixture"
    ).json()
    journal_before = client.get("/api/options/pilot-journal").json()
    journal_response = client.post(
        "/api/options/pilot-journal/entry",
        json={
            "symbol": "QQQ",
            "option_symbol": chain["contracts"][0]["option_symbol"],
            "status": "reviewed",
            "notes": "Manual pilot API test.",
            "outcome": "Watch after close.",
            "source_type": "fixture_read_only",
            "profile_id": "strict_local_v1",
            "alert_level": ATM_WATCH,
            "alert_score": 70.5,
            "market_date": "2026-06-15",
            "stock_kline_checked": True,
            "option_kline_checked": True,
            "lens_checked": True,
        },
    )
    journal_saved = journal_response.json()
    journal_after = client.get("/api/options/pilot-journal").json()
    latest = client.get("/api/options/eval/latest?symbols=SPY&symbols=QQQ&source=fixture").json()["eval"]
    snapshot = client.get("/api/options/snapshots/latest?symbol=QQQ").json()
    latest_atm_cache = client.get("/api/options/atm-alerts/latest?universe=default&profile=strict").json()
    latest_chain_cache = client.get("/api/options/chain/latest?symbol=QQQ").json()
    latest_history_cache = client.get(
        "/api/options/price-history/latest?instrument=underlying&symbol=SPY&range=5d&interval=15m"
    ).json()
    live_pilot_status = client.get("/api/options/live-pilot/status").json()
    html = client.get("/").text

    assert missing_snapshot["scan"] is None
    assert missing_snapshot["chain"] is None
    assert missing_snapshot["snapshot_available"] is False
    assert missing_snapshot["freshness"]["is_fresh"] is False
    assert missing_snapshot["provider_status"]["source_type"] == "missing_snapshot"
    assert missing_snapshot["provider_status"]["provider_available"] is False
    assert len(underlyings["symbols"]) == 50
    assert underlyings["symbols"][:2] == ["SPY", "QQQ"]
    assert underlyings["provider_status"]["provider_available"] is True
    assert underlyings["freshness"]["is_fresh"] is True
    ai_underlyings = client.get("/api/options/underlyings?source=fixture&universe=ai").json()
    ai_candidates = client.get("/api/options/daily-candidates?source=fixture&universe=ai").json()
    assert len(ai_underlyings["symbols"]) == 30
    assert ai_underlyings["symbols"] == AI_OPTION_SYMBOLS
    assert ai_candidates["universe"] == "ai"
    assert len(ai_candidates["candidates"]) == 30
    assert candidates["candidates"][0]["symbol"] == "SPY"
    assert candidates["snapshot_id"].startswith("options-scan-")
    assert candidates["freshness"]["is_fresh"] is True
    assert candidates["provider_error_count"] == 0
    assert atm_alerts["snapshot_id"].startswith("options-scan-")
    assert atm_alerts["profile_id"] == "strict_local_v1"
    assert atm_alerts["overall_alert_level"] in {ATM_ALERT, ATM_WATCH, ATM_PASS}
    assert atm_alerts["atm_alerts"]
    assert atm_alerts["atm_alerts"][0]["option_symbol"]
    assert atm_alerts["alert_summary"]["total_alerts"] == len(atm_alerts["atm_alerts"])
    assert atm_alerts["report_path"].endswith("options-atm-alerts-report.md")
    assert atm_alerts["live_pilot_review"]["planned_trading_days"] == 3
    assert atm_alerts["live_pilot_review"]["high_confidence_allowed"] is False
    assert atm_alerts["safety"]["order_submission_wired"] is False
    assert journal_before["summary"]["total_entries"] == 0
    assert journal_response.status_code == 200
    assert journal_saved["entry"]["status"] == "reviewed"
    assert journal_saved["entry"]["option_symbol"] == chain["contracts"][0]["option_symbol"]
    assert journal_after["summary"]["total_entries"] == 1
    assert journal_after["summary"]["review_step_complete_count"] == 1
    assert journal_after["safety"]["order_submission_wired"] is False
    assert chain["underlying"]["symbol"] == "QQQ"
    assert chain["snapshot_id"].startswith("options-chain-")
    assert chain["provider_status"]["provider_available"] is True
    assert chain["chain_rows"]
    assert contract["contract"]["option_symbol"] == chain["contracts"][0]["option_symbol"]
    assert contract["freshness"]["is_fresh"] is True
    assert surface["model"]["surface"]
    assert surface["provider_status"]["provider_available"] is True
    assert underlying_history["candles"]
    assert underlying_history["instrument_type"] == "underlying"
    assert option_history["candles"]
    assert option_history["instrument_type"] == "option"
    assert option_history_1d["range"] == "1d"
    assert option_history_1d["interval"] == "5m"
    assert option_history_1d["candles"]
    assert option_history_5d["range"] == "5d"
    assert option_history_5d["interval"] == "15m"
    assert option_history_5d["candles"]
    assert option_history_1mo["range"] == "1mo"
    assert option_history_1mo["interval"] == "1d"
    assert option_history_1mo["candles"]
    assert history_3mo["range"] == "3mo"
    assert history_3mo["interval"] == "1d"
    assert len(history_3mo["candles"]) == 63
    assert history_1y["range"] == "1y"
    assert history_1y["interval"] == "1d"
    assert len(history_1y["candles"]) == 252
    assert latest["source_type"] == "fixture_read_only"
    assert latest["snapshot_id"].startswith("options-scan-")
    assert latest["provider_error_count"] == 0
    assert latest["report_path"].endswith("options-worthiness-report.md")
    assert snapshot["scan"]["id"] == latest["snapshot_id"]
    assert snapshot["chain"]["id"] == chain["snapshot_id"]
    assert snapshot["provider_status"]["provider_available"] is True
    assert latest_atm_cache["source_type"] == "atm_alerts_snapshot_missing"
    assert latest_atm_cache["snapshot_read_mode"] == "cache_only"
    assert latest_atm_cache["provider_status"]["provider_available"] is False
    assert latest_chain_cache["source_type"] == "chain_snapshot_missing"
    assert latest_history_cache["source_type"] == "price_history_snapshot_missing"
    assert live_pilot_status["phase"] == "3_trading_day_live_observation"
    assert live_pilot_status["planned_trading_days"] == 3
    assert live_pilot_status["default_scan_status"]["status"] == "pending"
    assert live_pilot_status["ai_scan_status"]["status"] == "pending"
    assert live_pilot_status["journal_reviewed_count"] in {0, 1}
    assert live_pilot_status["llm_signal_core_enabled"] is False
    assert live_pilot_status["external_llm_calls_enabled"] is False
    assert "ATM Options Signal Assistant" in html
    assert "Today's ATM Option Alerts" in html
    assert "/api/options/atm-alerts" in html
    assert "/api/options/atm-alerts/latest" in html
    assert "/api/options/chain/latest" in html
    assert "/api/options/price-history/latest" in html
    assert "/api/options/live-pilot/status" in html
    assert "optionsLivePilotStatus" in html
    assert "/api/options/pilot-journal" in html
    assert "data-pilot-save" in html
    assert "Pilot journal saved" in html
    assert "ATM ALERT" in html
    assert "Run ATM Alert Scan" in html
    assert "Refresh ATM Alerts" in html
    assert "strict_local_v1" in html
    assert "LLM Core Locked" in html
    assert "LLM signal core is locked during Live Pilot" in html
    assert "AI Review" in html
    assert "Pilot Today" in html
    assert "data-pilot-stock-kline" in html
    assert "data-pilot-option-kline" in html
    assert "data-pilot-lens" in html
    assert "/api/options/snapshots/latest" in html
    assert "Snapshot freshness" in html
    assert "Agent Eval and Read-only Scan" in html
    assert "Data Center" in html
    assert "3D Options Globe" in html
    assert "Buy Decision Lens" in html
    assert "Daily Operations Loop" in html
    assert "optionsOpsLoop" in html
    assert "Live Data Health" in html
    assert "optionsLiveHealth" in html
    assert "Stock Watchlist" in html
    assert "AI Watchlist" in html
    assert "Default 50" in html
    assert "1D / 5m" in html
    assert "5D / 15m" in html
    assert "1M / 1D" in html
    assert "3M / 1D" in html
    assert "1Y / 1D" in html
    assert "Stock K-Line" in html
    assert "Chart Readiness" in html
    assert "data-stock-frequency" in html
    assert "data-option-frequency" in html
    assert "data-options-chain-side" in html
    assert "data-options-chain-liquidity" in html
    assert "data-options-chain-sort" in html
    assert "Open 3D Buy Lens" in html
    assert "Full Greeks" in html
    assert 'data-view="options-lens"' in html
    assert "optionsWatchlist" in html
    assert "Stock K-Line" in html
    assert "Option Contract K-Line" in html
    assert "lightweight-charts.standalone.production.js" in html
    assert "EMA20 / EMA50 / VWAP" in html
    assert "/api/options/price-history" in html
    assert "strong edge" in html
    assert "premium drag" in html
    assert "data-surface-mode=\"globe\"" in html
    assert "/vendor/three.module.js" in html
    assert "optionsSource" in html
    assert "optionDataSource" in html
    assert "profile=" in html
    assert "forceLiveScan" in html


def test_options_snapshot_endpoint_keeps_provider_outage_visible(monkeypatch, tmp_path):
    def fake_http_json(url, *, timeout, referer=None):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    client = TestClient(create_app(config_path))

    latest = client.get("/api/options/eval/latest?symbols=AAPL&source=live").json()["eval"]
    snapshot = client.get("/api/options/snapshots/latest?symbol=AAPL").json()

    assert latest["source_type"] == "live_read_only_unavailable"
    assert latest["overall_recommendation"] == RECOMMEND_NO_TRADE
    assert latest["provider_errors"]
    assert latest["provider_status"]["provider_available"] is False
    assert snapshot["scan"]["id"] == latest["snapshot_id"]
    assert snapshot["provider_status"]["provider_available"] is False
    assert snapshot["provider_status"]["provider_error_count"] > 0
    assert snapshot["freshness"]["is_fresh"] is True


def test_live_scan_outage_exposes_last_good_live_snapshot(monkeypatch, tmp_path):
    state = {"fail": False}

    def fake_http_json(url, *, timeout, referer=None):
        if state["fail"]:
            raise RuntimeError("provider unavailable")
        if "finance/chart/AAPL" in url:
            return _yahoo_chart_sample()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)
    client = _options_test_client(tmp_path)

    first = client.get("/api/options/daily-candidates?symbols=AAPL&source=live").json()
    state["fail"] = True
    outage = client.get("/api/options/daily-candidates?symbols=AAPL&source=live").json()
    snapshot = client.get("/api/options/snapshots/latest?symbol=AAPL").json()

    assert first["source_type"] == "public_live_us_equities"
    assert outage["source_type"] == "live_read_only_unavailable"
    assert outage["provider_status"]["provider_available"] is False
    assert outage["last_good_snapshot"]["id"] == first["snapshot_id"]
    assert outage["last_good_snapshot"]["payload"]["source_type"] == "public_live_us_equities"
    assert snapshot["scan"]["id"] == outage["snapshot_id"]
    assert snapshot["last_good_scan"]["id"] == first["snapshot_id"]
    assert snapshot["last_good_scan"]["payload"]["source_type"] != "fixture_read_only"


def test_live_price_history_outage_exposes_last_good_live_snapshot(monkeypatch, tmp_path):
    state = {"fail": False}

    def fake_http_json(url, *, timeout, referer=None):
        if state["fail"]:
            raise RuntimeError("provider unavailable")
        if "finance/chart/AAPL" in url:
            return _yahoo_chart_sample()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)
    client = _options_test_client(tmp_path)

    first = client.get("/api/options/price-history?instrument=underlying&symbol=AAPL&range=5d&interval=15m&source=live").json()
    latest = client.get("/api/options/price-history/latest?instrument=underlying&symbol=AAPL&range=5d&interval=15m").json()
    state["fail"] = True
    outage = client.get("/api/options/price-history?instrument=underlying&symbol=AAPL&range=5d&interval=15m&source=live").json()

    assert first["source_type"] == "public_live_us_equity_history"
    assert first["snapshot_id"].startswith("options-history-")
    assert latest["source_type"] == "stale_live_snapshot"
    assert latest["snapshot_read_mode"] == "cache_only"
    assert latest["last_good_snapshot"]["id"] == first["snapshot_id"]
    assert latest["candles"]
    assert outage["source_type"] == "public_live_us_equity_history_unavailable"
    assert outage["candles"] == []
    assert outage["provider_errors"]
    assert outage["last_good_snapshot"]["id"] == first["snapshot_id"]
    assert outage["last_good_snapshot"]["payload"]["source_type"] == "public_live_us_equity_history"
    assert outage["last_good_snapshot"]["payload"]["candles"]


def test_live_options_scanner_parses_public_chain_and_estimates_greeks(monkeypatch, tmp_path):
    def fake_http_json(url, *, timeout, referer=None):
        if "finance/chart/AAPL" in url:
            return _yahoo_chart_sample()
        if "option-chain" in url:
            return _nasdaq_chain_sample()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)

    payload = options_worthiness_report(symbols=["AAPL"], outputs_dir=tmp_path / "outputs", source="live")

    assert payload["source_type"] == "public_live_us_options"
    assert payload["provider_errors"] == []
    assert payload["daily_candidates"][0]["symbol"] == "AAPL"
    assert payload["daily_candidates"][0]["data_quality"] == "live"
    assert payload["safety"]["broker_trading_key_required"] is False
    assert payload["safety"]["order_submission_wired"] is False
    assert payload["evaluations"][0]["symbol"] == "AAPL"
    assert payload["evaluations"][0]["underlying"]["data_source"] == "yahoo_chart_public"
    assert payload["evaluations"][0]["underlying"]["momentum_score"] >= 50
    best = payload["evaluations"][0]["best_contract"]
    contract = best["contract"]
    assert contract["option_symbol"].startswith("AAPL260717C")
    assert contract["implied_volatility"] > 0
    assert 0.2 <= abs(contract["delta"]) <= 0.8
    assert contract["gamma"] > 0
    assert contract["vega"] > 0
    assert payload["live_data_health"]["requested_symbol_count"] == 1
    assert payload["live_data_health"]["successful_symbol_count"] == 1
    assert payload["live_data_health"]["provider_degraded"] is False
    assert payload["report_path"].endswith("options-worthiness-report.md")
    assert "## Live Data Health" in (tmp_path / "outputs" / "options-worthiness-report.md").read_text(encoding="utf-8")


def test_live_options_daily_candidates_partial_provider_failure_is_degraded(monkeypatch):
    def fake_http_json(url, *, timeout, referer=None):
        if "finance/chart/AAPL" in url:
            return _yahoo_chart_sample()
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)

    payload = options_daily_candidates(symbols=["AAPL", "MSFT"], source="live")

    assert payload["source_type"] == "public_live_us_equities"
    assert payload["symbols"] == ["AAPL"]
    assert payload["provider_errors"]
    assert payload["live_data_health"]["requested_symbol_count"] == 2
    assert payload["live_data_health"]["successful_symbol_count"] == 1
    assert payload["live_data_health"]["failed_symbol_count"] == 1
    assert payload["live_data_health"]["provider_degraded"] is True
    assert "MSFT" in payload["live_data_health"]["failed_symbols"]


def test_live_options_chain_groups_call_and_put_rows(monkeypatch):
    def fake_http_json(url, *, timeout, referer=None):
        if "finance/chart/AAPL" in url:
            return _yahoo_chart_sample()
        if "option-chain" in url:
            return _nasdaq_chain_sample()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)

    payload = options_chain("AAPL", source="live")
    row = next(item for item in payload["chain_rows"] if item["strike"] == 300.0)

    assert payload["source_type"] == "public_live_us_options"
    assert payload["data_quality"] == "live"
    assert payload["expiration_groups"][0]["expiration"] == "2026-07-17"
    assert row["call"]["option_symbol"].startswith("AAPL260717C")
    assert row["put"]["option_symbol"].startswith("AAPL260717P")
    assert row["call"]["model_inputs"]["delta"] > 0
    assert row["put"]["model_inputs"]["delta"] < 0


def test_live_options_price_history_parses_yahoo_chart(monkeypatch):
    def fake_http_json(url, *, timeout, referer=None):
        if "finance/chart/AAPL" in url:
            return _yahoo_chart_sample()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)

    payload = options_price_history(instrument="underlying", symbol="AAPL", source="live")

    assert payload["source_type"] == "public_live_us_equity_history"
    assert payload["instrument_type"] == "underlying"
    assert payload["provider_errors"] == []
    assert len(payload["candles"]) == 5
    assert payload["candles"][0]["open"] > 0


def test_live_options_price_history_option_empty_is_visible(monkeypatch):
    def fake_http_json(url, *, timeout, referer=None):
        if "finance/chart/AAPL260717C00300000" in url:
            return _empty_yahoo_option_chart_sample()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)

    payload = options_price_history(
        instrument="option",
        option_symbol="AAPL260717C00300000",
        source="live",
    )

    assert payload["source_type"] == "public_live_us_option_history_empty"
    assert payload["instrument_type"] == "option"
    assert payload["candles"] == []
    assert payload["provider_errors"][0]["error"] == "No traded option candles from public provider."
    assert payload["provider_status"]["provider_available"] is False


def test_live_options_scanner_does_not_fallback_to_fixture_when_provider_fails(monkeypatch, tmp_path):
    def fake_http_json(url, *, timeout, referer=None):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)

    payload = options_worthiness_report(symbols=["AAPL"], outputs_dir=tmp_path / "outputs", source="live")

    assert payload["source_type"] == "live_read_only_unavailable"
    assert payload["overall_recommendation"] == RECOMMEND_NO_TRADE
    assert payload["evaluations"] == []
    assert payload["provider_errors"]
    assert payload["safety"]["live_locked"] is True


def test_live_atm_alerts_do_not_fallback_to_fixture_when_provider_fails(monkeypatch, tmp_path):
    def fake_http_json(url, *, timeout, referer=None):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)

    payload = options_atm_alerts(symbols=["AAPL"], outputs_dir=tmp_path / "outputs", source="live")

    assert payload["source_type"] == "live_read_only_unavailable"
    assert payload["overall_alert_level"] == ATM_PASS
    assert payload["atm_alerts"] == []
    assert payload["provider_errors"]
    assert payload["live_pilot_review"]["data_caution"] is True
    assert payload["live_pilot_review"]["review_allowed"] is False
    assert payload["safety"]["order_submission_wired"] is False
    assert payload["report_path"].endswith("options-atm-alerts-report.md")
    report_md = (tmp_path / "outputs" / "options-atm-alerts-report.md").read_text(encoding="utf-8")
    assert "Live Pilot Review" in report_md


def test_live_atm_alerts_latest_reads_cache_without_provider(monkeypatch, tmp_path):
    calls = {"count": 0}

    def fake_http_json(url, *, timeout, referer=None):
        calls["count"] += 1
        if "finance/chart/AAPL" in url:
            return _yahoo_chart_sample()
        if "option-chain" in url:
            return _nasdaq_chain_sample()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)
    live = options_atm_alerts(symbols=["AAPL"], outputs_dir=tmp_path / "outputs", source="live")
    calls["count"] = 0
    cached = options_atm_alerts_latest(outputs_dir=tmp_path / "outputs")

    assert live["source_type"] == "public_live_us_options_atm_alerts"
    assert cached["source_type"] == "public_live_us_options_atm_alerts"
    assert cached["snapshot_read_mode"] == "cache_only"
    assert cached["atm_alerts"]
    assert cached["live_pilot_review"]["phase"] == "3_trading_day_live_observation"
    assert calls["count"] == 0


def test_live_pilot_status_tracks_scan_and_cooldown_without_provider_rehit(monkeypatch, tmp_path):
    calls = {"count": 0}

    def fake_http_json(url, *, timeout, referer=None):
        calls["count"] += 1
        if "finance/chart/AAPL" in url:
            return _yahoo_chart_sample()
        if "option-chain" in url:
            return _nasdaq_chain_sample()
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("btc_eth_15m.options_lab._http_json", fake_http_json)
    outputs_dir = tmp_path / "outputs"

    live = options_atm_alerts(symbols=["AAPL"], outputs_dir=outputs_dir, source="live", universe="default")
    status = options_live_pilot_status(outputs_dir=outputs_dir, latest_payload=live)
    calls["count"] = 0
    cooled = options_atm_alerts(symbols=["AAPL"], outputs_dir=outputs_dir, source="live", universe="default")

    assert live["source_type"] == "public_live_us_options_atm_alerts"
    assert status["default_scan_status"]["status"] == "completed"
    assert status["ai_scan_status"]["status"] == "pending"
    assert status["llm_signal_core_enabled"] is False
    assert cooled["scan_cooldown_active"] is True
    assert cooled["snapshot_read_mode"] == "cache_only"
    assert calls["count"] == 0
    report_md = (outputs_dir / "options-atm-alerts-report.md").read_text(encoding="utf-8")
    assert "3-Day Pilot Progress" in report_md
    assert "Provider Error Summary" in report_md
    assert "Journal Coverage" in report_md
    assert "LLM Core Locked Policy" in report_md


def _yahoo_chart_sample():
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL",
                        "regularMarketPrice": 290.0,
                        "chartPreviousClose": 280.0,
                        "regularMarketVolume": 320000000,
                        "longName": "Apple Inc.",
                        "regularMarketTime": 1781011800,
                    },
                    "timestamp": [1780666200, 1780752600, 1780839000, 1780925400, 1781011800],
                    "indicators": {
                        "quote": [
                            {
                                "open": [269.0, 273.0, 279.0, 281.0, 286.0],
                                "high": [271.0, 275.0, 281.0, 283.0, 292.0],
                                "low": [268.0, 272.0, 278.0, 280.0, 285.0],
                                "close": [270.0, 274.0, 280.0, 282.0, 290.0],
                                "volume": [100000000, 120000000, 110000000, 130000000, 320000000],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def _options_test_client(tmp_path):
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "symbols": ["BTCUSDT"],
                "db_path": str(tmp_path / "market.sqlite3"),
                "runs_dir": str(tmp_path / "runs"),
                "outputs_dir": str(tmp_path / "outputs"),
            }
        ),
        encoding="utf-8",
    )
    return TestClient(create_app(config_path))


def _empty_yahoo_option_chart_sample():
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL260717C00300000",
                        "instrumentType": "OPTION",
                        "regularMarketPrice": 0.0,
                    },
                    "timestamp": [],
                    "indicators": {"quote": [{"open": [], "high": [], "low": [], "close": [], "volume": []}]},
                }
            ],
            "error": None,
        }
    }


def _nasdaq_chain_sample():
    return {
        "data": {
            "lastTrade": "AAPL $290.00",
            "table": {
                "rows": [
                    {
                        "expirygroup": "July 17, 2026",
                        "expiryDate": None,
                        "strike": None,
                    },
                    {
                        "expirygroup": "",
                        "expiryDate": "Jul 17",
                        "c_Bid": "8.00",
                        "c_Ask": "8.40",
                        "c_Volume": "15000",
                        "c_Openinterest": "60000",
                        "strike": "300.00",
                        "p_Bid": "13.40",
                        "p_Ask": "13.90",
                        "p_Volume": "5000",
                        "p_Openinterest": "22000",
                    },
                    {
                        "expirygroup": "",
                        "expiryDate": "Jul 17",
                        "c_Bid": "4.20",
                        "c_Ask": "4.55",
                        "c_Volume": "4000",
                        "c_Openinterest": "18000",
                        "strike": "315.00",
                        "p_Bid": "25.20",
                        "p_Ask": "26.10",
                        "p_Volume": "800",
                        "p_Openinterest": "5000",
                    },
                ]
            },
        },
        "message": None,
        "status": {"rCode": 200},
    }
