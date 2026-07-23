from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kquant.config import KquantConfig, load_config
from kquant.database_migrations import migration_readiness
from kquant.decision_ledger import (
    create_decision_ledger_entry,
    list_decision_ledger,
    record_manual_trade_journal,
    weekly_personal_review,
)
from kquant.manual_workflow import calculate_manual_position_size
from kquant.operations import (
    dispatch_personal_notification,
    operational_health,
    queue_notification,
    recent_notifications,
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


FORBIDDEN_ROUTE_TOKENS = (
    "/account",
    "/broker",
    "/orders",
    "/positions",
    "/options",
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
    }


def create_app(
    config_path: str | Path = "config/default.yml",
    *,
    config: KquantConfig | None = None,
) -> FastAPI:
    settings = config or load_config(config_path)
    app = FastAPI(title=settings.product, version="0.3.0")
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8001",
            "http://127.0.0.1:8001",
        ],
        allow_origin_regex=r"https://.*",
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        market_data = api_stock_market_data_status(db_path=settings.db_path)
        safety = route_safety_report(app)
        return {
            "product": settings.product,
            "status": "online" if safety["status"] == "pass" else "unsafe",
            "backend": "kquant.dashboard.fastapi",
            "stock_database": str(settings.db_path),
            "market_data": market_data,
            "ai": api_stock_ai_review_status(),
            "safety": safety,
            "read_only_research": True,
        }

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
        return FileResponse(index)
