from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from kquant.options_radar import (
    _open_simulation_from_evidence,
    _option_screen,
    american_option_price,
    list_option_manual_outcomes,
    list_option_watchlist,
    list_option_signals,
    option_data_audit,
    option_plan_timeline,
    option_research_report,
    persist_option_quote_evidence,
    record_option_manual_outcome,
    remove_option_watch,
    residual_evidence,
    run_premarket_radar,
    select_atm_contract,
    set_option_watch,
)
from kquant.stock_store import connect


def _daily(start: date, closes: list[float]) -> list[dict]:
    return [
        {
            "open_time": datetime.combine(start + timedelta(days=index), datetime.min.time(), tzinfo=UTC).isoformat(),
            "close": value,
            "bar_state": "closed_candle",
        }
        for index, value in enumerate(closes)
    ]


def test_residual_evidence_uses_market_and_sector_history() -> None:
    start = date(2026, 1, 1)
    market = [100 * math.exp(index * 0.001) for index in range(100)]
    sector = [100 * math.exp(index * 0.0012 + math.sin(index / 7) * 0.002) for index in range(100)]
    target = [100 * math.exp(index * 0.0015 + math.sin(index / 5) * 0.003) for index in range(100)]

    result = residual_evidence(
        _daily(start, target),
        _daily(start, market),
        _daily(start, sector),
        current_target_return=0.05,
        current_market_return=0.001,
        current_sector_return=0.001,
    )

    assert result["status"] == "available"
    assert result["observations"] == 60
    assert result["current_residual_z"] > 1.5
    assert result["training_end"] < date.today().isoformat()


def test_atm_contract_selection_respects_call_and_put_side() -> None:
    rows = [
        {"strike_price": 99, "call_symbol": "C99", "put_symbol": "P99", "is_standard": True},
        {"strike_price": 101, "call_symbol": "C101", "put_symbol": "P101", "is_standard": True},
    ]
    assert select_atm_contract(rows, spot=100, direction="CALL")["contract_symbol"] == "C99"
    assert select_atm_contract(rows, spot=100, direction="PUT")["contract_symbol"] == "P101"


def test_american_pricer_handles_early_exercise_and_intrinsic_at_expiry() -> None:
    call = american_option_price(
        spot=100,
        strike=100,
        years_to_expiry=30 / 365.25,
        volatility=0.3,
        risk_free_rate=0.04,
        dividend_yield=0.01,
        direction="CALL",
    )
    put = american_option_price(
        spot=90,
        strike=100,
        years_to_expiry=30 / 365.25,
        volatility=0.3,
        risk_free_rate=0.04,
        dividend_yield=0.01,
        direction="PUT",
    )
    expiry = american_option_price(
        spot=105,
        strike=100,
        years_to_expiry=0,
        volatility=0.3,
        risk_free_rate=0.04,
        dividend_yield=0.01,
        direction="CALL",
    )
    assert call > 0
    assert put >= 10
    assert expiry == 5


def test_option_screen_rejects_receipt_only_bbo_and_0dte_wide_spread() -> None:
    decision = datetime(2026, 9, 14, 13, 40, tzinfo=UTC)
    snapshot = {
        "provider_status": "available",
        "depth_status": "available",
        "is_standard": True,
        "strict_fill_eligible": False,
        "bbo_received_at": (decision + timedelta(seconds=2)).isoformat(),
        "delta": 0.5,
        "spread_pct": 4.0,
        "bid_size": 2,
        "ask_size": 2,
        "open_interest": 1000,
        "volume": 200,
        "quote_time_meaning": "latest_trade_time_not_bbo_time",
    }
    blockers, warnings = _option_screen(snapshot, "INTRADAY_0DTE", decision)
    assert any("native event timestamp" in item for item in blockers)
    assert any("3.0%" in item for item in blockers)
    assert warnings


def test_option_screen_rejects_predecision_and_clock_conflicted_native_bbo() -> None:
    decision = datetime(2026, 9, 14, 13, 40, tzinfo=UTC)
    snapshot = {
        "provider_status": "available",
        "depth_status": "available",
        "is_standard": True,
        "strict_fill_eligible": True,
        "bbo_time_source": "native_event_time",
        "bbo_event_time": (decision - timedelta(seconds=1)).isoformat(),
        "bbo_received_at": (decision + timedelta(seconds=30)).isoformat(),
        "delta": 0.5,
        "spread_pct": 2.0,
        "bid_size": 2,
        "ask_size": 2,
        "open_interest": 1000,
        "volume": 200,
    }
    blockers, _ = _option_screen(snapshot, "INTRADAY_0DTE", decision)
    assert any("native BBO event" in item for item in blockers)
    assert any("within 15 seconds" in item for item in blockers)


