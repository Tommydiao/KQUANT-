from pathlib import Path
import json
import sqlite3
from datetime import datetime

import pytest

from btc_eth_15m.dashboard.stdlib_server import stock_live_only_source
from kquant.stock_signals import (
    api_stock_ai_daily_agent,
    api_stock_ai_daily_report_latest,
    api_stock_ai_decision,
    api_stock_ai_review,
    api_stock_ai_review_status,
    api_stock_analyze,
    api_stock_candles,
    api_stock_live_data_health,
    api_stock_monday_readiness_latest,
    api_stock_research_chat,
    api_stock_search,
    api_stock_signal_journal_entry,
    api_stock_signals,
    api_stock_signals_latest,
)
from kquant.stock_store import connect
from kquant.stock_universe import stock_universe


def test_default_stock_universe_has_200_symbols() -> None:
    stocks = stock_universe("default")
    assert len(stocks) == 200
    assert stocks[0].symbol == "SPY"
    symbols = {stock.symbol for stock in stocks}
    assert "NVDA" in symbols
    assert {"CEG", "KKR", "VRTX", "XLF", "TTD", "TGT"}.issubset(symbols)
    assert len(symbols) == 200


def test_ai_five_layer_universe_is_complete_and_deduped() -> None:
    stocks = stock_universe("ai_five_layer")
    symbols = [stock.symbol for stock in stocks]
    layers = {stock.layer for stock in stocks}
    assert len(symbols) == len(set(symbols))
    assert {"Energy", "Chips", "Infrastructure", "Models", "Applications"}.issubset(layers)
    assert {"NVDA", "CEG", "MSFT", "PLTR", "CRM"}.issubset(set(symbols))
    assert {"SNDK", "MU", "IREN", "NVTS", "COHR"}.issubset(set(symbols))
    assert next(stock for stock in stocks if stock.symbol == "NVDA").layer == "Chips"
    assert next(stock for stock in stocks if stock.symbol == "SNDK").layer == "Chips"
    assert next(stock for stock in stocks if stock.symbol == "COHR").layer == "Infrastructure"


def test_all_universe_is_core_200_plus_ai_deduped() -> None:
    default_symbols = {stock.symbol for stock in stock_universe("default")}
    ai_symbols = {stock.symbol for stock in stock_universe("ai_five_layer")}
    space_symbols = {stock.symbol for stock in stock_universe("space_robotics")}
    physical_symbols = {stock.symbol for stock in stock_universe("physical_ai")}
    all_symbols = [stock.symbol for stock in stock_universe("all")]
    assert len(all_symbols) == len(set(all_symbols))
    assert set(all_symbols) == default_symbols | ai_symbols | space_symbols | physical_symbols
    assert {"RKLB", "ASTS", "BOTZ", "ROBO"}.issubset(set(all_symbols))
    assert {"SNDK", "IREN", "NVTS", "COHR", "SERV", "AVAV", "LAZR", "RDW"}.issubset(set(all_symbols))
    assert len(all_symbols) > 200


def test_physical_ai_universe_has_four_research_tracks() -> None:
    stocks = stock_universe("physical_ai")
    symbols = {stock.symbol for stock in stocks}
    layers = {stock.layer for stock in stocks}
    assert {
        "Embodied AI Components",
        "Drones / Low Altitude",
        "Spatial Computing",
        "Space Exploration",
    }.issubset(layers)
    assert {"AVAV", "RCAT", "ONDS", "LAZR", "HSAI", "RDW", "RKLB", "BOTZ"}.issubset(symbols)
    assert len(symbols) == len(stocks)


