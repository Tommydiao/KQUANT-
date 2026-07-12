from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from btc_eth_15m.config import AppConfig, load_config
from btc_eth_15m.data import connect, fetch_recent_all, fetch_recent_symbol, market_freshness
from btc_eth_15m.dashboard.broker import BrokerError, broker_for_mode
from btc_eth_15m.dashboard.risk import daily_loss_within_cap, risk_gates
from btc_eth_15m.dashboard.redaction import safe_error_detail
from btc_eth_15m.dashboard.research import latest_research_summary, research_chart, research_runs, research_trades
from btc_eth_15m.dashboard.signals import find_order_draft, replay_order_drafts
from btc_eth_15m.dashboard.state import (
    daily_margin_used,
    daily_loss_used,
    kill_switch_enabled,
    latest_exchange_self_check,
    latest_exchange_self_check_summary,
    latest_exchange_sync,
    latest_exchange_sync_summary,
    latest_events,
    latest_orders,
    open_margin,
    open_positions,
    record_exchange_self_check,
    record_exchange_sync,
    record_event,
    set_kill_switch,
)
from btc_eth_15m.live_market import DEFAULT_LIVE_SYMBOL, safe_live_ticker
from btc_eth_15m.options_lab import (
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
from btc_eth_15m.options_broker import (
    broker_account as options_broker_account,
    broker_positions as options_broker_positions,
    broker_status as options_broker_status,
    cancel_option_paper_order,
    create_option_order_intent,
    submit_option_paper_order,
)
from btc_eth_15m.options_pilot_journal import load_pilot_journal, record_pilot_journal_entry
from btc_eth_15m.options_snapshots import (
    annotate_options_payload,
    attach_chain_snapshot,
    attach_price_history_snapshot,
    attach_scan_snapshot,
    latest_options_chain_payload,
    latest_options_snapshot,
    latest_price_history_payload,
)
from kquant.stock_signals import (
    api_stock_ai_daily_agent,
    api_stock_ai_daily_report_latest,
    api_stock_ai_decision,
    api_stock_ai_review,
    api_stock_ai_review_status,
    api_stock_analyze,
    api_stock_candles,
    api_stock_live_data_health,
    api_stock_live_data_health_latest,
    api_stock_market_data_status,
    api_stock_market_regime,
    api_stock_monday_readiness_latest,
    api_stock_provider_health,
    api_stock_quote,
    api_stock_realtime_snapshot,
    api_stock_search,
    api_stock_signal_journal,
    api_stock_signal_journal_entry,
    api_stock_signals,
    api_stock_signals_latest,
    api_stock_strategy_validation,
    api_stock_universe,
)
from kquant.mstr_cycle import api_mstr_cycle_history, api_mstr_cycle_journal, api_mstr_cycle_journal_entry, api_mstr_cycle_radar


class ConfirmOrderRequest(BaseModel):
    mode: str = Field(default="paper", pattern="^(paper|testnet|live)$")
    leverage: int | None = Field(default=None, ge=1, le=15)


class KillSwitchRequest(BaseModel):
    enabled: bool
    reason: str = ""


class ClosePositionRequest(BaseModel):
    mode: str = Field(default="paper", pattern="^(paper|testnet|live)$")
    reason: str = "manual"


class MarketRefreshRequest(BaseModel):
    lookback_bars: int = Field(default=600, ge=100, le=1500)


class PilotJournalEntryRequest(BaseModel):
    symbol: str = ""
    option_symbol: str
    status: str = Field(default="reviewed", pattern="^(reviewed|skipped|paper-observed)$")
    notes: str = ""
    outcome: str = ""
    run_id: str = ""
    source_type: str = "live"
    profile_id: str = "strict_local_v1"
    universe: str = ""
    alert_level: str = ""
    alert_score: float | None = None
    market_date: str = ""
    stock_kline_checked: bool = False
    option_kline_checked: bool = False
    lens_checked: bool = False
    review_step_complete: bool = False


class MstrCycleJournalEntryRequest(BaseModel):
    run_id: str = ""
    status: str = Field(default="reviewed", pattern="^(reviewed|wait|staged-watch|invalidated)$")
    notes: str = ""
    outcome: str = ""


class StockSignalJournalEntryRequest(BaseModel):
    run_id: str = ""
    symbol: str
    strategy_profile: str = ""
    status: str = Field(default="reviewed", pattern="^(reviewed|watch|skipped|paper-observed|manual-traded|entered-manually|exited-manually|invalidated)$")
    notes: str = ""
    planned_entry: float | None = None
    planned_stop: float | None = None
    planned_target: float | None = None
    outcome: str = ""


class StockAiReviewRequest(BaseModel):
    symbol: str = "NVDA"
    profile: str = "tactical_1w_v1"
    model: str = ""
    model_tier: str = "review"
    signal_payload: dict[str, Any] | None = None
    profile_comparison: list[dict[str, Any]] | None = None
    journal_context_limit: int = 5


class StockAiDailyAgentRequest(BaseModel):
    universe: str = "all"
    limit: int = Field(default=40, ge=5, le=80)
    top_n: int = Field(default=8, ge=3, le=12)
    profiles: list[str] | None = None
    model: str = ""
    model_tier: str = "batch"


class OptionOrderIntentRequest(BaseModel):
    symbol: str = ""
    option_symbol: str
    action: str = "buy_to_open"
    side: str = ""
    order_type: str = "limit"
    quantity: int = Field(default=1, ge=1, le=1)
    limit_price: float | None = Field(default=None, gt=0)
    source_type: str = "fixture"
    requested_by: str = "manual"
    manual_confirmed: bool = False


class OptionPaperOrderRequest(BaseModel):
    intent_id: str
    manual_confirmed: bool = False


def create_app(config_path: str | Path = "config/default.yml") -> FastAPI:
    config = load_config(config_path)
    stock_db_path = Path(config.db_path).parent / "kquant_us.sqlite3"
    app = FastAPI(title="KQUANT US Stock Signal Terminal", version="0.2.0")
    app.state.config = config
    app.state.btc_kline_refresh_cache = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:8001",
            "http://127.0.0.1:8001",
        ],
        allow_origin_regex=r"https://.*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def api_health() -> dict:
        ai_status = api_stock_ai_review_status()
        market_data_status = api_stock_market_data_status(db_path=stock_db_path)
        return {
            "product": "KQUANT US Stock Signal Terminal",
            "status": "online",
            "backend": "fastapi",
            "live_data_enabled": True,
            "market_data": market_data_status,
            "market_data_provider": market_data_status["provider"],
            "longbridge_status": market_data_status["status"],
            "stock_database": str(stock_db_path),
            "ai_review_status": ai_status["status"],
            "ai_models": ai_status["models"],
            "read_only_research": True,
            "fixture_user_visible": False,
            "broker_order_wiring_enabled": False,
            "account_access_enabled": False,
            "order_submission_enabled": False,
        }

    @app.get("/api/status")
    def status(mode: str = Query(default="paper", pattern="^(paper|testnet|live)$")) -> dict:
        broker = broker_for_mode(config, mode)
        broker_status = broker.status()
        sync_summary = latest_exchange_sync_summary(
            config.db_path,
            mode,
            max_age_seconds=config.exchange_sync_max_age_seconds,
        )
        self_check_summary = latest_exchange_self_check_summary(
            config.db_path,
            mode,
            max_age_seconds=config.exchange_self_check_max_age_seconds,
        )
        self_check_ok = _summary_ok(self_check_summary)
        sync_ok = _mode_sync_ok(mode, broker_status, sync_summary)
        budget = _risk_budget(config, mode)
        kill_switch = kill_switch_enabled(config.db_path)
        freshness = market_freshness(config)
        btc_refresh = _legacy_btc_kline_refresh_status()
        legacy_live_market = safe_live_ticker(DEFAULT_LIVE_SYMBOL, timeout=4.0)
        gates = risk_gates(
            config,
            mode=mode,
            kill_switch=kill_switch,
            order_sync_ok=sync_ok,
            position_sync_ok=sync_ok,
            market_data_ok=_market_data_ok(freshness),
            api_error_ok=bool((self_check_ok and sync_ok) or mode == "paper"),
            rate_limit_ok=True,
            open_margin_usdt=budget["open_margin_used_usdt"],
            daily_margin_used_usdt=budget["daily_margin_used_usdt"],
            daily_loss_used_usdt=budget["daily_loss_used_usdt"],
            exchange_self_check_ok=None if mode == "paper" else self_check_ok,
        )
        return {
            "app": "kquant ATM Options Signal Assistant",
            "product_focus": "US ATM options local workbench",
            "mode": mode,
            "symbols": config.symbols,
            "interval": config.interval,
            "exchange": "Alpaca Paper US Options",
            "live_locked": not config.live_enabled,
            "kill_switch_enabled": kill_switch,
            "leverage_range": [config.min_execution_leverage, config.max_execution_leverage],
            "margin_caps": {
                "single_order_usdt": budget["single_order_cap_usdt"],
                "open_usdt": budget["open_margin_cap_usdt"],
                "daily_usdt": budget["daily_margin_cap_usdt"],
                "daily_loss_usdt": budget["daily_loss_cap_usdt"],
                "max_notional_at_15x_usdt": budget["max_notional_at_max_leverage_usdt"],
                "max_notional_at_max_leverage_usdt": budget["max_notional_at_max_leverage_usdt"],
            },
            "risk_budget": budget,
            "broker": options_broker_status(),
            "legacy_crypto": {
                "exchange": "Binance USD-M Futures",
                "broker": broker_status,
                "symbols": config.symbols,
                "interval": config.interval,
                "live_market": legacy_live_market,
                "live_btc_kline_refresh": btc_refresh,
            },
            "last_self_check": self_check_summary,
            "last_sync": sync_summary,
            "market_freshness": freshness,
            "live_market": legacy_live_market,
            "live_btc_kline_refresh": btc_refresh,
            "risk_gates": [gate.to_dict() for gate in gates],
        }

    def _refresh_live_btc_klines() -> dict:
        cached = app.state.btc_kline_refresh_cache
        if cached and time.monotonic() - cached[0] <= 60:
            return cached[1]
        try:
            with connect(config.db_path) as connection:
                result = fetch_recent_symbol(connection, config, DEFAULT_LIVE_SYMBOL, lookback_bars=16)
            payload = {
                "ok": True,
                "symbol": result.symbol,
                "rows": result.rows,
                "start_time": result.start_time,
                "end_time": result.end_time,
                "source": "Binance USD-M Futures public REST",
                "refreshed_at": datetime.now(tz=UTC).isoformat(),
                "error": None,
            }
        except Exception as exc:  # pragma: no cover - network and SQLite defensive path
            payload = {
                "ok": False,
                "symbol": DEFAULT_LIVE_SYMBOL,
                "rows": 0,
                "start_time": None,
                "end_time": None,
                "source": "Binance USD-M Futures public REST",
                "refreshed_at": datetime.now(tz=UTC).isoformat(),
                "error": safe_error_detail(exc),
            }
        app.state.btc_kline_refresh_cache = (time.monotonic(), payload)
        return payload

    def _legacy_btc_kline_refresh_status() -> dict:
        cached = app.state.btc_kline_refresh_cache
        if cached and time.monotonic() - cached[0] <= 60:
            return cached[1]
        return {
            "ok": False,
            "skipped": True,
            "symbol": DEFAULT_LIVE_SYMBOL,
            "rows": 0,
            "start_time": None,
            "end_time": None,
            "source": "Legacy Binance USD-M Futures public REST",
            "refreshed_at": None,
            "error": "Legacy BTC refresh is not triggered by /api/status.",
        }

    @app.get("/api/signals/latest")
    def latest_signals(mode: str = Query(default="paper", pattern="^(paper|testnet|live)$")) -> dict:
        return {
            "mode": mode,
            "signals": _latest_signal_dicts(config, mode),
        }

    @app.get("/api/paper/replay-drafts")
    def paper_replay_drafts(limit: int = Query(default=4, ge=1, le=20)) -> dict:
        return {
            "mode": "paper",
            "drafts": _replay_draft_dicts(config, limit=limit),
        }

    @app.get("/api/positions")
    def positions(mode: str = Query(default="paper", pattern="^(paper|testnet|live)$")) -> dict:
        if mode == "paper":
            rows = [row for row in open_positions(config.db_path) if row["mode"] == mode]
        else:
            rows = broker_for_mode(config, mode).positions()
        return {"mode": mode, "positions": rows}

    @app.get("/api/orders")
    def orders(mode: str = Query(default="paper", pattern="^(paper|testnet|live)$")) -> dict:
        if mode == "paper":
            rows = [row for row in latest_orders(config.db_path) if row["mode"] == mode]
        else:
            rows = broker_for_mode(config, mode).orders()
        return {"mode": mode, "orders": rows}

    @app.get("/api/risk-gates")
    def gates(mode: str = Query(default="paper", pattern="^(paper|testnet|live)$")) -> dict:
        broker_status = broker_for_mode(config, mode).status()
        sync_summary = latest_exchange_sync_summary(
            config.db_path,
            mode,
            max_age_seconds=config.exchange_sync_max_age_seconds,
        )
        self_check_summary = latest_exchange_self_check_summary(
            config.db_path,
            mode,
            max_age_seconds=config.exchange_self_check_max_age_seconds,
        )
        self_check_ok = _summary_ok(self_check_summary)
        sync_ok = _mode_sync_ok(mode, broker_status, sync_summary)
        freshness = market_freshness(config)
        rows = risk_gates(
            config,
            mode=mode,
            kill_switch=kill_switch_enabled(config.db_path),
            order_sync_ok=sync_ok,
            position_sync_ok=sync_ok,
            market_data_ok=_market_data_ok(freshness),
            api_error_ok=bool((self_check_ok and sync_ok) or mode == "paper"),
            rate_limit_ok=True,
            open_margin_usdt=open_margin(config.db_path, mode),
            daily_margin_used_usdt=daily_margin_used(config.db_path, mode),
            daily_loss_used_usdt=daily_loss_used(config.db_path, mode),
            exchange_self_check_ok=None if mode == "paper" else self_check_ok,
        )
        return {"mode": mode, "risk_gates": [row.to_dict() for row in rows]}

    def _exchange_self_check_response(mode: str) -> dict:
        payload = broker_for_mode(config, mode).self_check()
        record_exchange_self_check(config.db_path, payload)
        summary = latest_exchange_self_check_summary(
            config.db_path,
            mode,
            max_age_seconds=config.exchange_self_check_max_age_seconds,
        )
        record_event(
            config.db_path,
            "self-check",
            f"Exchange self-check: {mode}",
            summary or {"mode": mode, "passed": payload.get("passed")},
        )
        payload["last_self_check"] = summary
        return payload

    @app.get("/api/exchange/self-check")
    def exchange_self_check(mode: str = Query(default="testnet", pattern="^(paper|testnet|live)$")) -> dict:
        return {
            "mode": mode,
            "self_check": latest_exchange_self_check(config.db_path, mode),
            "last_self_check": latest_exchange_self_check_summary(
                config.db_path,
                mode,
                max_age_seconds=config.exchange_self_check_max_age_seconds,
            ),
        }

    @app.post("/api/exchange/self-check")
    def post_exchange_self_check(mode: str = Query(default="testnet", pattern="^(paper|testnet|live)$")) -> dict:
        return _exchange_self_check_response(mode)

    def _exchange_sync_response(mode: str) -> dict:
        payload = broker_for_mode(config, mode).sync_snapshot()
        record_exchange_sync(config.db_path, payload)
        summary = latest_exchange_sync_summary(
            config.db_path,
            mode,
            max_age_seconds=config.exchange_sync_max_age_seconds,
        )
        record_event(
            config.db_path,
            "sync",
            f"Exchange sync snapshot: {mode}",
            summary or {"mode": mode, "passed": payload.get("passed")},
        )
        payload["last_sync"] = summary
        return payload

    @app.get("/api/exchange/sync")
    def exchange_sync(mode: str = Query(default="testnet", pattern="^(paper|testnet|live)$")) -> dict:
        return {
            "mode": mode,
            "sync": latest_exchange_sync(config.db_path, mode),
            "last_sync": latest_exchange_sync_summary(
                config.db_path,
                mode,
                max_age_seconds=config.exchange_sync_max_age_seconds,
            ),
        }

    @app.post("/api/exchange/sync")
    def post_exchange_sync(mode: str = Query(default="testnet", pattern="^(paper|testnet|live)$")) -> dict:
        return _exchange_sync_response(mode)

    @app.get("/api/exchange/last-sync")
    def exchange_last_sync(mode: str = Query(default="testnet", pattern="^(paper|testnet|live)$")) -> dict:
        return {"mode": mode, "sync": latest_exchange_sync(config.db_path, mode)}

    @app.get("/api/exchange/last-self-check")
    def exchange_last_self_check(mode: str = Query(default="testnet", pattern="^(paper|testnet|live)$")) -> dict:
        return {"mode": mode, "self_check": latest_exchange_self_check(config.db_path, mode)}

    @app.get("/api/logs")
    def logs(limit: int = Query(default=80, ge=1, le=250)) -> dict:
        return {"events": latest_events(config.db_path, limit=limit)}

    @app.get("/api/research/latest")
    def research_latest() -> dict:
        return latest_research_summary(config)

    @app.get("/api/research/runs")
    def get_research_runs(limit: int = Query(default=20, ge=1, le=100)) -> dict:
        return research_runs(config, limit=limit)

    @app.get("/api/research/trades")
    def get_research_trades(
        run_id: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        try:
            return research_trades(config, run_id=run_id, symbol=symbol, limit=limit, offset=offset)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/research/chart")
    def get_research_chart(
        run_id: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
        trade_id: str | None = Query(default=None),
        pre_bars: int = Query(default=96, ge=12, le=240),
        post_bars: int = Query(default=48, ge=12, le=240),
    ) -> dict:
        try:
            return research_chart(
                config,
                run_id=run_id,
                symbol=symbol,
                trade_id=trade_id,
                pre_bars=pre_bars,
                post_bars=post_bars,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/market/refresh")
    def refresh_market(payload: MarketRefreshRequest) -> dict:
        results = fetch_recent_all(config, lookback_bars=payload.lookback_bars)
        response = {
            "lookback_bars": payload.lookback_bars,
            "results": [result.__dict__ for result in results],
            "market_freshness": market_freshness(config),
        }
        record_event(config.db_path, "market", "Market data refreshed.", response)
        return response

    @app.get("/api/market/live")
    def live_market(symbol: str = Query(default=DEFAULT_LIVE_SYMBOL, pattern="^[A-Z0-9]{3,24}$")) -> dict:
        return safe_live_ticker(symbol, timeout=4.0)

    @app.get("/api/kill-switch")
    def get_kill_switch() -> dict:
        return {"enabled": kill_switch_enabled(config.db_path)}

    @app.post("/api/kill-switch")
    def update_kill_switch(payload: KillSwitchRequest) -> dict:
        enabled = set_kill_switch(config.db_path, payload.enabled, reason=payload.reason)
        return {"enabled": enabled}

    @app.post("/api/orders/{draft_id}/confirm")
    def confirm_order(draft_id: str, payload: ConfirmOrderRequest) -> dict:
        draft = _find_order_draft(config, draft_id, payload.mode)
        if draft is None:
            reason = "Order draft is no longer available."
            record_event(
                config.db_path,
                "order",
                f"Order confirmation rejected: {payload.mode}",
                _order_rejection_summary(draft_id, payload, reason),
            )
            raise HTTPException(status_code=404, detail=reason)
        broker = broker_for_mode(config, payload.mode)
        try:
            result = broker.submit_order_draft(draft, leverage=payload.leverage)
        except BrokerError as exc:
            reason = safe_error_detail(str(exc))
            record_event(
                config.db_path,
                "order",
                f"Order confirmation rejected: {payload.mode}",
                _order_rejection_summary(draft_id, payload, reason, draft=draft),
            )
            raise HTTPException(status_code=400, detail=reason) from exc
        record_event(
            config.db_path,
            "order",
            f"Order confirmation accepted: {payload.mode}",
            _order_confirmation_summary(draft, payload, result),
        )
        return {"mode": payload.mode, "result": result}

    @app.post("/api/positions/{position_id}/close")
    def close_position(position_id: str, payload: ClosePositionRequest) -> dict:
        broker = broker_for_mode(config, payload.mode)
        try:
            result = broker.close_position(position_id, reason=payload.reason)
        except BrokerError as exc:
            reason = safe_error_detail(str(exc))
            record_event(
                config.db_path,
                "position",
                f"Position close rejected: {payload.mode}",
                {
                    "mode": payload.mode,
                    "position_id": position_id,
                    "close_reason": payload.reason,
                    "status": "REJECTED",
                    "rejection_reason": reason,
                },
            )
            raise HTTPException(status_code=400, detail=reason) from exc
        record_event(
            config.db_path,
            "position",
            f"Position close accepted: {payload.mode}",
            _position_close_summary(position_id, payload, result),
        )
        return {"mode": payload.mode, "result": result}

    @app.get("/api/readiness")
    def readiness() -> dict:
        return live_readiness(config)

    @app.get("/api/stocks/universe")
    def stock_universe_endpoint(universe: str = Query(default="default")) -> dict:
        return api_stock_universe(universe=universe, db_path=stock_db_path)

    @app.get("/api/stocks/search")
    def stock_search_endpoint(
        q: str = Query(default=""),
        universe: str = Query(default="all"),
        limit: int = Query(default=24, ge=1, le=50),
    ) -> dict:
        return api_stock_search(q=q, universe=universe, limit=limit)

    @app.get("/api/stocks/candles")
    def stock_candles_endpoint(
        symbol: str = Query(default="SPY"),
        range: str = Query(default="1y"),
        interval: str = Query(default="1d"),
        source: str = Query(default="live"),
    ) -> dict:
        source = _stock_live_only_source(source)
        return api_stock_candles(
            symbol=symbol,
            range_value=range,
            interval=interval,
            source=source,
            db_path=stock_db_path,
        )

    @app.get("/api/stocks/signals")
    def stock_signals_endpoint(
        source: str = Query(default="live"),
        universe: str = Query(default="default"),
        profile: str = Query(default="swing_long_v1"),
        limit: int = Query(default=100, ge=1, le=300),
        layer: str = Query(default=""),
    ) -> dict:
        source = _stock_live_only_source(source)
        return api_stock_signals(
            source=source,
            universe=universe,
            profile=profile,
            db_path=stock_db_path,
            outputs_dir=config.outputs_dir,
            limit=limit,
            layer=layer or None,
        )

    @app.get("/api/stocks/signals/latest")
    def stock_signals_latest_endpoint(
        source: str = Query(default="live"),
        universe: str = Query(default="default"),
        profile: str = Query(default="swing_long_v1"),
    ) -> dict:
        source = _stock_live_only_source(source)
        return api_stock_signals_latest(
            source=source,
            universe=universe,
            profile=profile,
            db_path=stock_db_path,
            outputs_dir=config.outputs_dir,
        )

    @app.get("/api/stocks/provider-health")
    def stock_provider_health_endpoint() -> dict:
        return api_stock_provider_health(db_path=stock_db_path)

    @app.get("/api/stocks/quote")
    def stock_quote_endpoint(symbol: str = Query(default="SPY")) -> dict:
        return api_stock_quote(symbol=symbol, db_path=stock_db_path)

    @app.get("/api/stocks/realtime-snapshot")
    def stock_realtime_snapshot_endpoint(symbol: str = Query(default="SPY")) -> dict:
        return api_stock_realtime_snapshot(symbol=symbol, db_path=stock_db_path)

    @app.get("/api/stocks/market-data/status")
    def stock_market_data_status_endpoint() -> dict:
        return api_stock_market_data_status(db_path=stock_db_path)

    @app.get("/api/stocks/strategy-validation")
    def stock_strategy_validation_endpoint(profile: str = Query(default="")) -> dict:
        return api_stock_strategy_validation(db_path=stock_db_path, profile=profile or None)

    @app.get("/api/stocks/ai-review/status")
    def stock_ai_review_status_endpoint() -> dict:
        return api_stock_ai_review_status()

    @app.get("/api/stocks/analyze")
    def stock_analyze_endpoint(
        symbol: str = Query(default="NVDA"),
        source: str = Query(default="live"),
        profile: str = Query(default="swing_long_v1"),
    ) -> dict:
        source = _stock_live_only_source(source)
        return api_stock_analyze(symbol=symbol, source=source, profile=profile, db_path=stock_db_path)

    @app.get("/api/stocks/market-regime")
    def stock_market_regime_endpoint(source: str = Query(default="live")) -> dict:
        source = _stock_live_only_source(source)
        return api_stock_market_regime(source=source, db_path=stock_db_path)

    @app.get("/api/stocks/signal-journal")
    def stock_signal_journal_endpoint(
        symbol: str = Query(default=""),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        return api_stock_signal_journal(db_path=stock_db_path, symbol=symbol or None, limit=limit)

    @app.post("/api/stocks/signal-journal/entry")
    def stock_signal_journal_entry_endpoint(payload: StockSignalJournalEntryRequest) -> dict:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        return api_stock_signal_journal_entry(data, db_path=stock_db_path)

    @app.post("/api/stocks/ai-review")
    def stock_ai_review_endpoint(payload: StockAiReviewRequest) -> dict:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        return api_stock_ai_review(data, db_path=stock_db_path)

    @app.post("/api/stocks/ai-decision")
    def stock_ai_decision_endpoint(payload: StockAiReviewRequest) -> dict:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        return api_stock_ai_decision(data, db_path=stock_db_path)

    @app.post("/api/stocks/ai-daily-agent")
    def stock_ai_daily_agent_endpoint(payload: StockAiDailyAgentRequest) -> dict:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        return api_stock_ai_daily_agent(data, db_path=stock_db_path, outputs_dir=config.outputs_dir)

    @app.get("/api/stocks/ai-daily-report/latest")
    def stock_ai_daily_report_latest_endpoint() -> dict:
        return api_stock_ai_daily_report_latest(outputs_dir=config.outputs_dir)

    @app.get("/api/stocks/live-data-health")
    def stock_live_data_health_endpoint(
        universes: str = Query(default="default,ai_five_layer"),
        limit: int | None = Query(default=None, ge=1, le=300),
    ) -> dict:
        return api_stock_live_data_health(
            universes=[item.strip() for item in universes.split(",") if item.strip()],
            db_path=stock_db_path,
            outputs_dir=config.outputs_dir,
            limit=limit,
        )

    @app.get("/api/stocks/live-data-health/latest")
    def stock_live_data_health_latest_endpoint() -> dict:
        return api_stock_live_data_health_latest(outputs_dir=config.outputs_dir)

    @app.get("/api/stocks/monday-readiness/latest")
    def stock_monday_readiness_latest_endpoint() -> dict:
        return api_stock_monday_readiness_latest(outputs_dir=config.outputs_dir)

    @app.get("/api/mstr/cycle-radar")
    def mstr_cycle_radar_endpoint(source: str = Query(default="live")) -> dict:
        source = _stock_live_only_source(source)
        return api_mstr_cycle_radar(source=source, db_path=stock_db_path, outputs_dir=config.outputs_dir)

    @app.get("/api/mstr/cycle-radar/history")
    def mstr_cycle_radar_history_endpoint(limit: int = Query(default=30, ge=1, le=200)) -> dict:
        return api_mstr_cycle_history(limit=limit, db_path=stock_db_path)

    @app.get("/api/mstr/cycle-journal")
    def mstr_cycle_journal_endpoint(limit: int = Query(default=50, ge=1, le=200)) -> dict:
        return api_mstr_cycle_journal(db_path=stock_db_path, limit=limit)

    @app.post("/api/mstr/cycle-journal/entry")
    def mstr_cycle_journal_entry_endpoint(payload: MstrCycleJournalEntryRequest) -> dict:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        return api_mstr_cycle_journal_entry(data, db_path=stock_db_path)

    @app.get("/api/options/underlyings")
    def options_underlyings_endpoint(
        symbols: list[str] | None = Query(default=None),
        source: str = Query(default="live"),
        universe: str = Query(default="default"),
    ) -> dict:
        return annotate_options_payload(options_underlyings(symbols=symbols, source=source, universe=universe))

    @app.get("/api/options/daily-candidates")
    def options_daily_candidates_endpoint(
        symbols: list[str] | None = Query(default=None),
        source: str = Query(default="live"),
        universe: str = Query(default="default"),
    ) -> dict:
        payload = options_daily_candidates(symbols=symbols, source=source, universe=universe)
        return attach_scan_snapshot(config.db_path, payload)

    @app.get("/api/options/atm-alerts")
    def options_atm_alerts_endpoint(
        symbols: list[str] | None = Query(default=None),
        source: str = Query(default="live"),
        universe: str = Query(default="default"),
        profile: str = Query(default="strict"),
    ) -> dict:
        payload = options_atm_alerts(
            symbols=symbols,
            outputs_dir=config.outputs_dir,
            db_path=config.db_path,
            source=source,
            universe=universe,
            profile=profile,
        )
        return attach_scan_snapshot(config.db_path, payload)

    @app.get("/api/options/atm-alerts/latest")
    def options_atm_alerts_latest_endpoint(
        universe: str = Query(default="default"),
        profile: str = Query(default="strict"),
    ) -> dict:
        return annotate_options_payload(
            options_atm_alerts_latest(
                outputs_dir=config.outputs_dir,
                db_path=config.db_path,
                universe=universe,
                profile=profile,
            )
        )

    @app.get("/api/options/chain")
    def options_chain_endpoint(
        symbol: str = "SPY",
        expiration: str | None = Query(default=None),
        source: str = Query(default="live"),
    ) -> dict:
        payload = options_chain(symbol, source=source, expiration=expiration)
        return attach_chain_snapshot(config.db_path, payload)

    @app.get("/api/options/chain/latest")
    def options_chain_latest_endpoint(symbol: str = "SPY") -> dict:
        return latest_options_chain_payload(config.db_path, symbol=symbol)

    @app.get("/api/options/contract")
    def options_contract_endpoint(
        option_symbol: str,
        source: str = Query(default="live"),
    ) -> dict:
        return annotate_options_payload(options_contract(option_symbol, source=source))

    @app.get("/api/options/model/surface")
    def options_model_surface_endpoint(
        option_symbol: str,
        source: str = Query(default="live"),
    ) -> dict:
        return annotate_options_payload(options_model_surface(option_symbol, source=source))

    @app.get("/api/options/price-history")
    def options_price_history_endpoint(
        instrument: str = Query(default="underlying", pattern="^(underlying|option)$"),
        symbol: str | None = Query(default=None),
        option_symbol: str | None = Query(default=None),
        range: str = Query(default="5d"),
        interval: str = Query(default="15m"),
        source: str = Query(default="live"),
    ) -> dict:
        return attach_price_history_snapshot(
            config.db_path,
            options_price_history(
                instrument=instrument,
                symbol=symbol,
                option_symbol=option_symbol,
                range_value=range,
                interval=interval,
                source=source,
            ),
        )

    @app.get("/api/options/price-history/latest")
    def options_price_history_latest_endpoint(
        instrument: str = Query(default="underlying", pattern="^(underlying|option)$"),
        symbol: str | None = Query(default=None),
        option_symbol: str | None = Query(default=None),
        range: str = Query(default="5d"),
        interval: str = Query(default="15m"),
    ) -> dict:
        return latest_price_history_payload(
            config.db_path,
            instrument_type=instrument,
            symbol=symbol,
            option_symbol=option_symbol,
            range_value=range,
            interval=interval,
        )

    @app.get("/api/options/eval/latest")
    def options_eval_latest(
        symbols: list[str] | None = Query(default=None),
        source: str = Query(default="live"),
        universe: str = Query(default="default"),
    ) -> dict:
        payload = options_worthiness_report(symbols=symbols, outputs_dir=config.outputs_dir, source=source, universe=universe)
        return {"eval": attach_scan_snapshot(config.db_path, payload)}

    @app.get("/api/options/snapshots/latest")
    def options_snapshots_latest(symbol: str | None = Query(default=None)) -> dict:
        return latest_options_snapshot(config.db_path, symbol=symbol)

    @app.get("/api/options/pilot-journal")
    def options_pilot_journal_endpoint() -> dict:
        return load_pilot_journal(config.outputs_dir, db_path=config.db_path)

    @app.get("/api/options/live-pilot/status")
    def options_live_pilot_status_endpoint() -> dict:
        return options_live_pilot_status(outputs_dir=config.outputs_dir, db_path=config.db_path)

    @app.post("/api/options/pilot-journal/entry")
    def options_pilot_journal_entry_endpoint(payload: PilotJournalEntryRequest) -> dict:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        return record_pilot_journal_entry(config.outputs_dir, data, db_path=config.db_path)

    @app.get("/api/broker/options/status")
    def options_broker_status_endpoint() -> dict:
        return options_broker_status()

    @app.get("/api/broker/options/account")
    def options_broker_account_endpoint() -> dict:
        try:
            return options_broker_account()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=safe_error_detail(str(exc))) from exc

    @app.get("/api/broker/options/positions")
    def options_broker_positions_endpoint() -> dict:
        try:
            return options_broker_positions()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=safe_error_detail(str(exc))) from exc

    @app.post("/api/options/order-intents")
    def options_order_intent_endpoint(payload: OptionOrderIntentRequest) -> dict:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        try:
            return create_option_order_intent(db_path=config.db_path, outputs_dir=config.outputs_dir, payload=data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=safe_error_detail(str(exc))) from exc

    @app.post("/api/options/paper-orders")
    def options_paper_order_endpoint(payload: OptionPaperOrderRequest) -> dict:
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        try:
            return submit_option_paper_order(
                db_path=config.db_path,
                intent_id=str(data.get("intent_id") or ""),
                manual_confirmed=bool(data.get("manual_confirmed")),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=safe_error_detail(str(exc))) from exc

    @app.post("/api/options/paper-orders/{order_id}/cancel")
    def options_paper_order_cancel_endpoint(order_id: str) -> dict:
        try:
            return cancel_option_paper_order(db_path=config.db_path, order_id=order_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=safe_error_detail(str(exc))) from exc

    @app.post("/api/readiness/report")
    def readiness_report() -> dict:
        payload = live_readiness(config)
        path = write_readiness_report(config, payload)
        return {"path": str(path), "readiness": payload}

    @app.get("/stream")
    async def stream(mode: str = Query(default="paper", pattern="^(paper|testnet|live)$")) -> StreamingResponse:
        async def events():
            while True:
                payload = {
                    "status": status(mode),
                    "signals": latest_signals(mode),
                    "positions": positions(mode),
                    "orders": orders(mode),
                }
                yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
                await asyncio.sleep(5)

        return StreamingResponse(events(), media_type="text/event-stream")

    from btc_eth_15m.agent_harness.api import install_agent_routes

    install_agent_routes(app, db_path=config.db_path, outputs_dir=config.outputs_dir)
    mount_frontend(app)
    return app


def _stock_live_only_source(source: str) -> str:
    normalized = str(source or "live").lower()
    if normalized == "fixture":
        raise HTTPException(
            status_code=400,
            detail=(
                "Stock terminal is live-only; fixture stock data is internal "
                "test data and is not available through user-facing APIs."
            ),
        )
    if normalized != "live":
        raise HTTPException(status_code=400, detail="Invalid stock data source. Use source=live.")
    return "live"


def live_readiness(config: AppConfig) -> dict[str, Any]:
    paper_status = broker_for_mode(config, "paper").status()
    testnet_status = broker_for_mode(config, "testnet").status()
    testnet_self_check = latest_exchange_self_check(config.db_path, "testnet")
    testnet_self_check_summary = latest_exchange_self_check_summary(
        config.db_path,
        "testnet",
        max_age_seconds=config.exchange_self_check_max_age_seconds,
    )
    testnet_sync = latest_exchange_sync_summary(
        config.db_path,
        "testnet",
        max_age_seconds=config.exchange_sync_max_age_seconds,
    )
    live_status = broker_for_mode(config, "live").status()
    freshness = market_freshness(config)
    live_budget = _risk_budget(config, "live")
    blockers = []
    kill_active = kill_switch_enabled(config.db_path)
    market_data_ok = _market_data_ok(freshness)
    if kill_active:
        blockers.append("Kill switch is active.")
    if not testnet_self_check_summary or not testnet_self_check_summary.get("passed"):
        blockers.append("Binance Testnet self-check has not passed.")
    if testnet_self_check_summary and not testnet_self_check_summary.get("is_fresh"):
        blockers.append("Binance Testnet self-check is stale.")
    if not testnet_status.get("connected"):
        blockers.append("Binance Testnet credentials/sync are not verified.")
    if not testnet_sync or not testnet_sync.get("passed"):
        blockers.append("Binance Testnet sync snapshot has not passed.")
    if testnet_sync and not testnet_sync.get("is_fresh"):
        blockers.append("Binance Testnet sync snapshot is stale.")
    if not market_data_ok:
        blockers.append("Market data is stale or missing.")
    if not config.live_enabled:
        blockers.append("Live trading is locked in config.")
    if not live_status.get("order_submission_enabled"):
        blockers.append("Live order submission is not wired.")
    if live_budget["open_margin_used_usdt"] > live_budget["open_margin_cap_usdt"]:
        blockers.append("Live open margin cap is exceeded.")
    elif live_budget["open_margin_remaining_usdt"] <= 0:
        blockers.append("Live open margin budget is exhausted.")
    if live_budget["daily_margin_used_usdt"] > live_budget["daily_margin_cap_usdt"]:
        blockers.append("Live daily margin cap is exceeded.")
    elif live_budget["daily_margin_remaining_usdt"] <= 0:
        blockers.append("Live daily margin budget is exhausted.")
    if not daily_loss_within_cap(live_budget["daily_loss_used_usdt"], live_budget["daily_loss_cap_usdt"]):
        blockers.append("Live daily loss cap is exceeded.")
    readiness_checks = _readiness_checks(
        kill_active=kill_active,
        testnet_status=testnet_status,
        testnet_self_check_summary=testnet_self_check_summary,
        testnet_sync=testnet_sync,
        market_data_ok=market_data_ok,
        live_enabled=config.live_enabled,
        live_status=live_status,
        live_budget=live_budget,
    )
    return {
        "ready_for_live": not blockers,
        "blockers": blockers,
        "readiness_checks": readiness_checks,
        "paper": paper_status,
        "testnet": testnet_status,
        "testnet_self_check": testnet_self_check,
        "testnet_self_check_summary": testnet_self_check_summary,
        "testnet_sync": testnet_sync,
        "market_freshness": freshness,
        "live": live_status,
        "live_risk_budget": live_budget,
        "live_rules": {
            "manual_confirmation_required": True,
            "leverage_range": [config.min_execution_leverage, config.max_execution_leverage],
            "single_order_margin_cap_usdt": live_budget["single_order_cap_usdt"],
            "open_margin_cap_usdt": live_budget["open_margin_cap_usdt"],
            "daily_margin_cap_usdt": live_budget["daily_margin_cap_usdt"],
            "daily_loss_cap_usdt": live_budget["daily_loss_cap_usdt"],
            "order_submission_enabled": bool(live_status.get("order_submission_enabled")),
        },
    }


def write_readiness_report(config: AppConfig, payload: dict[str, Any] | None = None) -> Path:
    payload = payload or live_readiness(config)
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    path = config.outputs_dir / f"{stamp}-live-readiness.md"
    blockers = payload.get("blockers", [])
    lines = [
        "# Live Readiness Report",
        "",
        f"- generated_at: {datetime.now(tz=UTC).isoformat()}",
        f"- ready_for_live: {payload.get('ready_for_live')}",
        f"- leverage_range: {payload.get('live_rules', {}).get('leverage_range')}",
        f"- single_order_margin_cap_usdt: {payload.get('live_rules', {}).get('single_order_margin_cap_usdt')}",
        f"- open_margin_cap_usdt: {payload.get('live_rules', {}).get('open_margin_cap_usdt')}",
        f"- daily_margin_cap_usdt: {payload.get('live_rules', {}).get('daily_margin_cap_usdt')}",
        f"- daily_loss_cap_usdt: {payload.get('live_rules', {}).get('daily_loss_cap_usdt')}",
        f"- order_submission_enabled: {payload.get('live_rules', {}).get('order_submission_enabled')}",
        "",
        "## Blockers",
        "",
    ]
    lines.extend([f"- {blocker}" for blocker in blockers] or ["- none"])
    lines.extend(
        [
            "",
            "## Readiness Checks",
            "",
        ]
    )
    for check in payload.get("readiness_checks", []):
        status = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"- {status} {check.get('name')}: {check.get('message')}")
    lines.extend(
        [
            "",
            "## Broker Status",
            "",
            f"- paper: {payload.get('paper', {}).get('message')}",
            f"- testnet: {payload.get('testnet', {}).get('message')}",
            f"- live: {payload.get('live', {}).get('message')}",
            "",
            "## Live Risk Budget",
            "",
        ]
    )
    live_budget = payload.get("live_risk_budget", {})
    lines.extend(
        [
            f"- open_margin_used_usdt: {live_budget.get('open_margin_used_usdt')}",
            f"- open_margin_cap_usdt: {live_budget.get('open_margin_cap_usdt')}",
            f"- open_margin_remaining_usdt: {live_budget.get('open_margin_remaining_usdt')}",
            f"- daily_margin_used_usdt: {live_budget.get('daily_margin_used_usdt')}",
            f"- daily_margin_cap_usdt: {live_budget.get('daily_margin_cap_usdt')}",
            f"- daily_margin_remaining_usdt: {live_budget.get('daily_margin_remaining_usdt')}",
            f"- daily_loss_used_usdt: {live_budget.get('daily_loss_used_usdt')}",
            f"- daily_loss_cap_usdt: {live_budget.get('daily_loss_cap_usdt')}",
            f"- daily_loss_remaining_usdt: {live_budget.get('daily_loss_remaining_usdt')}",
            "",
            "## Market Data",
            "",
        ]
    )
    for item in payload.get("market_freshness", []):
        lines.append(
            f"- {item.get('symbol')}: fresh={item.get('is_fresh')} latest={item.get('latest_open_time_iso')} age_seconds={item.get('age_seconds')}"
        )
    lines.extend(
        [
            "",
            "## Testnet Sync",
            "",
        ]
    )
    sync = payload.get("testnet_sync")
    if sync:
        lines.extend(
            [
                f"- passed: {sync.get('passed')}",
                f"- synced_at: {sync.get('synced_at')}",
                f"- age_seconds: {sync.get('age_seconds')}",
                f"- max_age_seconds: {sync.get('max_age_seconds')}",
                f"- is_fresh: {sync.get('is_fresh')}",
                f"- positions: {sync.get('position_count')}",
                f"- orders: {sync.get('order_count')}",
                f"- failed_checks: {sync.get('failed_checks')}",
                "",
            ]
        )
    else:
        lines.extend(["- none", ""])
    lines.extend(
        [
            "## Testnet Self Check",
            "",
        ]
    )
    self_check_summary = payload.get("testnet_self_check_summary")
    if self_check_summary:
        lines.extend(
            [
                f"- passed: {self_check_summary.get('passed')}",
                f"- checked_at: {self_check_summary.get('checked_at')}",
                f"- age_seconds: {self_check_summary.get('age_seconds')}",
                f"- max_age_seconds: {self_check_summary.get('max_age_seconds')}",
                f"- is_fresh: {self_check_summary.get('is_fresh')}",
                f"- failed_checks: {self_check_summary.get('failed_checks')}",
                "",
            ]
        )
    else:
        lines.extend(["- none", ""])
    for check in (payload.get("testnet_self_check") or {}).get("checks", []):
        status = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"- {status} {check.get('name')}: {check.get('message')}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _mode_sync_ok(
    mode: str,
    broker_status: dict[str, Any],
    sync_summary: dict | None,
) -> bool:
    if mode == "paper":
        return bool(broker_status.get("order_sync_ok") and broker_status.get("position_sync_ok"))
    return _summary_ok(sync_summary)