def test_quote_evidence_downgrades_untrusted_native_flag(tmp_path: Path) -> None:
    db = tmp_path / "stock.sqlite3"
    decision = datetime(2026, 9, 14, 13, 40, tzinfo=UTC)
    plan_id = _seed_plan(db, decision)
    evidence = persist_option_quote_evidence(
        db,
        plan_id,
        {
            "contract_symbol": "SPY-C",
            "source": "test_adapter",
            "bbo_received_at": (decision + timedelta(seconds=31)).isoformat(),
            "bbo_event_time": (decision + timedelta(seconds=1)).isoformat(),
            "bbo_time_source": "native_event_time",
            "bid": 1.0,
            "ask": 1.1,
            "strict_fill_eligible": True,
        },
        "entry",
    )
    assert evidence["strict_fill_eligible"] is False
    assert evidence["execution_quality"] == "RECEIPT_TIME_ONLY"


def test_premarket_radar_persists_observation_only_when_opra_and_events_are_missing(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "stock.sqlite3"
    current = datetime(2026, 9, 14, 12, 30, tzinfo=UTC)
    start = date(2026, 5, 1)
    base = [100 * math.exp(index * 0.001 + math.sin(index / 5) * 0.002) for index in range(100)]
    target = [100 * math.exp(index * 0.0015 + math.sin(index / 4) * 0.003) for index in range(100)]
    daily = {
        "AAPL": {"source_type": "longbridge_candles", "candles": _daily(start, target)},
        "SPY": {"source_type": "longbridge_candles", "candles": _daily(start, base)},
        "XLK": {"source_type": "longbridge_candles", "candles": _daily(start, base)},
    }
    quotes = {
        "AAPL": {"provider_status": "available", "last": 110, "pre_market": {"last": 110, "previous_close": 100, "turnover": 1_000_000, "event_time": current.isoformat()}},
        "SPY": {"provider_status": "available", "last": 100.1, "pre_market": {"last": 100.1, "previous_close": 100, "turnover": 2_000_000, "event_time": current.isoformat()}},
        "XLK": {"provider_status": "available", "last": 100.1, "pre_market": {"last": 100.1, "previous_close": 100, "turnover": 500_000, "event_time": current.isoformat()}},
    }
    monkeypatch.setattr("kquant.options_radar.market_schedule", lambda *args, **kwargs: {"is_trading_day": True, "regular_open_utc": "2026-09-14T13:30:00+00:00", "regular_close_utc": "2026-09-14T20:00:00+00:00"})
    monkeypatch.setattr("kquant.options_radar.option_market_status", lambda: {"status": "available", "opra_status": "not_detected"})
    monkeypatch.setattr("kquant.options_radar.corporate_event_context", lambda *args, **kwargs: {"status": "not_ingested", "trade_eligible": False})
    monkeypatch.setattr("kquant.options_radar.option_expiries", lambda symbol: {"expiries": ["2026-09-14", "2026-09-25", "2026-10-02"]})
    monkeypatch.setattr("kquant.options_radar.option_chain", lambda symbol, expiry: {"contracts": [{"strike_price": 109, "call_symbol": f"{symbol}-C", "put_symbol": f"{symbol}-P", "is_standard": True}]})

    report = run_premarket_radar(db, now=current, daily_payloads=daily, quote_payloads=quotes)

    assert report["opportunities"]
    opportunity = next(item for item in report["opportunities"] if item["symbol"] == "AAPL")
    assert opportunity["status"] == "PREMARKET_WATCH"
    assert any("OPRA" in item for item in opportunity["blockers"])
    assert all(plan["state"] == "REFERENCE_ONLY" for plan in opportunity["plans"])
    assert all(plan["reference_quote"] == {} for plan in opportunity["plans"])


def _seed_plan(db: Path, decision: datetime) -> str:
    with connect(db) as conn:
        conn.execute(
            "INSERT INTO option_radar_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-1", "2026-09-14", "premarket", "v1", "[]", "hash", "completed", "available", decision.isoformat(), "{}", decision.isoformat()),
        )
        conn.execute(
            """
            INSERT INTO option_opportunities VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            ("opp-1", "run-1", "SPY", "test", "CALL", "INTRADAY", 1, 90, "CONFIRMED", decision.isoformat(), decision.isoformat(), decision.isoformat(), "available", "observational", "v1", "state", "{}", "[]", "[]", decision.isoformat(), decision.isoformat()),
        )
        conn.execute(
            """
            INSERT INTO option_plans VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            ("plan-1", "opp-1", "INTRADAY_0DTE", "SPY-C", "2026-09-14", 0, 100, "CALL", "CONFIRMED", "standard", decision.isoformat(), decision.isoformat(), decision.isoformat(), decision.isoformat(), decision.isoformat(), 0, 0, "{}", "{}", "[]", decision.isoformat(), decision.isoformat()),
        )
        conn.commit()
    return "plan-1"