def test_space_robotics_universe_and_search_are_available() -> None:
    stocks = stock_universe("space_robotics")
    symbols = {stock.symbol for stock in stocks}
    assert {"RKLB", "ASTS", "LUNR", "ISRG", "BOTZ", "SERV"}.intersection(symbols)
    assert all(stock.layer == "Space / Robotics" for stock in stocks)

    robot_results = api_stock_search(q="robot", universe="all")["results"]
    space_results = api_stock_search(q="space", universe="all")["results"]
    optical_results = api_stock_search(q="光模块", universe="all")["results"]
    storage_results = api_stock_search(q="存储", universe="all")["results"]
    gpu_cloud_results = api_stock_search(q="GPU云", universe="all")["results"]
    rklb_results = api_stock_search(q="RKLB", universe="all")["results"]
    chinese_robot_results = api_stock_search(q="机器人", universe="all")["results"]
    chinese_space_results = api_stock_search(q="太空", universe="all")["results"]
    chinese_nvda_results = api_stock_search(q="英伟达", universe="all")["results"]
    chinese_chip_results = api_stock_search(q="半导体", universe="all")["results"]
    assert any(item["symbol"] in {"BOTZ", "ROBO", "SYM", "ISRG"} for item in robot_results)
    assert any(item["symbol"] in {"RKLB", "ASTS", "LUNR", "PL"} for item in space_results)
    assert any(item["symbol"] in {"COHR", "FN", "LITE", "CRDO"} for item in optical_results)
    assert any(item["symbol"] in {"SNDK", "WDC", "STX", "MU"} for item in storage_results)
    assert any(item["symbol"] in {"IREN", "NBIS", "CORZ"} for item in gpu_cloud_results)
    assert rklb_results[0]["symbol"] == "RKLB"
    assert any(item["symbol"] in {"BOTZ", "ROBO", "SYM", "ISRG"} for item in chinese_robot_results)
    assert any(item["symbol"] in {"RKLB", "ASTS", "LUNR", "PL"} for item in chinese_space_results)
    assert chinese_nvda_results[0]["symbol"] == "NVDA"
    assert any(item["symbol"] in {"NVDA", "AMD", "SMH", "SOXX"} for item in chinese_chip_results)


def test_physical_ai_search_terms_route_to_research_tracks() -> None:
    embodied = api_stock_search(q="具身智能", universe="all")["results"]
    drones = api_stock_search(q="无人机", universe="all")["results"]
    spatial = api_stock_search(q="空间计算", universe="all")["results"]
    lidar = api_stock_search(q="激光雷达", universe="all")["results"]
    space = api_stock_search(q="太空探索", universe="all")["results"]
    assert any(item["symbol"] in {"BOTZ", "ROBO", "SYM", "ISRG", "ROK"} for item in embodied)
    assert any(item["symbol"] in {"AVAV", "KTOS", "RCAT", "ONDS", "EH"} for item in drones)
    assert any(item["symbol"] in {"AAPL", "META", "VUZI", "KOPN", "OUST"} for item in spatial)
    assert any(item["symbol"] in {"LAZR", "OUST", "HSAI", "AEVA", "MVIS"} for item in lidar)
    assert any(item["symbol"] in {"RKLB", "ASTS", "LUNR", "PL", "RDW"} for item in space)


def test_ai_review_status_without_key_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    payload = api_stock_ai_review_status()
    assert payload["status"] == "missing_key"
    assert payload["llm_signal_core_enabled"] is True
    assert payload["ai_decision_engine_enabled"] is False
    assert payload["hard_rule_veto_enabled"] is True
    assert payload["broker_order_wiring_enabled"] is False


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
    assert "validation_by_level" in payload
    assert set(payload["validation_by_level"]) == {"BUY SETUP", "WATCH", "PASS"}
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


def test_fixture_stock_signal_layer_scan_limits_to_selected_layer(tmp_path: Path) -> None:
    payload = api_stock_signals(
        source="fixture",
        universe="default",
        profile="swing_long_v1",
        db_path=tmp_path / "kquant_us.sqlite3",
        outputs_dir=tmp_path / "outputs",
        limit=200,
        layer="Healthcare",
    )
    assert payload["scan_layer"] == "Healthcare"
    assert payload["universe_total"] == len([stock for stock in stock_universe("default") if stock.layer == "Healthcare"])
    assert payload["counts"]["total"] == payload["universe_total"]
    assert {signal["primary_layer"] for signal in payload["signals"]} == {"Healthcare"}


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
    assert first["exit_risk"]["status"] in {
        "CLEAR",
        "DATA CAUTION",
        "EXIT RISK",
        "SETUP INVALIDATED",
        "TAKE PROFIT WATCH",
        "PULLBACK RISK",
        "HIGH VOLATILITY RISK",
    }


