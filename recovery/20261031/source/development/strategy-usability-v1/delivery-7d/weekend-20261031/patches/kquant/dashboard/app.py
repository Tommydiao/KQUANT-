from __future__ import annotations

import os
import asyncio
import json
import queue
import sqlite3
from urllib.parse import urlencode
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kquant.config import KquantConfig, load_config
from kquant.policy_availability import PolicyConfigUnavailable
from kquant.data_coverage import api_stock_data_coverage
from kquant.capital_rotation import capital_rotation_detail, latest_capital_rotation
from kquant.quant_dataset import DatasetIntegrityError, list_model_artifacts, model_artifact_detail
from kquant.stock_quant import MODEL_0_VERSION, latest_stock_quant_run, stock_quant_ranking, stock_quant_symbol_detail
from kquant.stock_quant_validation import (
    latest_stock_quant_validation,
    run_stock_quant_validation,
    stock_quant_validation_detail,
)
from kquant.stock_quant_readiness import stock_quant_validation_readiness
from kquant.shadow_observation import latest_shadow_observation
from kquant.v2_overview import build_v2_overview
from kquant.theme_prediction import latest_theme_prediction, theme_prediction_detail
from kquant.leadership import latest_leadership, theme_leaders
from kquant.theme_taxonomy import latest_theme_taxonomy, taxonomy_audit, theme_detail
from kquant.data_snapshots import read_data_snapshot
from kquant.database_migrations import apply_sqlite_schema_migrations, migration_readiness
from kquant.universe_registry import ensure_stock_universe_catalog
from kquant.decision_ledger import (
    create_decision_ledger_entry,
    list_decision_ledger,
    record_manual_trade_journal,
    weekly_personal_review,
)
from kquant.manual_workflow import calculate_manual_position_size
from kquant.early_trend_service import early_trend_snapshot
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
    option_contract_snapshots,
    option_expiries,
    option_market_status,
    list_option_paper_observations,
    record_option_paper_observation,
)
from kquant.stock_watchlist import (
    add_stock_watchlist_member,
    daily_option_scope_report,
    ensure_stock_watchlist_seed,
    list_stock_watchlist_groups,
    list_stock_watchlist_members,
    record_stock_watchlist_capability,
    refresh_stock_watchlist_identities,
    remove_stock_watchlist_member,
    stock_watchlist_quotes,
    watchlist_audit,
)
from kquant.options_radar import (
    OPTION_RADAR_POLICY_VERSION,
    latest_premarket_report,
    list_option_manual_outcomes,
    list_option_signals,
    list_option_simulations,
    list_option_watchlist,
    option_data_audit,
    option_plan_timeline,
    option_radar_status,
    option_research_report,
    option_signal_detail,
    record_option_manual_outcome,
    record_option_simulation,
    remove_option_watch,
    set_option_watch,
)
from kquant.options_radar_supervisor import OptionRadarSupervisor
from kquant.option_calendar_source import source_events, source_observations
from kquant.option_event_coverage import option_event_context
from kquant.options_profiles import load_options_profiles, options_foundation_status
from kquant.options_research_workbench import DEFAULT_RESEARCH_DB, workbench_payload
from kquant.options_review_r1 import review_r1_payload
from kquant.options_review_r2 import review_r2_payload
from kquant.options_review_r3 import review_r3_payload
from kquant.options_review_r4 import review_r4_payload
from kquant.options_review_r5 import review_r5_payload
from kquant.options_review_r6 import review_r6_payload
from kquant.options_forward_paper import DEFAULT_DB_PATH as OPTIONS_FORWARD_DB, DEFAULT_RUN_ID as OPTIONS_FORWARD_RUN_ID, forward_status
from kquant.options_signal_copilot import (
    DEFAULT_STORE_PATH as OPTIONS_COPILOT_DB,
    confirm_paper_intent,
    copilot_status,
    list_signals as list_copilot_signals,
    paper_state as copilot_paper_state,
    signal_detail as copilot_signal_detail,
    update_notification_state as update_copilot_notification_state,
    update_signal_state as update_copilot_signal_state,
)
from kquant.options_cbrm_research import review_payload as cbrm_review_payload
from kquant.options_astra import astra_status
from kquant.options_full_watch import (
    check_full_watch_options,
    full_watch_status,
    run_full_watch_scan,
)
from kquant.options_model_router import model_router_status
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
from kquant.web_push import (
    deliver_web_push,
    notification_preferences,
    public_key as web_push_public_key,
    subscribe as web_push_subscribe,
    unsubscribe as web_push_unsubscribe,
    update_notification_preferences,
    web_push_status,
)


API_CONTRACT_VERSION = "kquant-api-2026-09-14-options-tracking-v2"


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


class StockQuantValidationRequest(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=160)
    random_seed: int = 20260817


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


class WebPushSubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=10, max_length=4096)
    keys: dict[str, str]


class WebPushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(min_length=10, max_length=4096)


class NotificationPreferencesRequest(BaseModel):
    web_push_enabled: bool = True
    quiet_start: str = Field(default="22:30", pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    quiet_end: str = Field(default="08:00", pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    timezone: str = "Asia/Shanghai"
    daily_routine_limit: int = Field(default=5, ge=1, le=20)


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


class OptionRadarSimulationRequest(BaseModel):
    action: str = Field(default="observe", pattern="^(observe|open|close)$")
    plan_id: str = Field(min_length=1, max_length=160)
    fees: float | None = Field(default=None, ge=0)
    reason: str = ""


class OptionWatchRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=160)
    notes: str = Field(default="", max_length=1000)


class OptionManualOutcomeRequest(BaseModel):
    plan_id: str = Field(min_length=1, max_length=160)
    status: str = Field(default="observing", pattern="^(not_entered|observing|open|completed|censored)$")
    entry_time: str | None = None
    entry_price: float | None = Field(default=None, gt=0)
    exit_time: str | None = None
    exit_price: float | None = Field(default=None, ge=0)
    contracts: int | None = Field(default=None, ge=1)
    multiplier: float = Field(default=100, gt=0)
    fees: float | None = Field(default=None, ge=0)
    reason: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=2000)


class StockWatchlistMemberRequest(BaseModel):
    group_id: str = Field(min_length=1, max_length=80)
    symbol: str = Field(min_length=1, max_length=32)


class CopilotPaperConfirmationRequest(BaseModel):
    signal_id: str = Field(min_length=1, max_length=160)
    action: str = Field(pattern="^(ENTRY|EXIT)$")
    confirmation_id: str = Field(min_length=8, max_length=160)
    confirmation_text: str = Field(min_length=1, max_length=80)
    contract_id: str = Field(min_length=1, max_length=80)
    contract_multiplier: int = Field(gt=0, le=100000)
    underlying: str = Field(min_length=1, max_length=32)
    theme_id: str = Field(min_length=1, max_length=80)
    limit_price: float = Field(gt=0)
    requested_quantity: int = Field(default=1, ge=1, le=100)


class CopilotNotificationStateRequest(BaseModel):
    state: str = Field(pattern="^(ACKNOWLEDGED|SNOOZED|DISMISSED|REVOKED)$")
    snoozed_until: str | None = None
    reason: str = Field(default="OWNER_ACTION", min_length=1, max_length=160)