def _summary_ok(summary: dict | None) -> bool:
    return bool(summary and summary.get("passed") and summary.get("is_fresh"))


def _market_data_ok(freshness: list[dict[str, Any]]) -> bool:
    return bool(freshness) and all(item.get("is_fresh") for item in freshness)


def _readiness_checks(
    *,
    kill_active: bool,
    testnet_status: dict[str, Any],
    testnet_self_check_summary: dict[str, Any] | None,
    testnet_sync: dict[str, Any] | None,
    market_data_ok: bool,
    live_enabled: bool,
    live_status: dict[str, Any],
    live_budget: dict[str, float],
) -> list[dict[str, Any]]:
    open_margin_ok = live_budget["open_margin_remaining_usdt"] > 0
    if live_budget["open_margin_used_usdt"] > live_budget["open_margin_cap_usdt"]:
        open_margin_message = "Live open margin cap is exceeded."
    elif not open_margin_ok:
        open_margin_message = "Live open margin budget is exhausted."
    else:
        open_margin_message = (
            f"Live open margin budget has room: "
            f"{live_budget['open_margin_used_usdt']:.2f} / {live_budget['open_margin_cap_usdt']:.2f} USDT."
        )

    daily_margin_ok = live_budget["daily_margin_remaining_usdt"] > 0
    if live_budget["daily_margin_used_usdt"] > live_budget["daily_margin_cap_usdt"]:
        daily_margin_message = "Live daily margin cap is exceeded."
    elif not daily_margin_ok:
        daily_margin_message = "Live daily margin budget is exhausted."
    else:
        daily_margin_message = (
            f"Live daily margin budget has room: "
            f"{live_budget['daily_margin_used_usdt']:.2f} / {live_budget['daily_margin_cap_usdt']:.2f} USDT."
        )

    daily_loss_ok = daily_loss_within_cap(
        live_budget["daily_loss_used_usdt"],
        live_budget["daily_loss_cap_usdt"],
    )
    daily_loss_message = (
        f"Live daily realized loss {live_budget['daily_loss_used_usdt']:.2f} / "
        f"{live_budget['daily_loss_cap_usdt']:.2f} USDT."
        if daily_loss_ok
        else "Live daily loss cap is exceeded."
    )

    return [
        _readiness_check(
            "kill_switch",
            not kill_active,
            "Kill switch is active." if kill_active else "Kill switch is off.",
        ),
        _readiness_check(
            "testnet_self_check_passed",
            bool(testnet_self_check_summary and testnet_self_check_summary.get("passed")),
            "Binance Testnet self-check has passed."
            if testnet_self_check_summary and testnet_self_check_summary.get("passed")
            else "Binance Testnet self-check has not passed.",
        ),
        _readiness_check(
            "testnet_self_check_fresh",
            bool(testnet_self_check_summary and testnet_self_check_summary.get("is_fresh")),
            "Binance Testnet self-check is fresh."
            if testnet_self_check_summary and testnet_self_check_summary.get("is_fresh")
            else "Binance Testnet self-check is stale or missing.",
        ),
        _readiness_check(
            "testnet_credentials_sync",
            bool(testnet_status.get("connected")),
            "Binance Testnet credentials/sync are verified."
            if testnet_status.get("connected")
            else "Binance Testnet credentials/sync are not verified.",
        ),
        _readiness_check(
            "testnet_sync_passed",
            bool(testnet_sync and testnet_sync.get("passed")),
            "Binance Testnet sync snapshot has passed."
            if testnet_sync and testnet_sync.get("passed")
            else "Binance Testnet sync snapshot has not passed.",
        ),
        _readiness_check(
            "testnet_sync_fresh",
            bool(testnet_sync and testnet_sync.get("is_fresh")),
            "Binance Testnet sync snapshot is fresh."
            if testnet_sync and testnet_sync.get("is_fresh")
            else "Binance Testnet sync snapshot is stale or missing.",
        ),
        _readiness_check(
            "market_data",
            market_data_ok,
            "Market data is fresh for every configured symbol."
            if market_data_ok
            else "Market data is stale or missing.",
        ),
        _readiness_check(
            "live_enabled",
            live_enabled,
            "Live trading is enabled in config." if live_enabled else "Live trading is locked in config.",
        ),
        _readiness_check(
            "live_order_submission",
            bool(live_status.get("order_submission_enabled")),
            "Live order submission is wired."
            if live_status.get("order_submission_enabled")
            else "Live order submission is not wired.",
        ),
        _readiness_check("live_open_margin_budget", open_margin_ok, open_margin_message),
        _readiness_check("live_daily_margin_budget", daily_margin_ok, daily_margin_message),
        _readiness_check("live_daily_loss_cap", daily_loss_ok, daily_loss_message),
    ]