def test_all_strategy_profiles_return_profile_specific_fields(tmp_path: Path) -> None:
    profiles = {
        "tactical_1w_v1": "3-7 trading days",
        "swing_1_2m_v1": "20-40 trading days",
        "position_6m_v1": "3-6 months",
        "cycle_1_3y_v1": "1-3 years",
        "high_beta_growth_v1": "3-15 trading days",
    }
    for profile, holding_period in profiles.items():
        payload = api_stock_signals(
            source="fixture",
            universe="default",
            profile=profile,
            db_path=tmp_path / f"{profile}.sqlite3",
            outputs_dir=tmp_path / profile,
            limit=3,
        )
        assert payload["profile"]["name"] == profile
        assert payload["profile"]["holding_period"] == holding_period
        assert "validation_by_strategy_profile" in payload
        assert payload["validation_by_strategy_profile"]["focus_window"] == payload["profile"]["focus_window"]
        first = payload["signals"][0]
        assert first["profile_name"] == profile
        assert first["holding_period"] == holding_period
        assert first["primary_timeframe"] == payload["profile"]["primary_timeframe"]
        assert first["confirmation_timeframe"] == payload["profile"]["confirmation_timeframe"]
        assert "exit_plan" in first
        assert "trade_conclusion" in first
        assert first["trade_conclusion"]["action"] in {"BUY", "WAIT", "DO_NOT_BUY", "HOLD_TRAIL", "EXIT_REVIEW"}
        assert first["trade_conclusion"]["llm_signal_core_enabled"] is False
        assert "focus_window" in first["historical_edge"]
        assert first["historical_edge"]["profile_note"].startswith("Profile edge")


def test_high_beta_growth_profile_is_separate_aggressive_system(tmp_path: Path) -> None:
    payload = api_stock_analyze(
        "RKLB",
        source="fixture",
        profile="high_beta_growth_v1",
        db_path=tmp_path / "kquant_us.sqlite3",
    )
    signal = payload["signal"]
    assert payload["profile"]["name"] == "high_beta_growth_v1"
    assert payload["profile"]["label"] == "High-Beta Growth"
    assert payload["profile"]["max_atr_pct"] == 12.0
    assert signal["profile_name"] == "high_beta_growth_v1"
    assert signal["holding_period"] == "3-15 trading days"
    assert "high-beta" in signal["score_breakdown"]["formula"]
    assert signal["trade_conclusion"]["llm_signal_core_enabled"] is False
    assert signal["trade_conclusion"]["broker_order_wiring_enabled"] is False


def test_stock_analyze_returns_single_symbol_profile_payload(tmp_path: Path) -> None:
    payload = api_stock_analyze(
        "NVDA",
        source="fixture",
        profile="position_6m_v1",
        db_path=tmp_path / "kquant_us.sqlite3",
    )
    assert payload["symbol"] == "NVDA"
    assert payload["profile"]["name"] == "position_6m_v1"
    assert payload["universe_match"] is True
    assert payload["signal"]["profile_name"] == "position_6m_v1"
    assert payload["signal"]["exit_plan"]["read_only_research"] is True
    assert payload["signal"]["trade_conclusion"]["read_only_research"] is True
    assert payload["signal"]["features"]["ema8"] > 0
    assert payload["signal"]["features"]["ema9"] > 0
    packet = payload["signal"]["ai_feature_packet_v1"]
    assert packet["version"] == "ai_feature_packet_v1"
    assert packet["price_structure"]["ema8"] > 0
    assert packet["price_structure"]["ema9"] > 0
    assert packet["confirmation_structure"]["ema8"] > 0
    assert packet["data_quality"]["daily_candles"] > 0
    assert packet["rule_state"]["level"] == payload["signal"]["level"]
    assert packet["ai_policy"]["hard_veto_remains_active"] is True
    assert payload["primary_candles"]["candle_count"] > 0
    assert payload["confirmation_candles"]["candle_count"] > 0
    assert payload["broker_order_wiring_enabled"] is False
    assert payload["llm_signal_core_enabled"] is False