def test_simulation_requires_strict_post_decision_quote(tmp_path: Path) -> None:
    db = tmp_path / "stock.sqlite3"
    decision = datetime(2026, 9, 14, 13, 40, tzinfo=UTC)
    plan_id = _seed_plan(db, decision)
    receipt_only = persist_option_quote_evidence(
        db,
        plan_id,
        {"contract_symbol": "SPY-C", "source": "longbridge", "bbo_received_at": (decision + timedelta(seconds=1)).isoformat(), "bid": 1.0, "ask": 1.1, "strict_fill_eligible": False},
        "entry",
    )
    with pytest.raises(ValueError, match="strict post-decision"):
        _open_simulation_from_evidence(db, plan_id, receipt_only["quote_evidence_id"])

    strict = persist_option_quote_evidence(
        db,
        plan_id,
        {"contract_symbol": "SPY-C", "source": "test_native_bbo", "bbo_received_at": (decision + timedelta(seconds=2)).isoformat(), "bbo_event_time": (decision + timedelta(seconds=1)).isoformat(), "bbo_time_source": "native_event_time", "bid": 1.0, "ask": 1.1, "bid_size": 2, "ask_size": 2, "strict_fill_eligible": True},
        "entry",
    )
    opened = _open_simulation_from_evidence(db, plan_id, strict["quote_evidence_id"])
    assert opened["status"] == "open"
    assert opened["entry_price"] == pytest.approx(1.1)


def test_simulation_cannot_open_a_reference_only_plan(tmp_path: Path) -> None:
    db = tmp_path / "stock.sqlite3"
    decision = datetime(2026, 9, 14, 13, 40, tzinfo=UTC)
    plan_id = _seed_plan(db, decision)
    with connect(db) as conn:
        conn.execute("UPDATE option_plans SET state='REFERENCE_ONLY' WHERE plan_id=?", (plan_id,))
        conn.commit()
    evidence = persist_option_quote_evidence(
        db,
        plan_id,
        {
            "contract_symbol": "SPY-C",
            "source": "test_native_bbo",
            "bbo_received_at": (decision + timedelta(seconds=2)).isoformat(),
            "bbo_event_time": (decision + timedelta(seconds=1)).isoformat(),
            "bbo_time_source": "native_event_time",
            "bid": 1.0,
            "ask": 1.1,
            "strict_fill_eligible": True,
        },
        "entry",
    )
    with pytest.raises(ValueError, match="intraday-confirmed"):
        _open_simulation_from_evidence(db, plan_id, evidence["quote_evidence_id"])


def test_observation_can_transition_to_open_after_strict_quote(tmp_path: Path) -> None:
    db = tmp_path / "stock.sqlite3"
    decision = datetime(2026, 9, 14, 13, 40, tzinfo=UTC)
    plan_id = _seed_plan(db, decision)
    with connect(db) as conn:
        conn.execute(
            """
            INSERT INTO option_outcomes(
              outcome_id, plan_id, status, contracts, multiplier, outcome_reason,
              censor_reason, execution_policy_id, created_at, updated_at
            ) VALUES (?, ?, 'not_entered', 1, 100, 'observation_registered',
                      'awaiting_strict_post_decision_bbo', ?, ?, ?)
            """,
            ("outcome-observed", plan_id, "option_simulation_ask_bid_v1.0.0", decision.isoformat(), decision.isoformat()),
        )
        conn.commit()
    evidence = persist_option_quote_evidence(
        db,
        plan_id,
        {
            "contract_symbol": "SPY-C",
            "source": "test_native_bbo",
            "bbo_received_at": (decision + timedelta(seconds=2)).isoformat(),
            "bbo_event_time": (decision + timedelta(seconds=1)).isoformat(),
            "bbo_time_source": "native_event_time",
            "bid": 1.0,
            "ask": 1.1,
            "bid_size": 2,
            "ask_size": 2,
            "strict_fill_eligible": True,
        },
        "entry",
    )
    opened = _open_simulation_from_evidence(db, plan_id, evidence["quote_evidence_id"])
    assert opened["outcome_id"] == "outcome-observed"
    assert opened["status"] == "open"
    assert opened["censor_reason"] == ""