def _readiness_check(name: str, passed: bool, message: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "message": message}


def _risk_budget(config: AppConfig, mode: str) -> dict[str, float]:
    open_used = open_margin(config.db_path, mode)
    daily_margin = daily_margin_used(config.db_path, mode)
    daily_loss = daily_loss_used(config.db_path, mode)
    open_cap = config.live_margin_cap_usdt
    daily_margin_cap = config.live_daily_margin_cap_usdt
    daily_loss_cap = config.initial_equity * config.max_daily_loss
    return {
        "single_order_cap_usdt": round(config.live_single_order_margin_cap_usdt, 2),
        "open_margin_cap_usdt": round(open_cap, 2),
        "daily_margin_cap_usdt": round(daily_margin_cap, 2),
        "daily_loss_cap_usdt": round(daily_loss_cap, 2),
        "open_margin_used_usdt": round(open_used, 2),
        "daily_margin_used_usdt": round(daily_margin, 2),
        "daily_loss_used_usdt": round(daily_loss, 2),
        "open_margin_remaining_usdt": round(max(open_cap - open_used, 0.0), 2),
        "daily_margin_remaining_usdt": round(max(daily_margin_cap - daily_margin, 0.0), 2),
        "daily_loss_remaining_usdt": round(max(daily_loss_cap - daily_loss, 0.0), 2),
        "max_notional_at_max_leverage_usdt": round(open_cap * config.max_execution_leverage, 2),
    }