def test_ai_review_without_api_key_returns_safe_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    signal = api_stock_analyze("NVDA", source="fixture", profile="tactical_1w_v1", db_path=tmp_path / "kquant_us.sqlite3")["signal"]
    payload = api_stock_ai_review(
        {
            "symbol": "NVDA",
            "profile": "tactical_1w_v1",
            "signal_payload": signal,
            "journal_context_limit": 5,
        },
        db_path=tmp_path / "kquant_us.sqlite3",
    )
    assert payload["status"] == "ai_review_unavailable"
    assert payload["ai_review"]["ai_review_verdict"] == "caution"
    assert payload["rule_conclusion"]["action"] == signal["trade_conclusion"]["action"]
    assert payload["safety_policy"]["llm_signal_core_enabled"] is False
    assert payload["safety_policy"]["broker_order_wiring_enabled"] is False
    assert payload["safety_policy"]["does_not_override_rule_conclusion"] is True


def test_ai_review_parses_openai_response_without_overriding_rule(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    signal = api_stock_analyze("NVDA", source="fixture", profile="tactical_1w_v1", db_path=tmp_path / "kquant_us.sqlite3")["signal"]

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "output_text": json.dumps(
                    {
                        "ai_review_verdict": "caution",
                        "quality_filter": "mixed",
                        "rr_improvement_notes": ["Wait for a cleaner pullback.", "Do not chase extension."],
                        "risk_questions": ["Is data clean?", "Does the 1H trigger still hold?"],
                        "journal_prompt": ["Record invalidation.", "Record planned stop."],
                        "downgrade_suggestion": "consider_wait",
                        "summary": "AI review is commentary only.",
                    }
                )
            }

    def fake_post(*args, **kwargs):
        assert kwargs["json"]["model"] == "gpt-5.4"
        return Response()

    monkeypatch.setattr("kquant.stock_signals.requests.post", fake_post)
    payload = api_stock_ai_review(
        {
            "symbol": "NVDA",
            "profile": "tactical_1w_v1",
            "signal_payload": signal,
            "model_tier": "review",
        },
        db_path=tmp_path / "kquant_us.sqlite3",
    )
    assert payload["status"] == "available"
    assert payload["ai_review"]["ai_review_verdict"] == "caution"
    assert payload["ai_review"]["does_not_override_rule_conclusion"] is True
    assert payload["rule_conclusion"] == signal["trade_conclusion"]
    assert payload["safety_policy"]["llm_signal_core_enabled"] is False


def test_ai_decision_without_key_is_agent_fallback_and_read_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    signal = api_stock_analyze("NVDA", source="fixture", profile="tactical_1w_v1", db_path=tmp_path / "kquant_us.sqlite3")["signal"]
    payload = api_stock_ai_decision(
        {
            "symbol": "NVDA",
            "profile": "tactical_1w_v1",
            "signal_payload": signal,
            "journal_context_limit": 5,
        },
        db_path=tmp_path / "kquant_us.sqlite3",
    )
    assert payload["status"] == "ai_unavailable"
    assert payload["product"] == "KQUANT AI Trading Agent"
    assert payload["ai_decision"]["action"] in {"AI_WAIT", "AI_AVOID", "AI_EXIT_REVIEW"}
    assert payload["ai_decision"]["broker_order_wiring_enabled"] is False
    assert payload["safety_policy"]["ai_leads_decision_layer"] is True
    assert payload["safety_policy"]["order_submission_enabled"] is False


