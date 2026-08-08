from __future__ import annotations

import os
import json
import queue
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kquant.config import KquantConfig, load_config
from kquant.data_coverage import api_stock_data_coverage
from kquant.database_migrations import migration_readiness
from kquant.decision_ledger import (
    create_decision_ledger_entry,
    list_decision_ledger,
    record_manual_trade_journal,
    weekly_personal_review,
)
from kquant.manual_workflow import calculate_manual_position_size
from kquant.forward_pilot import (
    activate_forward_pilot,
    close_forward_day,
    enter_paper_position,
    exit_paper_position,
    forward_pilot_summary,
    initialize_paper_simulation,
    paper_simulation_summary,
    prepare_forward_pilot,
    record_forward_day,
    record_forward_outcome,
)
from kquant.operations import (
    dispatch_personal_notification,
    operational_health,
    queue_notification,
    recent_notifications,
)
from kquant.options_expression import (
    OPTION_EXPRESSION_VERSION,
    option_candidates,
    option_chain,
    option_contract_snapshot,
    option_expiries,
    option_market_status,
    list_option_paper_observations,
    record_option_paper_observation,
)
from kquant.realtime_instructions import (
    TRIGGER_POLICY_VERSION,
    AlertEventHub,
    acknowledge_alert,
    list_alerts,
    list_instructions,
)
from kquant.realtime_supervisor import RealtimeSupervisor
from kquant.security import ApiSecurityMiddleware, LocalSessionAuth, SecuritySettings
from kquant.production_readiness import (
    evaluate_go_no_go,
    manual_live_readiness_check,
    write_personal_production_launch_report,
)
from kquant.today_workbench import build_today_workbench
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
    api_stock_market_data_self_check,
    api_stock_market_data_status,
    api_stock_market_regime,
    api_stock_monday_readiness_latest,
    api_stock_provider_health,
    api_stock_quote,
    api_stock_realtime_snapshot,
    api_stock_research_chat,
    api_stock_search,
    api_stock_signal_journal,
    api_stock_signal_journal_entry,
    api_stock_signals,
    api_stock_signals_latest,
    api_stock_universe,
)
from kquant.validation_service import (
    api_strategy_validation_action,
    api_strategy_validation_latest,
    run_strategy_validation,
)


API_CONTRACT_VERSION = "kquant-api-2026-08-08-realtime-options-v1"


FORBIDDEN_ROUTE_TOKENS = (
    "/account",
    "/broker",
    "/orders",
    "/positions",
    "/binance",
    "/btc",
    "/eth",
)


class StockSignalJournalEntryRequest(BaseModel):
    run_id: str = ""
    symbol: str
    strategy_profile: str = ""
    status: str = Field(
        default="reviewed",
        pattern="^(reviewed|watch|skipped|paper-observed|manual-traded|entered-manually|exited-manually|invalidated)$",
    )
    notes: str = ""
    planned_entry: float | None = None
    planned_stop: float | None = None
    planned_target: float | None = None
    outcome: str = ""


class StockAiRequest(BaseModel):
    symbol: str = "NVDA"
    profile: str = "tactical_1w_v1"
    model: str = ""
    model_tier: str = "review"
    signal_payload: dict[str, Any] | None = None
    profile_comparison: list[dict[str, Any]] | None = None
    journal_context_limit: int = 5
    force_regenerate: bool = False


class StockResearchChatRequest(BaseModel):
    symbol: str = "NVDA"
    profile: str = "tactical_1w_v1"
    question: str
    model: str = ""
    language: str = "zh"
    signal_payload: dict[str, Any] | None = None
    ai_decision: dict[str, Any] | None = None
    research_context: dict[str, Any] | None = None
    messages: list[dict[str, Any]] | None = None


class StockAiDailyAgentRequest(BaseModel):
    universe: str = "all"
    limit: int = Field(default=40, ge=5, le=80)
    top_n: int = Field(default=8, ge=3, le=12)
    profiles: list[str] | None = None
    model: str = ""
    model_tier: str = "batch"


class StrategyValidationRunRequest(BaseModel):
    profiles: list[str] = Field(default_factory=lambda: ["tactical_1w_v1", "high_beta_growth_v1"])
    start: str = ""
    end: str = ""
    universe: str = "default"
    symbols: list[str] | None = None