def _latest_signal_dicts(config: AppConfig, mode: str) -> list[dict[str, Any]]:
    try:
        from btc_eth_15m.dashboard.signals import latest_signal_snapshots

        return [snapshot.to_dict() for snapshot in latest_signal_snapshots(config, mode)]
    except ImportError as exc:
        return _signal_import_fallback(config, str(exc))


def _replay_draft_dicts(config: AppConfig, limit: int) -> list[dict[str, Any]]:
    try:
        return [draft.to_dict() for draft in replay_order_drafts(config, limit=limit)]
    except ImportError:
        return []


def _find_order_draft(config: AppConfig, draft_id: str, mode: str):
    return find_order_draft(config, draft_id, mode)


def _signal_import_fallback(config: AppConfig, reason: str) -> list[dict[str, Any]]:
    freshness = {item["symbol"]: item for item in market_freshness(config)}
    signals = []
    for symbol in config.symbols:
        item = freshness.get(symbol, {})
        signals.append(
            {
                "symbol": symbol,
                "status": "signal_engine_unavailable",
                "bar_time": item.get("latest_open_time_iso"),
                "side": "flat",
                "close": None,
                "atr": None,
                "rsi": None,
                "confidence": 0.0,
                "leverage": None,
                "explanation": {
                    "blockers": [
                        "Signal engine could not load pandas/numpy in this runtime.",
                        reason,
                    ]
                },
                "order_draft": None,
            }
        )
    return signals