def test_ai_decision_hard_veto_blocks_model_buy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    signal = api_stock_analyze("NVDA", source="fixture", profile="tactical_1w_v1", db_path=tmp_path / "kquant_us.sqlite3")["signal"]
    signal["data_status"]["data_quality"] = "caution"
    signal["data_status"]["daily_provider_status"] = "provider_failed"

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "output_text": json.dumps(
                    {
                        "action": "AI_BUY_CANDIDATE",
                        "confidence": "HIGH",
                        "risk_bucket": "standard_risk",
                        "entry_zone": "Buy near support.",
                        "stop_zone": "Below support.",
                        "target_zone": "Prior high.",
                        "risk_reward": "2.5R",
                        "position_size_hint": "small",
                        "why_now": ["Momentum is improving.", "Trend is supportive."],
                        "what_invalidates_this_setup": ["Provider fails.", "Price loses support."],
                        "best_profile": "tactical_1w_v1",
                        "human_checklist": ["Check live K-line.", "Save journal."],
                        "summary": "Model wants buy.",
                    }
                )
            }

    def fake_post(*args, **kwargs):
        request_payload = kwargs["json"]
        context = json.loads(request_payload["input"][1]["content"])
        assert context["ai_feature_packet_v1"]["version"] == "ai_feature_packet_v1"
        assert context["ai_feature_packet_v1"]["price_structure"]["ema8"] > 0
        assert context["ai_feature_packet_v1"]["confirmation_structure"]["ema9"] > 0
        return Response()

    monkeypatch.setattr("kquant.stock_signals.requests.post", fake_post)
    payload = api_stock_ai_decision(
        {
            "symbol": "NVDA",
            "profile": "tactical_1w_v1",
            "signal_payload": signal,
            "model_tier": "review",
        },
        db_path=tmp_path / "kquant_us.sqlite3",
    )
    assert payload["status"] == "available"
    assert payload["hard_veto"]["active"] is True
    assert payload["ai_decision"]["action"] != "AI_BUY_CANDIDATE"
    assert payload["ai_decision"]["hard_veto_applied"] is True
    assert payload["ai_decision"]["confidence"] != "HIGH"


def test_research_chat_without_key_returns_safe_unavailable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    signal = api_stock_analyze("NVDA", source="fixture", profile="tactical_1w_v1", db_path=tmp_path / "kquant_us.sqlite3")["signal"]
    payload = api_stock_research_chat(
        {
            "symbol": "NVDA",
            "profile": "tactical_1w_v1",
            "signal_payload": signal,
            "question": "Should I buy this setup?",
            "language": "zh",
        },
        db_path=tmp_path / "kquant_us.sqlite3",
    )
    assert payload["status"] == "ai_unavailable"
    assert payload["model_name"]
    assert payload["answer"]["risk_flags"]
    assert payload["safety_policy"]["broker_order_wiring_enabled"] is False
    assert payload["safety_policy"]["order_submission_enabled"] is False


def test_research_chat_uses_research_model_and_parses_response(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("KQUANT_AI_RESEARCH_MODEL", "gpt-5.5-pro")
    signal = api_stock_analyze("NVDA", source="fixture", profile="tactical_1w_v1", db_path=tmp_path / "kquant_us.sqlite3")["signal"]

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "output_text": json.dumps(
                    {
                        "answer": "NVDA is a researchable setup, but wait for confirmation.",
                        "direct_view": "Wait for cleaner entry.",
                        "key_points": ["Trend is constructive.", "Risk/reward depends on entry."],
                        "risk_flags": ["High valuation risk"],
                        "what_to_check_next": ["Daily support", "1H momentum"],
                        "evidence_used": ["KQUANT signal payload"],
                        "follow_up_questions": ["What is the stop?", "What invalidates the setup?"],
                        "safety_note": "Read-only research.",
                    }
                )
            }

    def fake_post(*args, **kwargs):
        assert kwargs["json"]["model"] == "gpt-5.5-pro"
        return Response()

    monkeypatch.setattr("kquant.stock_signals.requests.post", fake_post)
    payload = api_stock_research_chat(
        {
            "symbol": "NVDA",
            "profile": "tactical_1w_v1",
            "signal_payload": signal,
            "question": "Deep research this setup.",
            "messages": [{"role": "user", "content": "Prior question"}],
            "language": "en",
        },
        db_path=tmp_path / "kquant_us.sqlite3",
    )
    assert payload["status"] == "available"
    assert payload["model_name"] == "gpt-5.5-pro"
    assert payload["answer"]["direct_view"] == "Wait for cleaner entry."
    assert payload["safety_policy"]["does_not_trigger_scans"] is True
    assert payload["safety_policy"]["order_submission_enabled"] is False