class ManualPositionPlanRequest(BaseModel):
    account_value: float = Field(gt=0)
    risk_per_trade_pct: float = Field(gt=0, le=100)
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    max_total_risk_pct: float = Field(gt=0, le=100)
    currently_open_risk: float = Field(default=0, ge=0)
    max_position_pct: float = Field(default=25, gt=0, le=100)


class DecisionLedgerRequest(BaseModel):
    signal_id: str
    symbol: str
    strategy_version: str = "legacy_unversioned"
    data_snapshot: dict[str, Any] = Field(default_factory=dict)
    system_decision: dict[str, Any] = Field(default_factory=dict)
    user_decision: str = "observe"
    entry_plan: dict[str, Any] = Field(default_factory=dict)
    veto_status: str = "unknown"
    final_execution: str = "not_executed"
    outcome: str = "pending"
    outcome_r: float | None = None
    error_owner: str = "unclassified"
    lesson: str = ""


class ManualTradeJournalRequest(BaseModel):
    ledger_id: str
    symbol: str
    stage: str = "pre_trade"
    reason: str = ""
    plan_followed: bool | None = None
    actual_entry: float | None = None
    actual_exit: float | None = None
    result_r: float | None = None
    emotion: str = ""
    screenshot_ref: str = ""
    notes: str = ""
    review: str = ""


class NotificationRequest(BaseModel):
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    channel: str = "web"


class ForwardPilotPrepareRequest(BaseModel):
    strategy_version: str
    universe_name: str = "default"
    universe_snapshot_hash: str
    start_date: str
    mode: str = "paper_observation"


class ForwardPilotDayRequest(BaseModel):
    market_date: str
    preflight: dict[str, Any] = Field(default_factory=dict)
    scan: dict[str, Any] = Field(default_factory=dict)
    phase: str = "daily_observation"


class ForwardOutcomeRequest(BaseModel):
    outcome_status: str
    entry_price: float | None = None
    exit_price: float | None = None
    realized_r: float | None = None
    notes: str = ""
    deviations: dict[str, Any] = Field(default_factory=dict)


class ForwardDayCloseRequest(BaseModel):
    close_notes: dict[str, Any] = Field(default_factory=dict)


class PaperAccountRequest(BaseModel):
    initial_cash: float = Field(gt=0)
    risk_per_trade_pct: float = Field(default=0.25, gt=0, le=0.25)
    max_positions: int = Field(default=3, ge=1, le=10)
    max_daily_risk_pct: float = Field(default=0.75, gt=0, le=2)


class PaperEntryRequest(BaseModel):
    candidate_id: str
    entry_time: str
    entry_price: float = Field(gt=0)
    stop_price: float = Field(gt=0)
    target_price: float = Field(gt=0)
    entry_plan_high: float | None = None
    notes: str = ""


class PaperExitRequest(BaseModel):
    position_id: str
    exit_time: str
    exit_price: float = Field(gt=0)
    notes: str = ""


class ManualLiveReadinessRequest(BaseModel):
    instrument_type: str
    risk_per_trade_pct: float = Field(gt=0, le=0.25)
    manual_trades_today: int = Field(default=0, ge=0)
    data_clean: bool
    hard_veto_active: bool
    is_leveraged_etf: bool = False
    is_option: bool = False


class LocalLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=512)


class OptionPaperObservationRequest(BaseModel):
    action: str = Field(default="open", pattern="^(open|close)$")
    candidate_id: str = ""
    observation_id: str = ""
    underlying_price: float = Field(gt=0)
    exit_price: float | None = Field(default=None, ge=0)
    exit_reason: str = ""
    notes: str = ""


def _live_only(source: str) -> str:
    if source != "live":
        raise HTTPException(status_code=400, detail="The stock terminal accepts live/reference data only.")
    return source


def stock_live_only_source(query: dict[str, list[str]]) -> str:
    values = query.get("source") or ["live"]
    source = str(values[0] if values else "live")
    if source != "live":
        raise ValueError("The stock terminal is live-only; fixture data is not user-selectable.")
    return source