def test_current_signals_only_include_latest_premarket_run(tmp_path: Path) -> None:
    db = tmp_path / "stock.sqlite3"
    first = datetime(2026, 9, 14, 12, 30, tzinfo=UTC)
    second = first + timedelta(minutes=1)
    _seed_plan(db, first)
    with connect(db) as conn:
        conn.execute(
            "INSERT INTO option_radar_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-2", "2026-09-14", "premarket", "v1", "[]", "hash-2", "completed", "available", second.isoformat(), "{}", second.isoformat()),
        )
        conn.execute(
            """
            INSERT INTO option_opportunities VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            ("opp-2", "run-2", "AAPL", "test", "CALL", "INTRADAY", 1, 91, "PREMARKET_WATCH", second.isoformat(), second.isoformat(), second.isoformat(), "available", "observational", "v1", "state-2", "{}", "[]", "[]", second.isoformat(), second.isoformat()),
        )
        conn.commit()

    result = list_option_signals(db, current_only=True, now=second)

    assert [item["opportunity_id"] for item in result["opportunities"]] == ["opp-2"]


def test_data_audit_and_report_do_not_claim_option_performance(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "stock.sqlite3"
    with connect(db):
        pass
    monkeypatch.setattr("kquant.options_radar.option_market_status", lambda: {"opra_status": "not_detected"})
    monkeypatch.setattr("kquant.options_radar.corporate_event_context", lambda *args, **kwargs: {"status": "not_ingested"})
    monkeypatch.setattr("kquant.options_radar.api_stock_quote", lambda *args, **kwargs: {"provider_status": "unavailable"})
    audit = option_data_audit(db)
    report = option_research_report(db)
    assert audit["strict_simulated_fill_ready"] is False
    assert audit["counts"]["option_outcomes"] == 0
    assert report["performance_status"] == "PERFORMANCE_UNPROVEN"
    assert report["legacy_option_paper_excluded"] is True


def test_watchlist_and_timeline_are_incremental_and_recoverable(tmp_path: Path) -> None:
    db = tmp_path / "stock.sqlite3"
    decision = datetime(2026, 9, 14, 13, 40, tzinfo=UTC)
    plan_id = _seed_plan(db, decision)

    watched = set_option_watch(db, plan_id, notes="开盘后复核")
    assert watched["status"] == "active"
    assert list_option_watchlist(db)["count"] == 1
    assert set_option_watch(db, plan_id, notes="更新备注")["notes"] == "更新备注"

    timeline = option_plan_timeline(db, plan_id)
    assert timeline["append_only"] is True
    assert [event["event_type"] for event in timeline["events"]].count("watch_started") == 2

    removed = remove_option_watch(db, plan_id)
    assert removed["changed"] is True
    assert list_option_watchlist(db)["count"] == 0
    assert list_option_watchlist(db, active_only=False)["items"][0]["status"] == "removed"
    assert option_plan_timeline(db, plan_id)["events"][-1]["event_type"] == "watch_stopped"


def test_manual_outcome_keeps_missing_fees_out_of_net_performance(tmp_path: Path) -> None:
    db = tmp_path / "stock.sqlite3"
    decision = datetime(2026, 9, 14, 13, 40, tzinfo=UTC)
    plan_id = _seed_plan(db, decision)

    result = record_option_manual_outcome(
        db,
        {
            "plan_id": plan_id,
            "status": "completed",
            "entry_time": decision.isoformat(),
            "entry_price": 1.0,
            "exit_time": (decision + timedelta(hours=1)).isoformat(),
            "exit_price": 1.5,
            "contracts": 1,
            "notes": "人工填写",
        },
    )

    assert result["source"] == "user_reported"
    assert result["gross_pnl"] == pytest.approx(50.0)
    assert result["fees"] is None
    assert result["net_pnl"] is None
    assert list_option_manual_outcomes(db)["simulation_results_excluded"] is True
    assert option_plan_timeline(db, plan_id)["events"][-1]["event_type"] == "manual_outcome_updated"