def test_research_chat_falls_back_when_primary_model_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("KQUANT_AI_RESEARCH_MODEL", "gpt-5.5-pro")
    monkeypatch.setenv("KQUANT_AI_DEEP_MODEL", "gpt-5.5")
    signal = api_stock_analyze("NVDA", source="fixture", profile="tactical_1w_v1", db_path=tmp_path / "kquant_us.sqlite3")["signal"]
    calls: list[str] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "output_text": json.dumps(
                    {
                        "answer": "Fallback model answered safely.",
                        "direct_view": "Fallback succeeded.",
                        "key_points": ["Primary failed.", "Fallback model returned a structured answer."],
                        "risk_flags": ["Model fallback was used"],
                        "what_to_check_next": ["Review model status.", "Confirm live data remains clean."],
                        "evidence_used": ["KQUANT signal payload"],
                        "follow_up_questions": ["Retry primary later?", "Check setup again?"],
                        "safety_note": "Read-only research.",
                    }
                )
            }

    def fake_post(*args, **kwargs):
        model = kwargs["json"]["model"]
        calls.append(model)
        if model == "gpt-5.5-pro":
            raise TimeoutError("primary model timed out")
        return Response()

    monkeypatch.setattr("kquant.stock_signals.requests.post", fake_post)
    payload = api_stock_research_chat(
        {
            "symbol": "NVDA",
            "profile": "tactical_1w_v1",
            "signal_payload": signal,
            "question": "Deep research this setup.",
            "language": "en",
        },
        db_path=tmp_path / "kquant_us.sqlite3",
    )
    assert calls == ["gpt-5.5-pro", "gpt-5.5"]
    assert payload["status"] == "available"
    assert payload["model_name"] == "gpt-5.5"
    assert payload["primary_model_name"] == "gpt-5.5-pro"
    assert payload["fallback_model_used"] is True
    assert "TimeoutError" in payload["fallback_reason"]
    assert payload["answer"]["direct_view"] == "Fallback succeeded."


def test_ai_daily_agent_without_key_writes_read_only_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    signal = api_stock_analyze("NVDA", source="fixture", profile="tactical_1w_v1", db_path=tmp_path / "kquant_us.sqlite3")["signal"]

    def fake_signals(*args, **kwargs):
        return {
            "signals": [signal],
            "provider_errors": [],
        }

    monkeypatch.setattr("kquant.stock_signals.api_stock_signals", fake_signals)
    monkeypatch.setattr(
        "kquant.stock_signals.api_stock_market_regime",
        lambda *args, **kwargs: {"regime": "RISK_ON", "score": 70, "high_confidence_allowed": True, "reasons": []},
    )
    payload = api_stock_ai_daily_agent(
        {
            "universe": "default",
            "limit": 5,
            "top_n": 3,
            "profiles": ["tactical_1w_v1"],
        },
        db_path=tmp_path / "kquant_us.sqlite3",
        outputs_dir=tmp_path / "outputs",
    )
    assert payload["status"] == "ai_unavailable"
    assert payload["broker_order_wiring_enabled"] is False
    assert payload["ai_report"]["top_buy_candidates"] == []
    assert (tmp_path / "outputs" / "ai-daily-opportunities.json").exists()
    latest = api_stock_ai_daily_report_latest(outputs_dir=tmp_path / "outputs")
    assert latest["run_id"] == payload["run_id"]


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


def test_live_stock_candles_return_when_cache_write_fails(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "kquant_us.sqlite3"

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1_718_000_000, 1_718_086_400],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [100, 101],
                                        "high": [102, 103],
                                        "low": [99, 100],
                                        "close": [101, 102],
                                        "volume": [1000, 1100],
                                    }
                                ]
                            },
                        }
                    ],
                    "error": None,
                }
            }

    monkeypatch.setattr("kquant.stock_signals.requests.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(
        "kquant.stock_signals.persist_candles",
        lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("readonly")),
    )

    payload = api_stock_candles("SPY", "1y", "1d", "live", db_path)

    assert payload["provider_status"] == "available"
    assert payload["source_type"] == "live_yahoo_chart"
    assert len(payload["candles"]) == 2
    assert payload["cache_write_status"] == "failed"
    assert payload["live_data_returned_despite_cache_write_failure"] is True
    assert any("cache_write_failed" in error for error in payload["provider_errors"])
    assert all(candle["source"] != "fixture" for candle in payload["candles"])


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