def route_safety_report(app: FastAPI) -> dict[str, Any]:
    paths = sorted({getattr(route, "path", "") for route in app.routes if getattr(route, "path", "")})
    forbidden = [path for path in paths if any(token in path.lower() for token in FORBIDDEN_ROUTE_TOKENS)]
    return {
        "status": "pass" if not forbidden else "fail",
        "registered_route_count": len(paths),
        "forbidden_routes": forbidden,
        "market_data_only": True,
        "account_access_enabled": False,
        "trade_context_enabled": False,
        "order_submission_enabled": False,
        "options_research_enabled": True,
        "options_order_submission_enabled": False,
    }


def create_app(
    config_path: str | Path = "config/default.yml",
    *,
    config: KquantConfig | None = None,
) -> FastAPI:
    settings = config or load_config(config_path)
    security = SecuritySettings.from_environment()
    session_auth = LocalSessionAuth(security)
    started_at_utc = datetime.now(timezone.utc).isoformat()
    alert_hub = AlertEventHub()
    supervisor = RealtimeSupervisor(settings.db_path, settings.outputs_dir, alert_hub)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        supervisor.start()
        try:
            yield
        finally:
            supervisor.stop()

    app = FastAPI(title=settings.product, version="0.10.0-realtime-options", lifespan=lifespan)
    app.state.settings = settings
    app.state.security = security
    app.state.session_auth = session_auth
    app.state.alert_hub = alert_hub
    app.state.realtime_supervisor = supervisor
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(security.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(ApiSecurityMiddleware, settings=security, session_auth=session_auth)

    @app.get("/api/auth/session")
    def auth_session(request: Request) -> dict[str, Any]:
        session = session_auth.session_from_request(request)
        if not security.local_login_enabled:
            return {"authentication_required": False, "authenticated": True, "mode": "not_required"}
        if not security.local_login_ready:
            return {"authentication_required": True, "authenticated": False, "mode": "setup_required"}
        return {
            "authentication_required": True,
            "authenticated": bool(session),
            "mode": "local_email_password",
            "expires_at": session.get("exp") if session else None,
        }

    @app.post("/api/auth/login")
    def auth_login(payload: LocalLoginRequest, request: Request) -> JSONResponse:
        if not security.local_login_enabled:
            raise HTTPException(status_code=409, detail="Local login is not enabled.")
        if not security.local_login_ready:
            raise HTTPException(status_code=503, detail="Local login is enabled but not configured.")
        client = request.client.host if request.client else "unknown"
        if not session_auth.login_allowed(client):
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
        if not session_auth.verify_login(payload.email, payload.password):
            session_auth.record_login_failure(client)
            raise HTTPException(status_code=401, detail="Incorrect email or password.")
        session_auth.clear_login_failures(client)
        response = JSONResponse({"authenticated": True, "expires_in_seconds": security.session_max_seconds})
        session_auth.set_session_cookie(response, session_auth.issue_session())
        return response

    @app.post("/api/auth/logout")
    def auth_logout() -> JSONResponse:
        response = JSONResponse({"authenticated": False})
        session_auth.clear_session_cookie(response)
        return response

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        market_data = api_stock_market_data_status(db_path=settings.db_path)
        safety = route_safety_report(app)
        return {
            "product": settings.product,
            "status": "online" if safety["status"] == "pass" else "unsafe",
            "backend": "kquant.dashboard.fastapi",
            "runtime": {
                "api_contract_version": API_CONTRACT_VERSION,
                "started_at_utc": started_at_utc,
                "auth_routes_version": "local_email_password_v1",
                "static_assets_version": "realtime-options-v1",
                "database_schema_version": "realtime-options-v1",
                "strategy_version": "swing_long_v1.1.0",
                "trigger_policy_version": TRIGGER_POLICY_VERSION,
                "options_expression_version": OPTION_EXPRESSION_VERSION,
            },
            "stock_database": str(settings.db_path),
            "market_data": market_data,
            "ai": api_stock_ai_review_status(),
            "security": security.report(),
            "safety": safety,
            "supervisor": supervisor.status(),
            "read_only_research": True,
        }

    @app.get("/api/instructions/current")
    def current_instructions(limit: int = Query(default=30, ge=1, le=100)) -> dict[str, Any]:
        payload = list_instructions(settings.db_path, current_only=True, limit=limit)
        payload["count"] = len(payload["instructions"])
        return payload

    @app.get("/api/instructions/history")
    def instruction_history(symbol: str = "", limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        payload = list_instructions(settings.db_path, symbol=symbol or None, limit=limit)
        payload["count"] = len(payload["instructions"])
        return payload

    @app.get("/api/alerts")
    def alerts(unread_only: bool = False, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        payload = list_alerts(settings.db_path, unread_only=unread_only, limit=limit)
        payload["count"] = len(payload["alerts"])
        return payload

    @app.get("/api/alerts/stream")
    def alerts_stream() -> StreamingResponse:
        channel = alert_hub.subscribe()

        def events():
            try:
                yield "retry: 3000\n\n"
                while True:
                    try:
                        event = channel.get(timeout=15)
                        yield f"event: alert\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    except queue.Empty:
                        yield ": keepalive\n\n"
            finally:
                alert_hub.unsubscribe(channel)

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/alerts/{alert_id}/ack")
    def alert_ack(alert_id: str) -> dict[str, Any]:
        try:
            return acknowledge_alert(settings.db_path, alert_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runtime/supervisor-status")
    def supervisor_status() -> dict[str, Any]:
        return supervisor.status()

    @app.get("/api/options/status")
    def options_status() -> dict[str, Any]:
        return option_market_status()

    @app.get("/api/options/expiries")
    def options_expiries(symbol: str = "NVDA") -> dict[str, Any]:
        try:
            return option_expiries(symbol)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/options/chain")
    def options_chain(symbol: str, expiry: str) -> dict[str, Any]:
        try:
            return option_chain(symbol, expiry)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/options/candidates")
    def options_candidates(symbol: str = "NVDA") -> dict[str, Any]:
        coverage = api_stock_data_coverage(settings.db_path)
        event_status = str((coverage.get("event_calendar") or {}).get("status") or "missing")
        try:
            return option_candidates(settings.db_path, symbol, event_calendar_ready=event_status == "available")
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/options/contracts/{contract}")
    def option_contract(contract: str) -> dict[str, Any]:
        try:
            return option_contract_snapshot(contract, settings.db_path)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/options/paper-observations")
    def option_paper(payload: OptionPaperObservationRequest) -> dict[str, Any]:
        try:
            return record_option_paper_observation(settings.db_path, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/options/paper-observations")
    def option_paper_list(status: str = "", limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        return list_option_paper_observations(settings.db_path, status=status, limit=limit)

    @app.get("/api/stocks/universe")
    def universe(universe: str = Query(default="default")) -> dict[str, Any]:
        return api_stock_universe(universe=universe, db_path=settings.db_path)

    @app.get("/api/stocks/search")
    def search(q: str = "", universe: str = "all", limit: int = Query(default=24, ge=1, le=50)) -> dict[str, Any]:
        return api_stock_search(q=q, universe=universe, limit=limit)

    @app.get("/api/stocks/candles")
    def candles(symbol: str = "SPY", range: str = "1y", interval: str = "1d", source: str = "live") -> dict[str, Any]:
        return api_stock_candles(symbol, range, interval, _live_only(source), settings.db_path)

    @app.get("/api/stocks/signals")
    def signals(
        source: str = "live",
        universe: str = "default",
        profile: str = "swing_long_v1",
        limit: int = Query(default=100, ge=1, le=300),
        layer: str = "",
    ) -> dict[str, Any]:
        return api_stock_signals(
            source=_live_only(source), universe=universe, profile=profile,
            db_path=settings.db_path, outputs_dir=settings.outputs_dir,
            limit=limit, layer=layer or None,
        )

    @app.get("/api/stocks/signals/latest")
    def signals_latest(source: str = "live", universe: str = "default", profile: str = "swing_long_v1") -> dict[str, Any]:
        return api_stock_signals_latest(
            source=_live_only(source), universe=universe, profile=profile,
            db_path=settings.db_path, outputs_dir=settings.outputs_dir,
        )

    @app.get("/api/stocks/daily-candidates")
    def daily_candidates(source: str = "live", universe: str = "default", profile: str = "swing_long_v1") -> dict[str, Any]:
        payload = api_stock_signals_latest(
            source=_live_only(source), universe=universe, profile=profile,
            db_path=settings.db_path, outputs_dir=settings.outputs_dir,
        )
        return {
            "run_id": payload.get("run_id"),
            "daily_candidates": payload.get("daily_candidates") or {
                "buy_setups": [], "watch": [], "excluded_count": 0,
                "read_only_research": True, "no_order_submission": True,
            },
        }

    @app.get("/api/stocks/provider-health")
    def provider_health() -> dict[str, Any]:
        return api_stock_provider_health(settings.db_path)

    @app.get("/api/stocks/quote")
    def quote(symbol: str = "SPY") -> dict[str, Any]:
        return api_stock_quote(symbol, settings.db_path)

    @app.get("/api/stocks/realtime-snapshot")
    def realtime_snapshot(symbol: str = "SPY") -> dict[str, Any]:
        return api_stock_realtime_snapshot(symbol, settings.db_path)

    @app.get("/api/stocks/market-data/status")
    def market_data_status() -> dict[str, Any]:
        return api_stock_market_data_status(settings.db_path)

    @app.get("/api/stocks/data-coverage")
    def data_coverage() -> dict[str, Any]:
        return api_stock_data_coverage(settings.db_path)

    @app.get("/api/stocks/market-data/self-check")
    def market_data_self_check(symbol: str = "SPY") -> dict[str, Any]:
        payload = api_stock_market_data_self_check(symbol, settings.db_path)
        payload["route_safety"] = route_safety_report(app)
        payload["ai_key"] = "configured" if os.getenv("OPENAI_API_KEY") else "missing"
        payload["credential_values_exposed"] = False
        if payload["route_safety"]["status"] != "pass":
            payload["status"] = "blocked"
        return payload

    @app.get("/api/stocks/ai-review/status")
    def ai_status() -> dict[str, Any]:
        return api_stock_ai_review_status()

    @app.get("/api/stocks/analyze")
    def analyze(symbol: str = "NVDA", source: str = "live", profile: str = "swing_long_v1") -> dict[str, Any]:
        return api_stock_analyze(symbol, _live_only(source), profile, settings.db_path)

    @app.get("/api/stocks/{symbol}/factor-snapshot")
    def factor_snapshot(symbol: str, profile: str = "swing_long_v1") -> dict[str, Any]:
        analysis = api_stock_analyze(symbol, "live", profile, settings.db_path)
        return {
            "symbol": analysis["symbol"],
            "strategy_version": analysis["strategy_version"],
            "factor_snapshot": analysis["factor_snapshot"],
            "decision_evidence": analysis["decision_evidence"],
            "read_only_research": True,
        }

    @app.get("/api/stocks/market-regime")
    def market_regime(source: str = "live") -> dict[str, Any]:
        return api_stock_market_regime(_live_only(source), settings.db_path)

    @app.get("/api/stocks/signal-journal")
    def journal(symbol: str = "", limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        return api_stock_signal_journal(settings.db_path, symbol or None, limit)

    @app.post("/api/stocks/manual-position-plan")
    def manual_position_plan(payload: ManualPositionPlanRequest) -> dict[str, Any]:
        return calculate_manual_position_size(**payload.model_dump())

    @app.get("/api/stocks/decision-ledger")
    def decision_ledger(symbol: str = "", limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        return list_decision_ledger(settings.db_path, symbol=symbol or None, limit=limit)

    @app.post("/api/stocks/decision-ledger")
    def decision_ledger_entry(payload: DecisionLedgerRequest) -> dict[str, Any]:
        return create_decision_ledger_entry(payload.model_dump(), settings.db_path)

    @app.post("/api/stocks/manual-trade-journal")
    def manual_trade_journal(payload: ManualTradeJournalRequest) -> dict[str, Any]:
        return record_manual_trade_journal(payload.model_dump(), settings.db_path)

    @app.get("/api/stocks/weekly-review")
    def weekly_review(week_start: str = "") -> dict[str, Any]:
        return weekly_personal_review(settings.db_path, week_start=week_start or None)

    @app.get("/api/stocks/production-readiness")
    def production_readiness(strategy_version: str = "swing_long_v1.1.0") -> dict[str, Any]:
        validation = api_strategy_validation_latest(settings.db_path)
        return evaluate_go_no_go(
            db_path=settings.db_path,
            strategy_version=strategy_version,
            historical_validation=validation.get("evidence", {}).get("historical_policy_replay", {}),
            security_report={**security.report(), "order_submission_enabled": False},
        )

    @app.post("/api/stocks/manual-live-readiness")
    def manual_live_readiness(payload: ManualLiveReadinessRequest, strategy_version: str = "swing_long_v1.1.0") -> dict[str, Any]:
        go_no_go = production_readiness(strategy_version)
        return manual_live_readiness_check(go_no_go=go_no_go, **payload.model_dump())

    @app.post("/api/stocks/production-launch-report")
    def production_launch_report(strategy_version: str = "swing_long_v1.1.0") -> dict[str, Any]:
        report = production_readiness(strategy_version)
        root = Path(__file__).resolve().parents[2]
        return {"report": report, "artifact": write_personal_production_launch_report(report, root / "docs" / "personal_production_launch_report.md")}

    @app.get("/api/stocks/today-workbench")
    def today_workbench(universe: str = "default", profile: str = "swing_long_v1") -> dict[str, Any]:
        run = api_stock_signals_latest(
            source="live", universe=universe, profile=profile,
            db_path=settings.db_path, outputs_dir=settings.outputs_dir,
        )
        validation = api_strategy_validation_latest(settings.db_path)
        readiness = evaluate_go_no_go(
            db_path=settings.db_path,
            strategy_version=str(run.get("strategy_version") or "swing_long_v1.1.0"),
            historical_validation=validation.get("evidence", {}).get("historical_policy_replay", {}),
            security_report={**security.report(), "order_submission_enabled": False},
        )
        return build_today_workbench(
            run=run,
            market_regime=run.get("market_regime"),
            market_data=api_stock_market_data_status(settings.db_path),
            ai_status=api_stock_ai_review_status(),
            operational_health=operational_health(settings.db_path),
            weekly_review=weekly_personal_review(settings.db_path),
            production_readiness=readiness,
        )

    @app.post("/api/stocks/forward-pilot")
    def forward_pilot_prepare(payload: ForwardPilotPrepareRequest) -> dict[str, Any]:
        return prepare_forward_pilot(db_path=settings.db_path, **payload.model_dump())

    @app.post("/api/stocks/forward-pilot/{session_id}/activate")
    def forward_pilot_activate(session_id: str) -> dict[str, Any]:
        return activate_forward_pilot(settings.db_path, session_id)

    @app.get("/api/stocks/forward-pilot/{session_id}")
    def forward_pilot_status(session_id: str) -> dict[str, Any]:
        return forward_pilot_summary(settings.db_path, session_id)

    @app.post("/api/stocks/forward-pilot/{session_id}/days")
    def forward_pilot_day(session_id: str, payload: ForwardPilotDayRequest) -> dict[str, Any]:
        return record_forward_day(db_path=settings.db_path, session_id=session_id, **payload.model_dump())

    @app.post("/api/stocks/forward-pilot/{session_id}/days/{market_date}/close")
    def forward_pilot_day_close(session_id: str, market_date: str, payload: ForwardDayCloseRequest) -> dict[str, Any]:
        return close_forward_day(db_path=settings.db_path, session_id=session_id, market_date=market_date, **payload.model_dump())

    @app.post("/api/stocks/forward-pilot/candidates/{candidate_id}/outcome")
    def forward_pilot_outcome(candidate_id: str, payload: ForwardOutcomeRequest) -> dict[str, Any]:
        return record_forward_outcome(db_path=settings.db_path, candidate_id=candidate_id, **payload.model_dump())

    @app.post("/api/stocks/paper-simulation/{session_id}")
    def paper_simulation_initialize(session_id: str, payload: PaperAccountRequest) -> dict[str, Any]:
        return initialize_paper_simulation(db_path=settings.db_path, session_id=session_id, **payload.model_dump())

    @app.get("/api/stocks/paper-simulation/{account_id}")
    def paper_simulation_status(account_id: str) -> dict[str, Any]:
        return paper_simulation_summary(settings.db_path, account_id)

    @app.post("/api/stocks/paper-simulation/{account_id}/entries")
    def paper_simulation_entry(account_id: str, payload: PaperEntryRequest) -> dict[str, Any]:
        return enter_paper_position(db_path=settings.db_path, account_id=account_id, **payload.model_dump())

    @app.post("/api/stocks/paper-simulation/{account_id}/exits")
    def paper_simulation_exit(account_id: str, payload: PaperExitRequest) -> dict[str, Any]:
        return exit_paper_position(db_path=settings.db_path, account_id=account_id, **payload.model_dump())

    @app.get("/api/stocks/operations/health")
    def operations_health() -> dict[str, Any]:
        return operational_health(settings.db_path)

    @app.get("/api/stocks/database/migration-readiness")
    def database_readiness() -> dict[str, Any]:
        return migration_readiness(default_path=settings.db_path)

    @app.get("/api/stocks/notifications")
    def notifications(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        return recent_notifications(settings.db_path, limit=limit)

    @app.post("/api/stocks/notifications")
    def notification(payload: NotificationRequest) -> dict[str, Any]:
        return queue_notification(settings.db_path, event_type=payload.event_type, payload=payload.payload, channel=payload.channel)

    @app.post("/api/stocks/notifications/{event_id}/dispatch")
    def notification_dispatch(event_id: str) -> dict[str, Any]:
        return dispatch_personal_notification(settings.db_path, event_id=event_id)

    @app.post("/api/stocks/signal-journal/entry")
    def journal_entry(payload: StockSignalJournalEntryRequest) -> dict[str, Any]:
        return api_stock_signal_journal_entry(payload.model_dump(), settings.db_path)

    @app.post("/api/stocks/ai-review")
    def ai_review(payload: StockAiRequest) -> dict[str, Any]:
        return api_stock_ai_review(payload.model_dump(), settings.db_path)

    @app.post("/api/stocks/ai-decision")
    def ai_decision(payload: StockAiRequest) -> dict[str, Any]:
        return api_stock_ai_decision(payload.model_dump(), settings.db_path)

    @app.post("/api/stocks/research-chat")
    def research_chat(payload: StockResearchChatRequest) -> dict[str, Any]:
        return api_stock_research_chat(payload.model_dump(), settings.db_path)

    @app.post("/api/stocks/ai-daily-agent")
    def ai_daily(payload: StockAiDailyAgentRequest) -> dict[str, Any]:
        return api_stock_ai_daily_agent(payload.model_dump(), settings.db_path, settings.outputs_dir)

    @app.get("/api/stocks/ai-daily-report/latest")
    def ai_daily_latest() -> dict[str, Any]:
        return api_stock_ai_daily_report_latest(settings.outputs_dir)

    @app.get("/api/stocks/live-data-health")
    def live_data_health(universes: str = "default,ai_five_layer", limit: int | None = None) -> dict[str, Any]:
        return api_stock_live_data_health(
            [item.strip() for item in universes.split(",") if item.strip()],
            settings.db_path, settings.outputs_dir, limit,
        )

    @app.get("/api/stocks/live-data-health/latest")
    def live_data_health_latest() -> dict[str, Any]:
        return api_stock_live_data_health_latest(settings.outputs_dir)

    @app.get("/api/stocks/monday-readiness/latest")
    def readiness_latest() -> dict[str, Any]:
        return api_stock_monday_readiness_latest(settings.outputs_dir)

    @app.post("/api/stocks/strategy-validation/runs")
    def validation_run(payload: StrategyValidationRunRequest) -> dict[str, Any]:
        return run_strategy_validation(
            profiles=payload.profiles, start=payload.start or None, end=payload.end or None,
            universe=payload.universe, symbols=payload.symbols,
            db_path=settings.db_path, outputs_dir=settings.outputs_dir,
        )

    @app.get("/api/stocks/strategy-validation/latest")
    def validation_latest(profile: str = "") -> dict[str, Any]:
        return api_strategy_validation_latest(settings.db_path, profile or None)

    @app.get("/api/stocks/strategy-validation/actions/{action}")
    def validation_action(action: str, profile: str = "") -> dict[str, Any]:
        return api_strategy_validation_action(action, settings.db_path, profile or None)

    mount_frontend(app)
    return app


def mount_frontend(app: FastAPI) -> None:
    root = Path(__file__).resolve().parents[2]
    dist = root / "web" / "dist"
    index = dist / "index.html"
    if not index.exists():
        return
    assets = dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def frontend_index() -> FileResponse:
        return FileResponse(index)

    @app.get("/{path:path}")
    def frontend_fallback(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        if path in {"manifest.webmanifest", "service-worker.js", "kquant-mark.svg"}:
            static_file = dist / path
            if static_file.exists():
                return FileResponse(static_file)
        return FileResponse(index)