def _order_confirmation_summary(draft, payload: ConfirmOrderRequest, result: dict[str, Any]) -> dict[str, Any]:
    requested_leverage = payload.leverage or draft.leverage
    summary: dict[str, Any] = {
        "mode": payload.mode,
        "draft_id": draft.id,
        "symbol": draft.symbol,
        "side": draft.side,
        "requested_leverage": requested_leverage,
        "status": result.get("status"),
    }
    for key in ("order_id", "position_id", "close_order_id"):
        if key in result:
            summary[key] = result[key]
    plan = result.get("order_plan")
    if isinstance(plan, dict):
        summary["order_plan"] = {
            "symbol": plan.get("symbol"),
            "requested_leverage": plan.get("requested_leverage"),
            "rounded_quantity": plan.get("rounded_quantity"),
            "notional_usdt": plan.get("notional_usdt"),
        }
    return summary


def _order_rejection_summary(
    draft_id: str,
    payload: ConfirmOrderRequest,
    reason: str,
    *,
    draft=None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "mode": payload.mode,
        "draft_id": draft_id,
        "requested_leverage": payload.leverage or getattr(draft, "leverage", None),
        "status": "REJECTED",
        "rejection_reason": reason,
    }
    if draft is not None:
        summary.update(
            {
                "symbol": draft.symbol,
                "side": draft.side,
                "draft_status": draft.status,
                "blocked_reasons": list(draft.blocked_reasons),
            }
        )
    return summary