def test_live_data_health_report_writes_database_summary(tmp_path: Path, monkeypatch) -> None:
    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "chart": {
                    "result": [
                        {
                            "timestamp": [1_718_000_000, 1_718_086_400, 1_718_172_800, 1_718_259_200],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [100, 101, 102, 103],
                                        "high": [102, 103, 104, 105],
                                        "low": [99, 100, 101, 102],
                                        "close": [101, 102, 103, 104],
                                        "volume": [1000, 1100, 1200, 1300],
                                    }
                                ]
                            },
                        }
                    ],
                    "error": None,
                }
            }

    monkeypatch.setattr("kquant.stock_signals.requests.get", lambda *args, **kwargs: Response())
    payload = api_stock_live_data_health(
        universes=["default", "ai_five_layer"],
        db_path=tmp_path / "kquant_us.sqlite3",
        outputs_dir=tmp_path / "outputs",
        limit=2,
    )
    assert payload["fixture_user_visible"] is False
    assert payload["summary"]["symbol_count"] == 4
    assert payload["summary"]["timeframe_checks"] == 16
    assert payload["summary"]["available_checks"] == 16
    assert payload["database"]["tables_ready"] is True
    assert (tmp_path / "outputs" / "stock-live-data-health.json").exists()
    assert "KQUANT Stock Live Data Health" in (tmp_path / "outputs" / "stock-live-data-health.md").read_text(encoding="utf-8")


def test_monday_readiness_latest_missing_is_not_scanned(tmp_path: Path) -> None:
    payload = api_stock_monday_readiness_latest(outputs_dir=tmp_path / "outputs")
    assert payload["status"] == "not_scanned"
    assert payload["available"] is False
    assert payload["fixture_user_visible"] is False
    assert payload["broker_order_wiring_enabled"] is False
    assert payload["order_submission_enabled"] is False
    assert payload["pilot_rules"]["journal_before_entry"] is True


def test_monday_readiness_latest_reads_ready_report(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "monday-pilot-readiness.json").write_text(
        json.dumps(
            {
                "run_id": "monday-readiness-test",
                "generated_at_utc": "2026-07-04T10:06:55Z",
                "status": "READY",
                "critical_failure_count": 0,
                "warning_count": 0,
                "checks": [{"name": "backend_online", "passed": True, "critical": True, "detail": "status=online"}],
                "pilot_rules": {"journal_before_entry": True},
            }
        ),
        encoding="utf-8",
    )
    payload = api_stock_monday_readiness_latest(outputs_dir=outputs)
    assert payload["status"] == "READY"
    assert payload["available"] is True
    assert payload["latest_cache_status"] == "available"
    assert payload["checks"][0]["name"] == "backend_online"
    assert payload["read_only_research"] is True


def test_monday_readiness_latest_bad_json_is_read_error(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "monday-pilot-readiness.json").write_text("{bad", encoding="utf-8")
    payload = api_stock_monday_readiness_latest(outputs_dir=outputs)
    assert payload["status"] == "read_error"
    assert payload["available"] is False
    assert payload["critical_failure_count"] == 1


def test_manual_trade_journal_requires_entry_stop_and_target(tmp_path: Path) -> None:
    payload = {
        "symbol": "RKLB",
        "status": "entered-manually",
        "notes": "Pilot entry without full plan should be rejected.",
        "planned_entry": "101.2",
        "planned_stop": "",
        "planned_target": "112.0",
    }
    with pytest.raises(ValueError, match="planned entry, stop, and target"):
        api_stock_signal_journal_entry(payload, db_path=tmp_path / "kquant_us.sqlite3")

    saved = api_stock_signal_journal_entry(
        {
            **payload,
            "planned_stop": "96.8",
        },
        db_path=tmp_path / "kquant_us.sqlite3",
    )
    assert saved["entry"]["status"] == "entered-manually"
    assert saved["entry"]["planned_entry"] == 101.2
    assert saved["entry"]["planned_stop"] == 96.8
    assert saved["entry"]["planned_target"] == 112.0
    assert saved["safety"]["broker_order_wiring_enabled"] is False


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
    assert fixture_latest["counts"]["total"] == 200


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
    assert payload["universe_total"] == 200
    assert payload["counts"]["total"] == 0
    assert payload["signals"] == []