class CopilotSignalStateRequest(BaseModel):
    state: str = Field(pattern="^(DRAFT|WATCH|TRIGGERED|REVIEW_READY|INVALIDATED|EXPIRED|REJECTED)$")
    reason: str = Field(min_length=1, max_length=160)


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
    research_store: Path | None = None,
    research_clock=None,
    manual_store: Path | None = None,
    minute_status_store: Path | None = None,
) -> FastAPI:
    settings = config or load_config(config_path)
    apply_sqlite_schema_migrations(settings.db_path)
    from ..main_store_runtime import prepare_read_concurrency
    main_store_concurrency = prepare_read_concurrency(settings.db_path)
    ensure_stock_universe_catalog(settings.db_path)
    ensure_stock_watchlist_seed(settings.db_path)
    security = SecuritySettings.from_environment()
    session_auth = LocalSessionAuth(security)
    started_at_utc = datetime.now(timezone.utc).isoformat()
    alert_hub = AlertEventHub()
    supervisor = RealtimeSupervisor(settings.db_path, settings.outputs_dir, alert_hub)
    option_radar_supervisor = OptionRadarSupervisor(settings.db_path, alert_hub)
    from ..status_snapshot import StatusSnapshot, SnapshotUnavailable
    one_minute_snapshot = StatusSnapshot()
    from ..research_http_snapshots import ResearchHttpSnapshots

    def load_research_projection(strategy, kind, worker):
        from ..status_worker import load_current_cards, load_opening_trend
        from ..options_scope_observation import apply as observe_scope
        from ..options_opening_trend_summary import compact_status
        extra = {"trend_path": research_store} if research_store is not None else {}
        if research_clock is not None:
            extra["now"] = research_clock()
        payload = (load_current_cards(settings.db_path, research_strategy=strategy, **extra) if kind == "current"
                   else load_opening_trend(settings.db_path, compact=True, research_strategy=strategy, **extra))
        observe_scope(payload, worker, now=research_clock() if research_clock else datetime.now(timezone.utc))
        if kind == "compact":
            payload["worker"] = {**worker.get(strategy, {}), "event_collection": worker.get("event_sources", {}),
                "runtime_health": worker.get("runtime_health"), "observed_at": worker.get("observed_at"),
                **{key: worker.get(key) for key in ("state", "research_ready", "first_loop_at", "loop_count",
                    "stage", "last_cycle_at", "error_id", "error_type", "failed_stage")},
                **{key: worker.get(key, {"status": "NOT_STARTED"}) for key in
                   ("price_action_sources", "source_request_budget", "source_call", "clock_measurement")}}
            payload["reference_collection"] = worker.get("trend_reference", {})
            payload["registered_items"] = worker.get("registered_items", []) if worker.get("session") == payload.get("session") else []
            payload = compact_status(payload)
        elif payload.get("scope_observation", {}).get("state") == "UNCONFIRMED":
            payload["evaluations"] = []
        return payload

    def load_service_observation():
        from ..options_service_observation import observe, MANIFEST
        root = os.getenv("KQUANT_OPTION_FOUNDATION_ROOT")
        return {**observe(Path(root) / "services.json" if root else MANIFEST), "enforced": bool(root)}

    def research_policy_availability(strategy):
        from .. import options_opening_momentum, options_opening_trend
        module = options_opening_momentum if strategy == "opening_momentum" else options_opening_trend
        # Background-only file check; HTTP reads consume its memory projection.
        return {"enabled": module.CONFIG.is_file(), "reason": "POLICY_CONFIG_MISSING"}

    research_snapshots = ResearchHttpSnapshots(
        lambda: option_radar_supervisor.one_minute_worker_status(nonblocking=True),
        load_research_projection, load_service_observation,
        on_complete=lambda strategy: alert_hub.publish({"type": "options_one_minute_snapshot_ready", "research_strategy": strategy}),
        on_tick=(lambda day: one_minute_snapshot.refresh(day, load_one_minute_status))
            if research_store is None or minute_status_store is not None else None,
        clock=research_clock, strategy_availability=research_policy_availability)

    def invalidate_research_status(event):
        if event.get("research_strategy") in {"opening_trend", "opening_momentum"} and event.get("type") in {
                "options_one_minute_progress", "options_one_minute_eligibility", "options_one_minute_ai"}:
            research_snapshots.invalidate(event["research_strategy"])

    alert_hub.add_listener(invalidate_research_status)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        supervisor.start()
        option_radar_supervisor.start()
        research_snapshots.start()
        async def sample_loop():
            loop = asyncio.get_running_loop()
            from anyio.to_thread import current_default_thread_limiter
            limiter = current_default_thread_limiter()
            while True:
                before = loop.time()
                await asyncio.sleep(.25)
                lag = max(0, loop.time() - before - .25)
                previous = research_snapshots.event_loop
                research_snapshots.event_loop = {"state": "OBSERVED", "samples": previous["samples"] + 1,
                    "checked_at": datetime.now(UTC).isoformat(), "lag_seconds": lag,
                    "max_lag_seconds": max(lag, previous.get("max_lag_seconds", 0))}
                statistics = limiter.statistics()
                research_snapshots.event_loop["anyio_thread_pool"] = {
                    "borrowed_tokens": statistics.borrowed_tokens, "total_tokens": statistics.total_tokens,
                    "tasks_waiting": statistics.tasks_waiting}
        loop_monitor = asyncio.create_task(sample_loop())
        try:
            yield
        finally:
            loop_monitor.cancel()
            try:
                await loop_monitor
            except asyncio.CancelledError:
                pass
            alert_hub.remove_listener(invalidate_research_status)
            one_minute_snapshot.close()
            research_snapshots.close()
            option_radar_supervisor.stop()
            supervisor.stop()

    app = FastAPI(title=settings.product, version="0.13.0-options-tracking", lifespan=lifespan)
    app.state.settings = settings
    app.state.main_store_concurrency = main_store_concurrency
    app.state.security = security
    app.state.session_auth = session_auth
    app.state.alert_hub = alert_hub
    app.state.realtime_supervisor = supervisor
    app.state.option_radar_supervisor = option_radar_supervisor
    app.state.research_http_snapshots = research_snapshots
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

    @app.get("/api/health/live")
    async def health_live() -> dict[str, Any]:
        # No filesystem, process enumeration, SDK, DB, or worker lock on this path.
        return {
            "status": "online", "backend": "kquant.dashboard.fastapi",
            "api_contract_version": API_CONTRACT_VERSION,
            "started_at_utc": started_at_utc, "read_only_research": True,
            "backend_release": os.getenv("KQUANT_BACKEND_RELEASE_ID", "UNVERIFIED_WORKING_TREE"),
            "backend_manifest_sha256": os.getenv("KQUANT_BACKEND_MANIFEST_SHA256"),
            "market_data_checked": False, "order_submission_enabled": False,
            "service_observation": research_snapshots.health(),
        }

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        market_data = api_stock_market_data_status(db_path=settings.db_path)
        safety = route_safety_report(app)
        migration = migration_readiness(default_path=settings.db_path)
        return {
            "product": settings.product,
            "status": "online" if safety["status"] == "pass" else "unsafe",
            "backend": "kquant.dashboard.fastapi",
            "runtime": {
                "api_contract_version": API_CONTRACT_VERSION,
                "started_at_utc": started_at_utc,
                "auth_routes_version": "local_email_password_v1",
                "static_assets_version": "v2-versioned-assets-v2",
                "database_schema_version": migration["migration"].get("schema_version", 0),
                "database_schema_fingerprint": migration["migration"].get("schema_fingerprint", ""),
                "strategy_version": "swing_long_v1.1.0",
                "early_trend_strategy_version": "early_trend_3_15d_v1.0.0",
                "trigger_policy_version": TRIGGER_POLICY_VERSION,
                "options_expression_version": OPTION_EXPRESSION_VERSION,
                "options_radar_policy_version": OPTION_RADAR_POLICY_VERSION,
                "stock_quant_model_version": MODEL_0_VERSION,
            },
            "stock_database": str(settings.db_path),
            "database_migration": migration["migration"],
            "market_data": market_data,
            "ai": api_stock_ai_review_status(),
            "security": security.report(),
            "safety": safety,
            "supervisor": supervisor.status(),
            "option_radar_supervisor": option_radar_supervisor.status(),
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
    async def alerts_stream(request: Request) -> StreamingResponse:
        async def events():
            channel = alert_hub.subscribe()
            loop = asyncio.get_running_loop()
            next_keepalive = loop.time() + 15
            try:
                yield "retry: 3000\n\n"
                while not await request.is_disconnected():
                    try:
                        event = channel.get_nowait()
                        yield f"event: alert\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                        next_keepalive = loop.time() + 15
                    except queue.Empty:
                        if loop.time() >= next_keepalive:
                            yield ": keepalive\n\n"
                            next_keepalive = loop.time() + 15
                        # Do not retain a worker thread while a disconnected
                        # client's synchronous queue waits for its keepalive.
                        await asyncio.sleep(.05)
            finally:
                alert_hub.unsubscribe(channel)

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/alerts/{alert_id}/ack")
    def alert_ack(alert_id: str) -> dict[str, Any]:
        try:
            return acknowledge_alert(settings.db_path, alert_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/notifications/status")
    def notifications_status() -> dict[str, Any]:
        return web_push_status(settings.db_path)

    @app.get("/api/notifications/web-push/public-key")
    def notifications_public_key() -> dict[str, Any]:
        return web_push_public_key()

    @app.post("/api/notifications/web-push/subscribe")
    def notifications_subscribe(payload: WebPushSubscriptionRequest, request: Request) -> dict[str, Any]:
        try:
            return web_push_subscribe(settings.db_path, payload.model_dump(), request.headers.get("user-agent", ""))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/notifications/web-push/subscribe")
    def notifications_unsubscribe(payload: WebPushUnsubscribeRequest) -> dict[str, Any]:
        return web_push_unsubscribe(settings.db_path, payload.endpoint)

    @app.post("/api/notifications/web-push/test")
    def notifications_test() -> dict[str, Any]:
        return deliver_web_push(
            settings.db_path,
            alert_id=None,
            severity="INFO",
            payload={
                "title": "KQUANT 测试通知",
                "body": "TEST_ONLY：桌面通知测试，请在设备上确认是否看到；接口成功不代表送达。",
                "url": "/?workspace=today",
                "tag": "kquant-web-push-test",
            },
            force=True,
        )

    @app.get("/api/notifications/preferences")
    def notifications_preferences() -> dict[str, Any]:
        return notification_preferences(settings.db_path)

    @app.put("/api/notifications/preferences")
    def notifications_preferences_update(payload: NotificationPreferencesRequest) -> dict[str, Any]:
        try:
            return update_notification_preferences(settings.db_path, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runtime/supervisor-status")
    def supervisor_status() -> dict[str, Any]:
        return supervisor.status()

    @app.get("/api/options/status")
    def options_status() -> dict[str, Any]:
        return option_market_status()

    @app.get("/api/options/radar/status")
    def options_radar_status() -> dict[str, Any]:
        return {**option_radar_status(settings.db_path), "supervisor": option_radar_supervisor.status()}

    @app.get("/api/options/profiles")
    def options_profiles() -> dict[str, Any]:
        return load_options_profiles()

    @app.get("/api/options/foundation/status")
    def options_foundation() -> dict[str, Any]:
        return options_foundation_status(supervisor=option_radar_supervisor.status())

    @app.get("/api/options/research/workbench")
    def options_research_workbench() -> dict[str, Any]:
        return workbench_payload(DEFAULT_RESEARCH_DB)

    @app.get("/api/options/research/reviews/r1")
    def options_research_review_r1() -> dict[str, Any]:
        return review_r1_payload()

    @app.get("/api/options/research/reviews/r2")
    def options_research_review_r2() -> dict[str, Any]:
        return review_r2_payload()

    @app.get("/api/options/research/reviews/r3")
    def options_research_review_r3() -> dict[str, Any]:
        return review_r3_payload()

    @app.get("/api/options/research/reviews/r4")
    def options_research_review_r4() -> dict[str, Any]:
        return review_r4_payload()

    @app.get("/api/options/research/reviews/r5")
    def options_research_review_r5() -> dict[str, Any]:
        return review_r5_payload()

    @app.get("/api/options/research/reviews/r6")
    def options_research_review_r6() -> dict[str, Any]:
        return review_r6_payload()

    @app.get("/api/options/research/forward/status")
    def options_research_forward_status() -> dict[str, Any]:
        return forward_status(store_path=OPTIONS_FORWARD_DB, run_id=OPTIONS_FORWARD_RUN_ID)

    @app.get("/api/options/copilot/status")
    def options_copilot_status() -> dict[str, Any]:
        payload = copilot_status(store_path=OPTIONS_COPILOT_DB)
        if payload.get("current_policy_available") is False:
            return payload
        return {
            **payload,
            "astra_runtime": astra_status(),
            "model_router": model_router_status(budget_store=OPTIONS_COPILOT_DB),
            "desktop_notifications": web_push_status(settings.db_path),
        }

    @app.get("/api/options/full-watch/status")
    def options_full_watch_status(
        scope: str = Query(default="full", pattern="^(full|core)$"),
        state: str = "",
        q: str = "",
        operations_only: bool = False,
    ) -> dict[str, Any]:
        from ..options_two_hour import status as two_hour_status
        from ..options_full_watch import full_watch_policy_status
        availability = full_watch_policy_status()
        payload = (availability if availability.get("current_policy_available") is False else
                   {"status": "RESEARCH_ONLY"} if operations_only else full_watch_status(scope=scope, state=state, query=q))
        try:
            payload["two_hour"] = two_hour_status()
            worker = option_radar_supervisor._two_hour_worker
            payload["two_hour"]["worker"] = dict(worker.state) if worker else {"state": "NOT_STARTED"}
            payload["two_hour"]["enabled"] = option_radar_supervisor.two_hour_enabled
        except Exception as exc:
            payload["two_hour"] = {"status": "UNAVAILABLE", "error_type": type(exc).__name__, "paper_enabled": False}
        return payload

    @app.get("/api/options/intraday/proposal/status")
    def options_intraday_proposal_status() -> dict[str, Any]:
        from ..options_intraday import proposal_status
        return proposal_status()

    @app.get("/api/options/one-minute/status")
    async def options_one_minute_status(research_strategy: str = Query(default="one_minute", pattern="^(one_minute|opening_trend|opening_momentum)$"),
                                 compact: bool = Query(default=False)) -> dict[str, Any]:
        from zoneinfo import ZoneInfo
        observed = research_clock() if research_clock else datetime.now(timezone.utc)
        key = observed.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if research_strategy in {"opening_trend", "opening_momentum"}:
            try:
                # Both variants expose a summary; full evidence remains by ID/page.
                return research_snapshots.read(research_strategy, "compact")
            except (sqlite3.Error, SnapshotUnavailable) as exc:
                raise HTTPException(status_code=503, detail="TREND_STATUS_UNAVAILABLE") from exc
        try:
            payload = one_minute_snapshot.peek(key)
            payload["enabled"] = option_radar_supervisor.one_minute_shadow_enabled
            payload["worker"] = research_snapshots.context[2] if research_snapshots.context else {"state": "UNAVAILABLE"}
            payload["service_observation"] = research_snapshots.health()
            # This archived strategy is not a live publication lane.
            payload["candidates"] = []
            return payload
        except SnapshotUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    def load_one_minute_status() -> dict[str, Any]:
        from ..status_worker import load_one_minute
        return load_one_minute(settings.db_path, minute_path=minute_status_store,
                              now=research_clock() if research_clock else None)

    def load_opening_trend_status() -> dict[str, Any]:
        from ..status_worker import load_opening_trend
        return load_opening_trend(settings.db_path)

    def load_opening_trend_compact_status() -> dict[str, Any]:
        from ..status_worker import load_opening_trend
        return load_opening_trend(settings.db_path, compact=True)

    @app.get("/api/options/opening-trend/coverage")
    def options_opening_trend_coverage(session: str, scope_hash: str, checkpoint: str,
        offset: int = Query(default=0, ge=0, le=1110), limit: int = Query(default=50, ge=1, le=100),
        research_strategy: str = Query(default="opening_trend", pattern="^(opening_trend|opening_momentum)$")) -> dict[str, Any]:
        from ..status_worker import coverage_page, StatusQueryTimeout
        try:
            return coverage_page(research_strategy=research_strategy, session=session, scope_hash=scope_hash,
                                 checkpoint=checkpoint, offset=offset, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="INVALID_COVERAGE_PAGE") from exc
        except StatusQueryTimeout as exc:
            raise HTTPException(status_code=503, detail="COVERAGE_SNAPSHOT_UNAVAILABLE") from exc

    @app.get("/api/options/opening-trend/current")
    async def options_opening_trend_current_cards(research_strategy: str = Query(default="opening_momentum", pattern="^(opening_trend|opening_momentum)$")):
        try:
            return research_snapshots.read(research_strategy, "current")
        except SnapshotUnavailable as exc:
            raise HTTPException(status_code=503, detail="CURRENT_CARDS_UNAVAILABLE") from exc

    @app.post("/api/options/opening-trend/ai-review")
    def options_opening_ai_review(payload: dict[str, Any], request: Request):
        from ..options_data_paths import resolve_stores
        from ..options_one_minute import ROOT as code_root
        from ..options_opening_trend_store import detail
        from ..options_research_ai import approved, version_identity
        from ..options_research_ai_store import TaskStore
        from ..options_research_ai_worker import captured_event
        if not request.headers.get('X-KQUANT-WORKSPACE-USER') and not session_auth.session_from_request(request):
            raise HTTPException(status_code=401,detail='LOCAL_LOGIN_REQUIRED')
        identity=payload.get('evaluation_id')
        role=payload.get('role')
        if role not in {'SOL','ASTRA'} or not isinstance(identity,str) or not 1<=len(identity)<=128:
            raise HTTPException(status_code=422,detail='INVALID_RESEARCH_REVIEW_REQUEST')
        now=research_clock() if research_clock else datetime.now(UTC)
        try:
            ai_config=json.loads((code_root/'config/options_opening_research_ai.json').read_text(encoding='utf-8-sig'))
            receipt=json.loads((code_root/'config/review_acceptances/opening_ai_budget.json').read_text(encoding='utf-8-sig'))
            if not approved(ai_config,receipt,now=now):
                raise HTTPException(status_code=403,detail='AI_BUDGET_NOT_APPROVED')
            roles=resolve_stores(code_root)
            original=detail(identity,research_store or roles['opening_research'])
            if original and original.get('reference_collection_owner') == 'S0':
                parent_id=original.get('parent_evaluation_id')
                original=detail(parent_id,research_store or roles['opening_research']) if parent_id else None
            from ..options_research_availability import current_allowed
            if original and not current_allowed(original):
                raise HTTPException(status_code=409,detail='LATE_OR_UNVERIFIED_TIMELINESS')
            event=captured_event(original,original.get('current_eligibility',{}),
                                 versions=version_identity(ai_config)) if original else None
            if not event:
                raise HTTPException(status_code=409,detail='CURRENT_REFERENCE_RESEARCH_REQUIRED')
            outcome=TaskStore(roles['signal_copilot'],initialize=False).enqueue(event,role=role,now=now)
            return {'state':outcome,'role':role,'model':'gpt-6-astra' if role=='ASTRA' else 'gpt-6.1-sol','evaluation_id':identity,'paid_call':False,'qualified_signal':False}
        except HTTPException:
            raise
        except (OSError,sqlite3.Error,ValueError,KeyError):
            raise HTTPException(status_code=503,detail='AI_REVIEW_QUEUE_UNAVAILABLE')

    @app.get("/api/options/opening-trend/history")
    def options_opening_trend_history(session: str, scope_hash: str = Query(min_length=1, max_length=128),
                                      before: int | None = Query(default=None, ge=1),
                                      limit: int = Query(default=10, ge=1, le=50),
                                      research_strategy: str = Query(default="opening_trend", pattern="^(opening_trend|opening_momentum)$")) -> dict[str, Any]:
        from ..options_opening_trend import load_policy
        from ..options_opening_trend_history_page import history_page
        if research_strategy == "opening_momentum":
            from ..options_opening_momentum import load_policy
        try:
            return history_page(session=session, policy_hash=load_policy()["policy_hash"],
                                scope_hash=scope_hash, before=before, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="INVALID_HISTORY_PAGE") from exc
        except (sqlite3.Error, TimeoutError, FileNotFoundError) as exc:
            raise HTTPException(status_code=503, detail="TREND_HISTORY_UNAVAILABLE") from exc

    @app.get("/api/options/one-minute/evaluations/{evaluation_id}")
    def options_one_minute_evaluation(evaluation_id: str) -> dict[str, Any]:
        from ..options_one_minute import evaluation_detail
        try:
            from ..options_opening_trend_store import detail as trend_detail
            trend_row = trend_detail(evaluation_id, research_store) if research_store is not None else trend_detail(evaluation_id)
            if trend_row is not None:
                return trend_row
            payload = evaluation_detail(evaluation_id)
            from ..signal_eligibility import revision_history
            from ..options_signal_copilot import DEFAULT_STORE_PATH as copilot_store
            try:
                payload["eligibility_revisions"] = revision_history(copilot_store, "one-minute-" + payload["event_id"])
            except (sqlite3.Error, TimeoutError):
                payload["eligibility_revision_status"] = "UNAVAILABLE"
            return payload
        except (KeyError, sqlite3.Error) as exc:
            raise HTTPException(status_code=404, detail="EVALUATION_NOT_FOUND") from exc

    @app.get("/api/options/one-minute/manual")
    def options_one_minute_manual_status(request: Request, operation_key: str | None = None) -> dict[str, Any]:
        from ..options_one_minute_manual import manual_status, operation_status
        try:
            if operation_key is not None:
                extra = {"path": manual_store} if manual_store is not None else {}
                return operation_status(operation_key,
                    reviewer=request.headers.get("X-KQUANT-WORKSPACE-USER", ""), **extra)
            return manual_status(manual_store) if manual_store is not None else manual_status()
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (sqlite3.Error, ValueError, OSError) as exc:
            return JSONResponse({"status": "UNAVAILABLE", "positions": [], "alerts": [],
                "position_records_complete": False, "old_position_continuity": "UNKNOWN",
                "operation_status": "UNAVAILABLE", "error_code": "MANUAL_READ_UNAVAILABLE", "error_type": type(exc).__name__},
                status_code=503, headers={"Retry-After": "1"})

    @app.post("/api/options/one-minute/manual/entries")
    def options_one_minute_manual_entry(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        from ..options_one_minute_manual import open_report
        reviewer = request.headers.get("X-KQUANT-WORKSPACE-USER", "")
        try:
            extra = {"path": manual_store, "trend_path": research_store} if manual_store is not None else {}
            if manual_store is not None and research_clock is not None:
                extra["now"] = research_clock()
            return open_report(payload, reviewer=reviewer, **extra)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/options/one-minute/manual/exits")
    def options_one_minute_manual_exit(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        from ..options_one_minute_manual import exit_report
        reviewer = request.headers.get("X-KQUANT-WORKSPACE-USER", "")
        try:
            extra = {"path": manual_store} if manual_store is not None else {}
            if manual_store is not None and research_clock is not None:
                extra["now"] = research_clock()
            return exit_report(payload, reviewer=reviewer, **extra)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (ValueError, KeyError, TypeError, sqlite3.Error) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/options/model-router/status")
    def options_model_router_status() -> dict[str, Any]:
        return model_router_status(budget_store=OPTIONS_COPILOT_DB)

    @app.get("/api/options/full-watch/evaluations/{evaluation_id}")
    def options_evaluation_evidence(evaluation_id: str) -> dict[str, Any]:
        from ..options_two_hour import evaluation_detail
        try:
            return evaluation_detail(evaluation_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="EVALUATION_NOT_FOUND") from exc

    @app.get("/api/options/event-sources")
    def options_event_sources(symbol: str = Query(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9^$/:\[\]-]+(?:\.[A-Za-z0-9^$/:\[\]-]+)*$"),
                             research_strategy: str = Query(default="two_hour", pattern="^(one_minute|two_hour|opening_trend|opening_momentum)$")) -> dict[str, Any]:
        from ..options_two_hour import load_policy
        from ..options_two_hour_data import universe
        policy = load_policy()
        scope = universe(settings.db_path)
        normalized = symbol.upper().removesuffix(".US")
        if research_strategy in {"one_minute", "opening_trend", "opening_momentum"}:
            if research_strategy in {"opening_trend", "opening_momentum"}:
                from ..options_opening_trend import load_policy as research_policy
                from ..options_opening_trend_events import event_context, review_context
                if research_strategy == "opening_momentum":
                    from ..options_opening_momentum import load_policy as research_policy
            else:
                from ..options_one_minute import load_policy as research_policy
                from ..options_one_minute_events import event_context, review_context
            policy, now = research_policy(), datetime.now(UTC)
            result = {"symbol": normalized, "calendar_sources": source_observations(settings.db_path, normalized),
                    "reviewed_coverage": event_context(settings.db_path, normalized, now=now, policy=policy, scope_hash=scope["scope_hash"]),
                    "review_context": review_context(now=now, policy=policy, scope_hash=scope["scope_hash"]),
                    "source_archive_does_not_clear_entry": True}
            if research_strategy in {"opening_trend", "opening_momentum"}:
                from ..options_opening_trend_events import automatic_diagnostics
                result["automatic_coverage"] = result["reviewed_coverage"].get("automatic_coverage") or automatic_diagnostics(
                    settings.db_path, normalized, now=now, policy=policy, scope_hash=scope["scope_hash"])
            return result
        return {"symbol": normalized, "calendar_sources": source_observations(settings.db_path, normalized),
                "reviewed_coverage": option_event_context(settings.db_path, normalized,
                    policy_id=policy["policy_id"], policy_hash=policy["policy_hash"], scope_hash=scope["scope_hash"]),
                "source_archive_does_not_clear_entry": True}

    @app.post("/api/options/event-sources/reviews")
    def options_event_source_review(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        from ..option_event_coverage_v3 import import_v3_review
        from ..options_two_hour import load_policy
        from ..options_two_hour_data import universe
        reviewer = request.headers.get("X-KQUANT-WORKSPACE-USER", "")
        if not reviewer or reviewer == "local@kquant.local":
            raise HTTPException(status_code=403, detail="AUTHENTICATED_REVIEWER_REQUIRED")
        strategy = payload.get("research_strategy", "two_hour")
        if strategy not in {"one_minute", "two_hour", "opening_trend", "opening_momentum"}:
            raise HTTPException(status_code=400, detail="UNKNOWN_RESEARCH_STRATEGY")
        if strategy in {"one_minute", "opening_trend", "opening_momentum"}:
            if strategy in {"opening_trend", "opening_momentum"}:
                from ..options_opening_trend import load_policy as research_policy
                from ..options_opening_trend_events import import_review, event_context
                if strategy == "opening_momentum":
                    from ..options_opening_momentum import load_policy as research_policy
            else:
                from ..options_one_minute import load_policy as research_policy
                from ..options_one_minute_events import import_review, event_context
            policy, scope = research_policy(), universe(settings.db_path)
            now = datetime.now(UTC)
            try:
                identity = import_review(settings.db_path, payload, reviewer=reviewer, now=now,
                    policy=policy, scope_hash=scope["scope_hash"])
            except (ValueError, TypeError, KeyError) as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            return {"coverage_id": identity, "status": "REVIEW_RECORDED", "research_strategy": strategy,
                    "trade_eligible": event_context(settings.db_path, str(payload.get("symbol") or ""),
                        now=now, policy=policy, scope_hash=scope["scope_hash"])["trade_eligible"]}
        policy = load_policy()
        scope = universe(settings.db_path)
        try:
            identity = import_v3_review(settings.db_path, payload, reviewer=reviewer,
                policy_hash=policy["policy_hash"], scope_hash=scope["scope_hash"])
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"coverage_id": identity, "status": "REVIEW_RECORDED",
                "trade_eligible": option_event_context(settings.db_path, str(payload.get("symbol") or ""),
                    policy_id=policy["policy_id"], policy_hash=policy["policy_hash"], scope_hash=scope["scope_hash"])["trade_eligible"]}

    @app.get("/api/options/event-sources/{category}/events")
    def options_event_source_events(category: str, symbol: str = Query(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9^$/:\[\]-]+(?:\.[A-Za-z0-9^$/:\[\]-]+)*$")) -> dict[str, Any]:
        try:
            return source_events(settings.db_path, symbol, category)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=503, detail="SOURCE_ARCHIVE_UNAVAILABLE") from exc

    @app.post("/api/options/full-watch/observations")
    def options_research_observation(payload: dict[str, Any]) -> dict[str, Any]:
        from ..options_two_hour import set_observation
        if not isinstance(payload.get("active"), bool) or not isinstance(payload.get("evaluation_id"), str):
            raise HTTPException(status_code=400, detail="EVALUATION_ID_AND_ACTIVE_REQUIRED")
        try:
            return set_observation(payload["evaluation_id"], payload["active"])
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/options/full-watch/scan")
    def options_full_watch_scan(probe_symbols: str = "") -> dict[str, Any]:
        values = [item.strip().upper() for item in probe_symbols.split(",") if item.strip()]
        if len(values) > 8:
            raise HTTPException(status_code=400, detail="At most 8 bounded live probes may be requested per scan.")
        try:
            return run_full_watch_scan(settings.db_path, live_probe_symbols=values)
        except PolicyConfigUnavailable as exc:
            raise HTTPException(status_code=503, detail=exc.status()) from exc

    @app.post("/api/options/full-watch/options/{symbol}")
    def options_full_watch_option_check(symbol: str) -> dict[str, Any]:
        try:
            return check_full_watch_options(symbol)
        except PolicyConfigUnavailable as exc:
            raise HTTPException(status_code=503, detail=exc.status()) from exc
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/options/copilot/signals")
    def options_copilot_signals(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        return list_copilot_signals(store_path=OPTIONS_COPILOT_DB, limit=limit)

    @app.get("/api/options/copilot/signals/{signal_id}")
    def options_copilot_signal(signal_id: str) -> dict[str, Any]:
        try:
            return copilot_signal_detail(signal_id, store_path=OPTIONS_COPILOT_DB)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Signal not found.") from exc

    @app.post("/api/options/copilot/signals/{signal_id}/state")
    def options_copilot_signal_state(signal_id: str, payload: CopilotSignalStateRequest) -> dict[str, Any]:
        try:
            from ..options_signal_copilot import load_copilot_config
            load_copilot_config()
            return update_copilot_signal_state(signal_id, payload.state, reason=payload.reason, store_path=OPTIONS_COPILOT_DB)
        except PolicyConfigUnavailable as exc:
            raise HTTPException(status_code=503, detail=exc.status()) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Signal not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/options/copilot/notifications/{notification_id}/state")
    def options_copilot_notification_state(notification_id: str, payload: CopilotNotificationStateRequest) -> dict[str, Any]:
        try:
            from ..options_signal_copilot import load_copilot_config
            load_copilot_config()
            return update_copilot_notification_state(
                notification_id,
                payload.state,
                snoozed_until=payload.snoozed_until,
                reason=payload.reason,
                store_path=OPTIONS_COPILOT_DB,
            )
        except PolicyConfigUnavailable as exc:
            raise HTTPException(status_code=503, detail=exc.status()) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Notification not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/options/copilot/paper")
    def options_copilot_paper() -> dict[str, Any]:
        return copilot_paper_state(store_path=OPTIONS_COPILOT_DB)

    @app.post("/api/options/copilot/paper/confirm")
    def options_copilot_paper_confirm(payload: CopilotPaperConfirmationRequest) -> dict[str, Any]:
        contract = {
            "contract_id": payload.contract_id.upper(),
            "multiplier": payload.contract_multiplier,
            "underlying": payload.underlying.upper(),
            "theme_id": payload.theme_id,
        }

        def fetch_quote() -> dict[str, Any] | None:
            snapshot = option_contract_snapshot(payload.contract_id, settings.db_path)
            if snapshot.get("provider_status") != "available" or snapshot.get("depth_status") != "available":
                return None
            return {
                "contract_id": payload.contract_id.upper(),
                "contract_multiplier": snapshot.get("contract_multiplier"),
                "bid": snapshot.get("bid"), "ask": snapshot.get("ask"),
                "bid_size": snapshot.get("bid_size"), "ask_size": snapshot.get("ask_size"),
                "request_started_at": snapshot.get("bbo_request_started_at"),
                "received_at": snapshot.get("bbo_received_at"),
                "contract_validity": snapshot.get("contract_validity"),
                "source_bbo_time": snapshot.get("bbo_event_time"),
                "evidence_class": "RECEIPT_L1_PROXY",
            }

        try:
            return confirm_paper_intent(
                signal_id=payload.signal_id,
                action=payload.action,
                confirmation_id=payload.confirmation_id,
                confirmation_text=payload.confirmation_text,
                contract=contract,
                quote_fetcher=fetch_quote,
                limit_price=str(payload.limit_price),
                requested_quantity=payload.requested_quantity,
                store_path=OPTIONS_COPILOT_DB,
            )
        except PolicyConfigUnavailable as exc:
            raise HTTPException(status_code=503, detail=exc.status()) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Signal not found.") from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/options/research/cbrm")
    def options_research_cbrm(symbol: str = "", limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        return cbrm_review_payload(symbol=symbol or None, limit=limit)

    @app.get("/api/options/research/daily-groups")
    def options_research_daily_groups() -> dict[str, Any]:
        payload = forward_status(store_path=OPTIONS_FORWARD_DB, run_id=OPTIONS_FORWARD_RUN_ID)
        return {
            "status": payload.get("status"),
            "run_id": payload.get("run", {}).get("run_id"),
            "groups": payload.get("groups", []),
            "evidence_boundary": payload.get("evidence_boundary", {}),
            "orders_enabled": False,
        }

    @app.get("/api/options/research/features")
    def options_research_features() -> dict[str, Any]:
        payload = workbench_payload(DEFAULT_RESEARCH_DB)
        return {
            "status": payload.get("status"),
            "definitions": payload.get("feature_definitions", []),
            "equity_snapshots": payload.get("equity_feature_snapshots", []),
            "option_snapshots": payload.get("option_feature_snapshots", []),
        }

    @app.get("/api/options/research/experiment")
    def options_research_experiment() -> dict[str, Any]:
        payload = workbench_payload(DEFAULT_RESEARCH_DB)
        return {"status": payload.get("status"), "experiment": payload.get("experiment")}

    @app.get("/api/options/research/cohort")
    def options_research_cohort() -> dict[str, Any]:
        payload = workbench_payload(DEFAULT_RESEARCH_DB)
        return {"status": payload.get("status"), "cohort": payload.get("cohort")}

    @app.get("/api/options/research/scenarios")
    def options_research_scenarios() -> dict[str, Any]:
        payload = workbench_payload(DEFAULT_RESEARCH_DB)
        return {"status": payload.get("status"), "scenarios": payload.get("scenarios", [])}

    @app.get("/api/options/research/drafts")
    def options_research_drafts() -> dict[str, Any]:
        payload = workbench_payload(DEFAULT_RESEARCH_DB)
        return {"status": payload.get("status"), "hypotheses": payload.get("hypotheses", []), "drafts": payload.get("drafts", [])}

    @app.get("/api/options/radar/premarket")
    def options_radar_premarket(market_date: str = "") -> dict[str, Any]:
        return latest_premarket_report(settings.db_path, market_date)

    @app.post("/api/options/radar/runs")
    def options_radar_run() -> dict[str, Any]:
        return option_radar_supervisor.request_scan()

    @app.get("/api/options/radar/jobs/{job_id}")
    def options_radar_job(job_id: str) -> dict[str, Any]:
        try:
            return option_radar_supervisor.scan_job(job_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/options/signals/current")
    def options_signals_current(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        return list_option_signals(settings.db_path, current_only=True, limit=limit)

    @app.get("/api/options/signals/history")
    def options_signals_history(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        return list_option_signals(settings.db_path, current_only=False, limit=limit)

    @app.get("/api/options/signals/{opportunity_id}")
    def options_signal(opportunity_id: str) -> dict[str, Any]:
        try:
            return option_signal_detail(settings.db_path, opportunity_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/options/watchlist")
    def options_watchlist(active_only: bool = True, limit: int = Query(default=200, ge=1, le=500)) -> dict[str, Any]:
        return list_option_watchlist(settings.db_path, active_only=active_only, limit=limit)

    @app.post("/api/options/watchlist")
    def options_watchlist_add(payload: OptionWatchRequest) -> dict[str, Any]:
        try:
            return set_option_watch(settings.db_path, payload.plan_id, notes=payload.notes)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/api/options/watchlist/{plan_id}")
    def options_watchlist_remove(plan_id: str) -> dict[str, Any]:
        try:
            return remove_option_watch(settings.db_path, plan_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/options/plans/{plan_id}/timeline")
    def options_plan_timeline_route(plan_id: str) -> dict[str, Any]:
        try:
            return option_plan_timeline(settings.db_path, plan_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/options/manual-outcomes")
    def options_manual_outcomes(limit: int = Query(default=200, ge=1, le=500)) -> dict[str, Any]:
        return list_option_manual_outcomes(settings.db_path, limit=limit)

    @app.post("/api/options/manual-outcomes")
    def options_manual_outcome(payload: OptionManualOutcomeRequest) -> dict[str, Any]:
        try:
            return record_option_manual_outcome(settings.db_path, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/options/research-report")
    def options_research_report() -> dict[str, Any]:
        return option_research_report(settings.db_path)

    @app.get("/api/options/data-audit")
    def options_data_audit() -> dict[str, Any]:
        return option_data_audit(settings.db_path)

    @app.get("/api/options/simulations")
    def options_simulations(limit: int = Query(default=200, ge=1, le=500)) -> dict[str, Any]:
        return list_option_simulations(settings.db_path, limit=limit)

    @app.post("/api/options/simulations")
    def options_simulation(payload: OptionRadarSimulationRequest) -> dict[str, Any]:
        try:
            return record_option_simulation(settings.db_path, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/options/expiries")
    def options_expiries(symbol: str = "NVDA") -> dict[str, Any]:
        try:
            payload = option_expiries(symbol)
            record_stock_watchlist_capability(
                settings.db_path,
                symbol,
                "options",
                "available" if payload.get("provider_status") == "available" and payload.get("expiries") else "unavailable",
            )
            return payload
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/options/chain")
    def options_chain(symbol: str, expiry: str) -> dict[str, Any]:
        try:
            return option_chain(symbol, expiry)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/options/contracts/stream")
    async def options_quote_stream(request: Request, contracts: str):
        from ..option_quote_stream import contract_list, stream
        try:
            values = contract_list(contracts)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return StreamingResponse(stream(request, values), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/options/contracts/snapshots")
    def option_contract_batch(contracts: str = "", greeks_only: bool = False) -> dict[str, Any]:
        values = [item.strip() for item in contracts.split(",") if item.strip()]
        if len(values) > 50:
            raise HTTPException(status_code=400, detail="At most 50 option contracts may be requested.")
        return option_contract_snapshots(values, greeks_only=greeks_only) if greeks_only else option_contract_snapshots(values)

    @app.get("/api/options/daily-summary")
    def options_daily_summary() -> dict[str, Any]:
        return daily_option_scope_report(
            settings.db_path,
            forward_store_path=OPTIONS_FORWARD_DB,
            forward_run_id=OPTIONS_FORWARD_RUN_ID,
        )

    @app.get("/api/options/candidates")
    def options_candidates(symbol: str = "NVDA") -> dict[str, Any]:
        coverage = api_stock_data_coverage(settings.db_path)
        event_status = str((coverage.get("event_calendar") or {}).get("status") or "missing")
        try:
            return option_candidates(settings.db_path, symbol, event_calendar_ready=event_status == "available")
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    from ..options_opening_trend_pipeline import Services as ReferenceContractServices
    reference_contract_services = ReferenceContractServices(settings.db_path)

    @app.get("/api/options/contracts/{contract}")
    def option_contract(contract: str, include_metadata: bool = False) -> dict[str, Any]:
        try:
            if include_metadata:
                # Use the same native metadata-before-BBO path as qualification.
                return reference_contract_services.contract(contract)["snapshot"]
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
    def candles(symbol: str = "SPY", range: str = "1y", interval: str = "1d", source: str = "live",
                mode: str = "", session: str = "regular", adjustment: str = "none",
                before: str | None = None, limit: int = Query(default=1000, ge=1, le=1000), raw_sdk: bool = False) -> dict[str, Any]:
        if mode == "chart":
            from ..stock_chart import chart_candles
            if raw_sdk:
                return chart_candles(symbol, interval, session, adjustment, before, limit, raw_sdk=True)
            return chart_candles(symbol, interval, session, adjustment, before, limit)
        if raw_sdk:
            raise HTTPException(status_code=422, detail="BOUNDED_RAW_SDK_CHART_MODE_REQUIRED")
        payload = api_stock_candles(symbol, range, interval, _live_only(source), settings.db_path)
        record_stock_watchlist_capability(
            settings.db_path,
            symbol,
            "history",
            "available" if payload.get("candles") else "unavailable",
        )
        return payload

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
    def quote(symbol: str = "SPY", mode: str = "") -> dict[str, Any]:
        if mode == "chart":
            from ..stock_chart import snapshot
            return snapshot(symbol)
        return api_stock_quote(symbol, settings.db_path)

    @app.get("/api/stocks/depth")
    def chart_depth(symbol: str = "SPY") -> dict[str, Any]:
        from ..stock_chart import snapshot
        return snapshot(symbol, "depth")

    @app.get("/api/stocks/chart/stream")
    async def stock_chart_stream(request: Request, symbol: str = "SPY", interval: str = "5m",
                                 session: str = "regular", adjustment: str = "none"):
        from ..stock_chart import chart_stream, PERIODS, symbol_code
        if interval not in PERIODS or session not in ("regular", "extended") or adjustment not in ("none", "forward"):
            raise HTTPException(422, "Invalid chart contract")
        try:
            symbol_code(symbol)
        except ValueError:
            raise HTTPException(422, "Invalid symbol")
        return StreamingResponse(chart_stream(request, symbol, interval, session, adjustment),
                                 media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/stocks/watchlist/groups")
    def stock_watchlist_groups() -> dict[str, Any]:
        return list_stock_watchlist_groups(settings.db_path)

    @app.get("/api/stocks/watchlist")
    def stock_watchlist(group_id: str = "", q: str = "", include_removed: bool = False) -> dict[str, Any]:
        return list_stock_watchlist_members(settings.db_path, group_id=group_id, query=q, include_removed=include_removed)

    @app.get("/api/stocks/watchlist/quotes")
    def stock_watchlist_group_quotes(group_id: str, selected_symbol: str = "") -> dict[str, Any]:
        return stock_watchlist_quotes(settings.db_path, group_id, selected_symbol=selected_symbol)

    @app.get("/api/stocks/watchlist/audit")
    def stock_watchlist_audit() -> dict[str, Any]:
        return watchlist_audit(settings.db_path)

    @app.post("/api/stocks/watchlist/members")
    def stock_watchlist_add(payload: StockWatchlistMemberRequest) -> dict[str, Any]:
        try:
            return add_stock_watchlist_member(settings.db_path, payload.group_id, payload.symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/stocks/watchlist/members/{member_id}")
    def stock_watchlist_remove(member_id: str) -> dict[str, Any]:
        try:
            return remove_stock_watchlist_member(settings.db_path, member_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/stocks/watchlist/identity-refresh")
    def stock_watchlist_identity_refresh() -> dict[str, Any]:
        return refresh_stock_watchlist_identities(settings.db_path)

    @app.get("/api/stocks/realtime-snapshot")
    def realtime_snapshot(symbol: str = "SPY") -> dict[str, Any]:
        return api_stock_realtime_snapshot(symbol, settings.db_path)

    @app.get("/api/stocks/market-data/status")
    def market_data_status() -> dict[str, Any]:
        return api_stock_market_data_status(settings.db_path)

    @app.get("/api/stocks/data-coverage")
    def data_coverage() -> dict[str, Any]:
        return api_stock_data_coverage(settings.db_path)

    @app.get("/api/data/coverage")
    def data_trust_coverage(detail: str = "full") -> dict[str, Any]:
        """Canonical v2 Data Trust endpoint; legacy stock route remains compatible.

        The default retains the original complete audit representation. The UI
        explicitly requests ``detail=summary`` for the light operational view.
        """

        normalized_detail = detail.strip().lower()
        if normalized_detail not in {"summary", "full"}:
            raise HTTPException(status_code=400, detail="detail must be 'summary' or 'full'")
        payload = api_stock_data_coverage(
            settings.db_path,
            include_symbols=normalized_detail == "full",
            prefer_materialized_summary=normalized_detail == "summary",
        )
        readiness = stock_quant_validation_readiness(settings.db_path)
        payload["historical_validation"] = {
            "status": readiness.get("status"),
            "universe_symbols": readiness.get("universe_symbols", payload.get("universe_symbols", 0)),
            "eligible_symbols": readiness.get("validation_window_eligible_symbols"),
            "coverage_pct": readiness.get("validation_window_coverage_pct"),
            "target_symbols": readiness.get("target_symbols"),
            "target_pct": readiness.get("target_pct", 90.0),
            "additional_symbols_required": readiness.get("additional_symbols_required"),
            "target_met": readiness.get("target_met", False),
            "reason": readiness.get("reason"),
        }
        payload["detail"] = normalized_detail
        return payload

    @app.get("/api/data/snapshots/{snapshot_id}")
    def data_snapshot(snapshot_id: str) -> dict[str, Any]:
        try:
            return read_data_snapshot(settings.db_path, snapshot_id=snapshot_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/themes")
    def themes() -> dict[str, Any]:
        return latest_theme_taxonomy(settings.db_path)

    @app.get("/api/themes/ranking")
    def theme_ranking() -> dict[str, Any]:
        return latest_capital_rotation(settings.db_path)

    @app.get("/api/themes/audit")
    def theme_taxonomy_audit() -> dict[str, Any]:
        return taxonomy_audit(settings.db_path)

    @app.get("/api/leadership/latest")
    def leadership_latest() -> dict[str, Any]:
        return latest_leadership(settings.db_path)

    @app.get("/api/themes/{theme_id}/leaders")
    def theme_leader_rows(theme_id: str) -> dict[str, Any]:
        try:
            return theme_leaders(settings.db_path, theme_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/themes/{theme_id:path}")
    def theme(theme_id: str) -> dict[str, Any]:
        try:
            payload = theme_detail(settings.db_path, theme_id)
            rotation = latest_capital_rotation(settings.db_path)
            if rotation.get("status") == "materialized":
                try:
                    payload["capital_rotation"] = capital_rotation_detail(settings.db_path, theme_id)
                except ValueError:
                    payload["capital_rotation"] = {"status": "not_ranked"}
            else:
                payload["capital_rotation"] = {"status": "not_materialized"}
            return payload
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/models/validation-runs")
    def model_validation_runs(dataset_id: str = "") -> dict[str, Any]:
        return list_model_artifacts(settings.db_path, dataset_id=dataset_id or None)

    @app.get("/api/models/theme-prediction/latest")
    def theme_prediction_latest() -> dict[str, Any]:
        return latest_theme_prediction(settings.db_path)

    @app.get("/api/models/theme-prediction/{run_id}")
    def theme_prediction_run(run_id: str) -> dict[str, Any]:
        try:
            return theme_prediction_detail(settings.db_path, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetIntegrityError as exc:
            raise HTTPException(status_code=409, detail="Theme prediction integrity check failed.") from exc

    @app.get("/api/models/{artifact_id}/metrics")
    def model_metrics(artifact_id: str) -> dict[str, Any]:
        try:
            return model_artifact_detail(settings.db_path, artifact_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetIntegrityError as exc:
            raise HTTPException(status_code=409, detail="Model artifact integrity check failed.") from exc

    @app.get("/api/quant/stocks/ranking")
    def stock_quant_model_ranking(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
        return stock_quant_ranking(settings.db_path, limit=limit)

    @app.get("/api/quant/stocks/validation-readiness")
    def stock_quant_validation_readiness_route(dataset_id: str = "") -> dict[str, Any]:
        return stock_quant_validation_readiness(settings.db_path, dataset_id=dataset_id or None)

    @app.get("/api/quant/overview")
    def quant_overview() -> dict[str, Any]:
        return build_v2_overview(settings.db_path)

    @app.get("/api/shadow-observation/status")
    def shadow_observation_status() -> dict[str, Any]:
        return latest_shadow_observation(settings.db_path)

    @app.post("/api/quant/stocks/validation/runs")
    def stock_quant_validation_run(payload: StockQuantValidationRequest) -> dict[str, Any]:
        try:
            return run_stock_quant_validation(settings.db_path, payload.dataset_id, random_seed=payload.random_seed)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except DatasetIntegrityError as exc:
            raise HTTPException(status_code=409, detail="Stock Quant validation integrity check failed.") from exc

    @app.get("/api/quant/stocks/validation/latest")
    def stock_quant_validation_latest() -> dict[str, Any]:
        return latest_stock_quant_validation(settings.db_path)

    @app.get("/api/quant/stocks/validation/{run_id}")
    def stock_quant_validation_run_detail(run_id: str) -> dict[str, Any]:
        try:
            return stock_quant_validation_detail(settings.db_path, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DatasetIntegrityError as exc:
            raise HTTPException(status_code=409, detail="Stock Quant validation integrity check failed.") from exc

    @app.get("/api/quant/stocks/{symbol}")
    def stock_quant_model_detail(symbol: str) -> dict[str, Any]:
        return stock_quant_symbol_detail(settings.db_path, symbol)

    @app.get("/api/quant/stocks")
    def stock_quant_model_status() -> dict[str, Any]:
        return latest_stock_quant_run(settings.db_path)

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

    @app.get("/api/stocks/{symbol}/early-trend")
    def early_trend(symbol: str) -> dict[str, Any]:
        return early_trend_snapshot(symbol, settings.db_path)

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

    def unified_redirect(request: Request) -> RedirectResponse | None:
        if os.getenv("KQUANT_UNIFIED_UI_REDIRECT", "false").strip().lower() != "true":
            return None
        base_url = os.getenv("KQUANT_UNIFIED_UI_URL", "http://127.0.0.1:8020").rstrip("/")
        params = dict(request.query_params)
        legacy = str(params.get("workspace") or params.get("view") or "today").lower()
        view_map = {"today": "today", "stock": "today", "charts": "chart", "chart": "chart", "options": "opportunities", "plan": "plans", "research": "review", "journal": "review", "settings": "settings", "status": "settings"}
        params["workspace"] = "options" if legacy == "options" else "stocks"
        params["view"] = view_map.get(str(params.get("view") or legacy).lower(), "today")
        params.pop("market", None)
        return RedirectResponse(f"{base_url}/?{urlencode(params)}", status_code=307)

    @app.get("/")
    def frontend_index(request: Request):
        redirect = unified_redirect(request)
        if redirect is not None:
            return redirect
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