def _position_close_summary(position_id: str, payload: ClosePositionRequest, result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "mode": payload.mode,
        "position_id": position_id,
        "close_reason": payload.reason,
        "status": result.get("status"),
    }
    for key in ("close_order_id", "pnl"):
        if key in result:
            summary[key] = result[key]
    return summary


def mount_frontend(app: FastAPI) -> None:
    root = Path(__file__).resolve().parents[2]
    dist = root / "web" / "dist"
    source_static = Path(__file__).resolve().parent / "static"
    index = dist / "index.html" if (dist / "index.html").exists() else source_static / "index.html"
    if not index.exists():
        return
    assets = dist / "assets"
    if index.parent == dist and assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")
    three_module = root / "web" / "node_modules" / "three" / "build" / "three.module.js"
    lightweight_charts = source_static / "vendor" / "lightweight-charts.standalone.production.js"

    @app.get("/vendor/three.module.js")
    def three_vendor() -> FileResponse:
        if not three_module.exists():
            raise HTTPException(status_code=404, detail="Three.js vendor module is not installed")
        return FileResponse(three_module, media_type="text/javascript")

    @app.get("/vendor/lightweight-charts.standalone.production.js")
    def lightweight_charts_vendor() -> FileResponse:
        if not lightweight_charts.exists():
            raise HTTPException(status_code=404, detail="Lightweight Charts vendor bundle is not installed")
        return FileResponse(lightweight_charts, media_type="text/javascript")

    @app.get("/")
    def frontend_index() -> FileResponse:
        return FileResponse(index)

    @app.get("/{path:path}")
    def frontend_fallback(path: str) -> FileResponse:
        if path.startswith("api/") or path == "stream":
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(index)
