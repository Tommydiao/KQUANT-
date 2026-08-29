from __future__ import annotations

import json
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..config import API_CONTRACT_VERSION, APP_VERSION, FRONTEND_CONTRACT_VERSION, Settings, load_settings
from ..db.migrations import migration_status, migrate
from ..evaluation_agent import EvaluationAgent
from ..evaluation_store import (
    get_evaluation,
    get_trade_plan,
    latest_evaluations,
    list_trade_plans,
)
from ..security import SessionAuth
from ..notifications import (
    NotificationHub,
    acknowledge_notification,
    deliver_web_push,
    get_notification_preferences,
    list_evaluated_notifications,
    notification_status,
    record_notification,
    remove_web_push_subscription,
    save_web_push_subscription,
    set_notification_preferences,
)
from ..provider_runtime import ProviderSupervisor, provider_health
from ..market_runtime import MarketDataRuntime
from ..market_regime_runtime import MarketRegimeRuntime
from ..dex_runtime import DexDiscoveryRuntime
from ..dex_models import DexSecurityStore
from ..data_trust import DataTrustStore
from ..factor_registry import FactorRegistry, MemeFactorRegistry
from ..evaluation_models import EVAL_POLICY_VERSION, TradePlanDraft
from ..backtest import BacktestBar, BacktestConfig, bars_for_duration
from ..validation import ValidationConfig, ValidationSeries, evaluate_validation_gate, run_walk_forward_validation
from ..validation_store import latest_validation_run, save_validation_run
from ..historical_dataset import load_parquet_validation_dataset
from ..paper_store import PaperGateError, close_paper_observation, create_paper_observation, list_paper_observations
from ..meme_factors import MemeObservation, compute_meme_factors
from ..instruction_store import get_instruction, list_current_instructions, list_instructions
from ..realtime_supervisor import RealtimeSupervisor
from ..signal_runtime import CEXSignalRuntime
from ..model_registry import ModelArtifactRegistry
from ..model_baselines import run_model_benchmark
from ..llm_advisor import list_advisory_reviews, save_advisory_review
from ..universe import UniverseRegistry
from ..bayesian_model import PointInTimeFeatureSnapshot, infer_bayesian_posterior
from ..monte_carlo import MonteCarloConfig, simulate_monte_carlo
from ..research_store import (
    get_bayesian_posterior,
    get_monte_carlo_result,
    latest_bayesian_posterior,
    latest_monte_carlo_result,
    save_bayesian_posterior,
    save_monte_carlo_result,
)
from ..roll_engine import RollInput, evaluate_roll
from ..roll_store import (
    get_roll_decision,
    list_current_roll_decisions,
    list_roll_decisions,
    list_roll_ledger,
    record_roll_ledger_event,
    save_roll_decision,
)
from ..roll_validation import RollBar, RollValidationConfig, build_roll_series_from_validation, run_roll_walk_forward
from ..roll_validation_store import get_roll_validation_report, latest_roll_validation_report, save_roll_validation_report
from ..roll_packet import build_roll_feature_packet_from_db
from ..roll_journal import preview_roll_journal_text
from ..roll_journal_store import confirm_roll_journal_preview, save_roll_journal_preview
from ..shadow_store import (
    get_shadow_observation,
    list_shadow_audit_events,
    list_shadow_observations,
    record_shadow_outcome,
    review_shadow_observation,
    save_shadow_observation,
    shadow_summary,
)
from ..external_evidence import (
    SUPPORTED_EVIDENCE_ASSETS,
    evidence_coverage,
    evidence_bundle,
    list_latest_evidence,
    save_evidence_snapshot,
)
from ..backup import latest_backup_status
from ..evidence_collectors import evidence_source_capabilities, fetch_configured_evidence, normalize_provider_evidence
from ..public_evidence import fetch_binance_derivatives_evidence, fetch_okx_derivatives_evidence
from ..market_structure_evidence import fetch_binance_market_structure_evidence
from ..providers.coinglass import CoinGlassPublicAdapter
from ..providers.defillama import DefiLlamaPublicAdapter
from ..observability import build_observability_summary
from ..staging import staging_status
from ..readiness import evaluate_readiness
from ..collection_session import read_collection_gate, read_collection_session


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=512)


class WebPushSubscriptionRequest(BaseModel):
    endpoint: str = Field(min_length=10, max_length=4096)
    keys: dict[str, str]


class WebPushRemoveRequest(BaseModel):
    endpoint: str = Field(min_length=10, max_length=4096)


class NotificationPreferencesRequest(BaseModel):
    enabled: bool = False
    web_push_enabled: bool = False
    telegram_enabled: bool = False
    quiet_start: str | None = Field(default=None, max_length=5)
    quiet_end: str | None = Field(default=None, max_length=5)
    timezone: str = Field(default="Asia/Shanghai", min_length=3, max_length=64)


PUBLIC_API_PATHS = {
    "/api/health",
    "/api/version",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/session",
}


def _frontend_index(settings: Settings) -> Path | None:
    built = settings.web_dist_dir / "index.html"
    source = settings.root_dir / "web" / "index.html"
    return built if built.exists() else source if source.exists() else None


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()
    auth = SessionAuth(
        resolved.db_path,
        resolved.login_email,
        resolved.login_password_hash,
        resolved.session_secret,
        resolved.session_idle_minutes,
        resolved.session_max_hours,
    )
    hub = NotificationHub()
    factor_registry = FactorRegistry(resolved.db_path)
    meme_factor_registry = MemeFactorRegistry(resolved.db_path)
    model_registry = ModelArtifactRegistry(resolved.db_path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        migrate(resolved.db_path)
        factor_registry.register()
        meme_factor_registry.register()
        supervisor = ProviderSupervisor(resolved)
        runtime = MarketDataRuntime(
            resolved.data_dir,
            db_path=resolved.db_path,
            flush_every=resolved.market_storage_flush_every,
            trade_bucket_seconds=resolved.market_trade_bucket_seconds,
            quote_sample_seconds=resolved.market_quote_sample_seconds,
            ticker_sample_seconds=resolved.market_ticker_sample_seconds,
        )
        instruction_supervisor = RealtimeSupervisor(resolved.db_path, hub, resolved)
        universe_snapshot = UniverseRegistry(resolved.db_path).ensure_cex_snapshot(
            resolved.core_symbols,
            root_dir=resolved.root_dir,
        )
        hydration = await asyncio.to_thread(
            runtime.hydrate_recent_closed_klines,
            resolved.core_symbols,
            limit_per_instrument=2048,
        )
        regime_runtime = MarketRegimeRuntime(
            resolved.db_path,
            runtime,
            symbols=resolved.core_symbols,
            universe_snapshot_id=str(universe_snapshot["snapshot_id"]),
        )
        signal_runtime = CEXSignalRuntime(
            resolved.db_path,
            runtime,
            factor_registry,
            instruction_supervisor,
            universe_snapshot_id=str(universe_snapshot["snapshot_id"]),
            regime_runtime=regime_runtime,
        )

        async def ingest_market_event(event: Any) -> None:
            await runtime.ingest(event)
            await regime_runtime.on_market_event(event)
            instruction_supervisor.on_market_event(event)
            signal_runtime.on_market_event(event)

        supervisor.on_event = ingest_market_event
        app.state.provider_supervisor = supervisor
        app.state.market_runtime = runtime
        app.state.factor_registry = factor_registry
        app.state.universe_snapshot = universe_snapshot
        app.state.realtime_supervisor = instruction_supervisor
        app.state.signal_runtime = signal_runtime
        app.state.market_regime_runtime = regime_runtime
        app.state.market_hydration = hydration
        task = None
        dex_runtime = DexDiscoveryRuntime(resolved) if resolved.providers.dexscreener else None
        dex_task = None
        app.state.dex_discovery_runtime = dex_runtime
        if any(resolved.providers.as_dict().get(name, False) for name in ("binance", "okx", "coinbase", "kraken")):
            task = asyncio.create_task(supervisor.run(list(resolved.core_symbols)))
        if dex_runtime is not None:
            dex_task = asyncio.create_task(dex_runtime.run_forever())
        try:
            yield
        finally:
            supervisor.stop()
            if dex_runtime is not None:
                dex_runtime.stop()
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if dex_task:
                dex_task.cancel()
                await asyncio.gather(dex_task, return_exceptions=True)
            runtime.flush(force=True)

    app = FastAPI(title="KQUANT CRYPTO", version=APP_VERSION, lifespan=lifespan)
    app.state.started_at = datetime.now(UTC).isoformat()
    app.state.settings = resolved
    app.state.auth = auth
    app.state.notification_hub = hub
    # Keep request handlers usable in unit tests that do not enter the ASGI
    # lifespan; the lifespan replaces this with the runtime-owned instance.
    app.state.realtime_supervisor = RealtimeSupervisor(resolved.db_path, hub, resolved)
    app.state.signal_runtime = None

    def _current_provider_health() -> dict[str, dict[str, Any]]:
        values = provider_health(resolved, getattr(app.state, "provider_supervisor", None))
        discovery = getattr(app.state, "dex_discovery_runtime", None)
        if discovery is not None and "dexscreener" in values:
            state = discovery.status()
            values["dexscreener"].update(
                status=state["status"],
                connected=state["status"] == "available",
                last_source_time=state["last_run_at"],
                last_received_at=state["last_run_at"],
                last_error=state["last_error"],
            )
        return values

    def _collector_session_status() -> dict[str, Any]:
        """Expose the separate public collector without merging runtimes."""

        configured_collector_providers = [
            name for name, enabled in resolved.providers.as_dict().items()
            if enabled and name in {"binance", "okx", "coinbase", "kraken"}
        ]
        value = read_collection_session(resolved.outputs_dir)
        # Older collector sessions predate the provider field. Recover it from
        # local public-provider configuration; this never grants capabilities.
        value["providers"] = list(value.get("providers") or configured_collector_providers)
        value.setdefault("market_data_only", True)
        value.setdefault("paper_or_order_access", False)
        return value

    @app.middleware("http")
    async def require_local_session(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in PUBLIC_API_PATHS:
            email = auth.authenticate(request.cookies.get(SessionAuth.cookie_name))
            if not email:
                return JSONResponse({"detail": "请先登录本机研究终端。"}, status_code=401)
            request.state.user_email = email
        return await call_next(request)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        universe = getattr(app.state, "universe_snapshot", None) or {}
        schema = migration_status(resolved.db_path)
        return {
            "status": "ok",
            "app_version": APP_VERSION,
            "api_contract_version": API_CONTRACT_VERSION,
            "frontend_contract_version": FRONTEND_CONTRACT_VERSION,
            "build_sha": os.getenv("KQUANT_CRYPTO_BUILD_SHA", "local")[:80],
            "started_at": app.state.started_at,
            "schema": schema,
            "version_matrix": {
                "application": APP_VERSION,
                "api": API_CONTRACT_VERSION,
                "frontend": FRONTEND_CONTRACT_VERSION,
                "schema": schema.get("current_version", 0),
                "strategy": "crypto_roll_v1.0.0",
                "eval_policy": EVAL_POLICY_VERSION,
            },
            "runtime_mode": resolved.mode.value,
            "auth": {"configured": auth.configured, "session_cookie": SessionAuth.cookie_name},
            "providers": _current_provider_health(),
            "collector_session": _collector_session_status(),
            "dex_discovery": getattr(getattr(app.state, "dex_discovery_runtime", None), "status", lambda: {"status": "disabled"})(),
            "instruction_supervisor": getattr(getattr(app.state, "realtime_supervisor", None), "status", lambda: {"status": "not_started"})(),
            "signal_runtime": getattr(getattr(app.state, "signal_runtime", None), "status", lambda: {"status": "not_started"})(),
            "market_regime": getattr(getattr(app.state, "market_regime_runtime", None), "status", lambda: {"status": "not_started"})(),
            "market_hydration": getattr(app.state, "market_hydration", {"status": "not_started"}),
            "universe": {
                "snapshot_id": universe.get("snapshot_id"),
                "registry_version": universe.get("registry_version"),
                "member_count": universe.get("member_count"),
                "content_hash": universe.get("content_hash"),
                "status": universe.get("status", "not_started"),
                "symbols": list(resolved.core_symbols),
            },
            "read_only": True,
            "account_access": False,
            "wallet_access": False,
            "order_submission": False,
            "eval_policy_version": EVAL_POLICY_VERSION,
            "research_layers": {
                "crypto_roll_strategy_version": "crypto_roll_v1.0.0",
                "bayesian_model_version": "crypto_bayesian_v1.0.0",
                "monte_carlo_model_version": "crypto_monte_carlo_v1.0.0",
                "roll_execution_enabled": False,
                "research_only": True,
            },
            "shadow_observation": shadow_summary(resolved.db_path, validation_gate_status="NO_GO"),
        }

    @app.get("/api/version")
    async def version() -> dict[str, Any]:
        """Return the same build contract as health without runtime details."""

        schema = migration_status(resolved.db_path)
        return {
            "application": APP_VERSION,
            "api": API_CONTRACT_VERSION,
            "frontend": FRONTEND_CONTRACT_VERSION,
            "schema": schema.get("current_version", 0),
            "strategy": "crypto_roll_v1.0.0",
            "bayesian": "crypto_bayesian_v1.0.0",
            "monte_carlo": "crypto_monte_carlo_v1.0.0",
            "eval_policy": EVAL_POLICY_VERSION,
            "build_sha": os.getenv("KQUANT_CRYPTO_BUILD_SHA", "local")[:80],
            "research_only": True,
            "order_submission": False,
        }

    @app.get("/api/operations/observability")
    async def operations_observability():
        report = latest_roll_validation_report(resolved.db_path)
        validation_status = str((report or {}).get("validation_gate", {}).get("status") or "NO_GO")
        return build_observability_summary(
            resolved.db_path,
            settings=resolved,
            providers=_current_provider_health(),
            runtime={
                "started_at": app.state.started_at,
                "signal": getattr(getattr(app.state, "signal_runtime", None), "status", lambda: {})(),
                "instruction": getattr(getattr(app.state, "realtime_supervisor", None), "status", lambda: {})(),
            },
            shadow=shadow_summary(resolved.db_path, validation_gate_status=validation_status),
        )

    @app.get("/api/operations/staging")
    async def operations_staging():
        return staging_status(resolved)

    @app.get("/api/operations/go-no-go")
    async def operations_go_no_go():
        """Return the complete, secret-free 999 research readiness report."""

        validation = latest_roll_validation_report(resolved.db_path) or {}
        validation_gate = validation.get("validation_gate") if isinstance(validation, dict) else None
        runtime = getattr(app.state, "market_runtime", None)
        runtime_coverage = runtime.coverage() if runtime else {}
        storage = (runtime_coverage.get("storage") or {}) if isinstance(runtime_coverage, dict) else {}
        continuous_gate = read_collection_gate(resolved.outputs_dir)
        coverage_gate = {
            "coverage_index_status": storage.get("coverage_index_status", "unknown"),
            "continuous_collection_gate": continuous_gate,
        }
        staging = staging_status(resolved)
        if staging.get("postgres_configured") and staging.get("driver_available"):
            from ..staging import verify_staging

            staging = verify_staging(resolved)
        shadow = shadow_summary(
            resolved.db_path,
            validation_gate_status=str((validation_gate or {}).get("status") or "NO_GO"),
        )
        readiness = evaluate_readiness(
            validation_gate=validation_gate,
            coverage_gate=coverage_gate,
            evidence_coverage=evidence_coverage(resolved.db_path),
            staging=staging,
            shadow=shadow,
            backup=latest_backup_status(resolved.root_dir / "work" / "backups"),
            raw_index_repair_required=bool(storage.get("raw_index_repair_required", True)),
            research_only=True,
            order_submission=False,
        )
        return {
            "readiness": readiness,
            "components": {
                "validation": validation_gate,
                "coverage": coverage_gate,
                "staging": staging,
                "shadow": shadow,
            },
            "research_only": True,
            "order_submission": False,
        }

    @app.get("/api/operations/backup/status")
    async def operations_backup_status():
        backup = latest_backup_status(resolved.root_dir / "work" / "backups")
        return {
            **backup,
            "backup_command": "python scripts/backup_crypto_state.py",
            "restore_command": "python scripts/restore_crypto_state.py --help",
            "research_only": True,
            "secrets_exposed": False,
        }

    @app.post("/api/auth/login")
    async def login(payload: LoginRequest, request: Request, response: Response):
        client_key = request.client.host if request.client else "local"
        token = auth.login(payload.email, payload.password, client_key)
        if not token:
            raise HTTPException(status_code=401, detail="邮箱或密码不正确，或登录暂时受限。")
        response.set_cookie(
            SessionAuth.cookie_name,
            token,
            httponly=True,
            samesite="strict",
            secure=False,
            max_age=resolved.session_max_hours * 3600,
            path="/",
        )
        return {"authenticated": True, "email": auth.email}

    @app.post("/api/auth/logout")
    async def logout(request: Request, response: Response):
        auth.logout(request.cookies.get(SessionAuth.cookie_name))
        response.delete_cookie(SessionAuth.cookie_name, path="/")
        return {"authenticated": False}

    @app.get("/api/auth/session")
    async def session(request: Request):
        email = auth.authenticate(request.cookies.get(SessionAuth.cookie_name))
        return {"authenticated": bool(email), "email": email, "configured": auth.configured}

    @app.get("/api/crypto/trade-plans/current")
    async def current_trade_plans():
        return {"items": list_trade_plans(resolved.db_path, 20)}

    @app.post("/api/crypto/trade-plans")
    async def create_trade_plan(payload: dict[str, Any]):
        """Store a research draft and immediately pass it through EVAL.

        This endpoint creates no order and has no account or wallet access.
        """
        draft = TradePlanDraft.from_mapping(payload)
        result = EvaluationAgent(
            resolved.db_path,
            factor_registry,
            model_registry,
            additional_factor_ids=meme_factor_registry.ids,
        ).evaluate(draft)
        evaluation = result.to_mapping()
        instruction = getattr(app.state, "realtime_supervisor").accept_evaluation(evaluation)
        return {"plan": draft.to_mapping(), "evaluation": evaluation, **instruction}

    @app.get("/api/crypto/instructions/current")
    @app.get("/api/instructions/current")
    async def current_instructions():
        return {"items": list_current_instructions(resolved.db_path, 100), "source": "eval_only"}

    @app.get("/api/crypto/instructions/history")
    @app.get("/api/instructions/history")
    async def instruction_history():
        return {"items": list_instructions(resolved.db_path, 200), "source": "eval_only"}

    @app.get("/api/crypto/instructions/{instruction_id}")
    @app.get("/api/instructions/{instruction_id}")
    async def instruction_detail(instruction_id: str):
        value = get_instruction(resolved.db_path, instruction_id)
        if value is None:
            raise HTTPException(status_code=404, detail="research instruction not found")
        return value

    @app.get("/api/crypto/runtime/supervisor-status")
    @app.get("/api/runtime/supervisor-status")
    async def supervisor_status():
        supervisor = getattr(app.state, "realtime_supervisor", None)
        return supervisor.status() if supervisor is not None else {"status": "not_started", "order_submission": False}

    @app.get("/api/crypto/runtime/signal-status")
    async def signal_status():
        runtime = getattr(app.state, "signal_runtime", None)
        return runtime.status() if runtime is not None else {"status": "not_started", "order_submission": False}

    @app.get("/api/crypto/trade-plans/history")
    async def trade_plan_history():
        return {"items": list_trade_plans(resolved.db_path, 100)}

    @app.get("/api/crypto/trade-plans/{plan_id}")
    async def trade_plan_detail(plan_id: str):
        value = get_trade_plan(resolved.db_path, plan_id)
        if value is None:
            raise HTTPException(status_code=404, detail="交易计划不存在。")
        return value

    @app.get("/api/crypto/roll/current")
    async def current_rolls():
        return {"items": list_current_roll_decisions(resolved.db_path, 100), "strategy_version": "crypto_roll_v1.0.0", "research_only": True}

    @app.get("/api/crypto/roll/history")
    async def roll_history():
        return {"items": list_roll_decisions(resolved.db_path, 200), "research_only": True}

    @app.get("/api/crypto/roll-journal")
    @app.get("/api/crypto/roll/ledger")
    async def roll_ledger():
        return {"items": list_roll_ledger(resolved.db_path, 200), "research_only": True}

    @app.post("/api/crypto/roll/evaluate")
    async def evaluate_crypto_roll(payload: dict[str, Any]):
        try:
            roll_input = RollInput.from_mapping(payload)
            decision = evaluate_roll(roll_input)
            saved, created = save_roll_decision(resolved.db_path, decision)
            evaluation = None
            trade_plan = payload.get("trade_plan")
            if isinstance(trade_plan, dict):
                plan_payload = dict(trade_plan)
                plan_payload.setdefault("asset_id", roll_input.asset_id)
                plan_payload.setdefault("symbol", roll_input.symbol)
                plan_payload.setdefault("asset_type", roll_input.asset_type)
                plan_payload.setdefault("strategy_version", "crypto_roll_v1.0.0")
                plan_payload.setdefault("factor_snapshot_hash", roll_input.feature_snapshot_id)
                plan_payload.setdefault("source_snapshot_ids", list(roll_input.source_snapshot_ids))
                evaluation = EvaluationAgent(
                    resolved.db_path,
                    factor_registry,
                    model_registry,
                    additional_factor_ids=meme_factor_registry.ids,
                ).evaluate(TradePlanDraft.from_mapping(plan_payload)).to_mapping()
            return {
                "decision": saved,
                "evaluation": evaluation,
                "created": created,
                "execution_enabled": False,
                "research_only": True,
                "eval_authority": "EVAL only",
            }
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"roll input invalid: {exc}") from exc

    @app.post("/api/crypto/roll/feature-packet")
    async def create_roll_feature_packet(payload: dict[str, Any]):
        try:
            input_payload = dict(payload.get("roll_input") or payload)
            decision = evaluate_roll(RollInput.from_mapping(input_payload))
            packet = build_roll_feature_packet_from_db(
                resolved.db_path,
                input_payload,
                decision=decision,
                bayesian=payload.get("bayesian"),
                monte_carlo=payload.get("monte_carlo"),
                validation=payload.get("validation"),
                model=payload.get("model"),
                journal=payload.get("journal"),
            )
            return packet.to_mapping()
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"roll feature packet invalid: {exc}") from exc

    @app.post("/api/crypto/roll-journal/ocr-preview")
    @app.post("/api/crypto/roll/ledger/ocr-preview")
    async def preview_roll_journal(payload: dict[str, Any]):
        text = str(payload.get("text") or payload.get("ocr_text") or "")
        if not text.strip():
            raise HTTPException(status_code=422, detail="ocr preview text is required")
        preview = preview_roll_journal_text(text).to_mapping()
        return save_roll_journal_preview(resolved.db_path, preview)

    @app.post("/api/crypto/roll-journal/confirm")
    @app.post("/api/crypto/roll/ledger")
    async def append_roll_ledger(payload: dict[str, Any]):
        try:
            confirmation = None
            preview_id = str(payload.get("preview_id") or "")
            if preview_id:
                confirmation = confirm_roll_journal_preview(resolved.db_path, preview_id, payload)
            elif not bool(payload.get("confirm_write")):
                raise HTTPException(status_code=409, detail="journal write requires explicit confirmation")
            result = record_roll_ledger_event(
                resolved.db_path,
                asset_id=str(payload.get("asset_id") or ""),
                symbol=str(payload.get("symbol") or ""),
                event_type=str(payload.get("event_type") or "research_note"),
                realized_profit=float(payload.get("realized_profit")),
                rolled_capital=float(payload.get("rolled_capital")),
                remaining_risk=float(payload.get("remaining_risk")),
                occurred_at=str(payload.get("occurred_at") or ""),
                roll_id=str(payload.get("roll_id") or "") or None,
                user_note=str(payload.get("user_note") or ""),
            )
            return {"entry": result, "confirmation": confirmation, "execution_enabled": False, "research_only": True}
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"roll ledger input invalid: {exc}") from exc

    @app.get("/api/crypto/roll/{roll_id}")
    async def roll_detail(roll_id: str):
        value = get_roll_decision(resolved.db_path, roll_id)
        if value is None:
            raise HTTPException(status_code=404, detail="roll decision not found")
        return value

    @app.post("/api/crypto/research/bayesian")
    async def create_bayesian_snapshot(payload: dict[str, Any]):
        try:
            snapshot = PointInTimeFeatureSnapshot.create(
                asset_id=str(payload.get("asset_id") or ""),
                symbol=str(payload.get("symbol") or ""),
                signal_time=str(payload.get("signal_time") or ""),
                available_at=str(payload.get("available_at") or ""),
                source_status=str(payload.get("source_status") or "unknown"),
                features=dict(payload.get("features") or {}),
                source_snapshot_ids=tuple(str(item) for item in (payload.get("source_snapshot_ids") or ())),
                required_features=tuple(str(item) for item in (payload.get("required_features") or ())),
            )
            posterior = infer_bayesian_posterior(
                snapshot,
                training_window_start=str(payload.get("training_window_start") or "") or None,
                training_window_end=str(payload.get("training_window_end") or "") or None,
                training_dataset_hash=str(payload.get("training_dataset_hash") or ""),
                random_seed=payload.get("random_seed"),
            )
            saved = save_bayesian_posterior(resolved.db_path, snapshot, posterior)
            return {**saved, "research_only": True, "eval_authority": "EVAL only"}
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"bayesian snapshot invalid: {exc}") from exc

    @app.get("/api/crypto/research/bayesian/snapshots/{snapshot_id}")
    async def bayesian_detail(snapshot_id: str):
        value = get_bayesian_posterior(resolved.db_path, snapshot_id)
        if value is None:
            raise HTTPException(status_code=404, detail="bayesian snapshot not found")
        return value

    @app.get("/api/crypto/research/bayesian/{asset_id:path}")
    async def latest_bayesian(asset_id: str):
        item = latest_bayesian_posterior(resolved.db_path, asset_id)
        return {"status": "available" if item else "not_collected", "item": item, "research_only": True}

    @app.post("/api/crypto/research/monte-carlo")
    async def create_monte_carlo(payload: dict[str, Any]):
        try:
            raw_config = dict(payload.get("config") or {})
            allowed_config = {key: raw_config[key] for key in (
                "horizons_days", "paths", "block_size", "seed", "target_return", "stop_return",
                "ruin_return", "instrument_type", "instrument_id", "instrument_data_status",
                "underlying_proxy_used", "daily_leverage", "management_fee_bps",
                "tracking_error_bps", "spread_bps", "slippage_bps",
            ) if key in raw_config}
            regime_labels = [str(item) for item in (payload.get("regime_labels") or ())]
            target_regime = str(payload.get("target_regime") or "") or None
            result = simulate_monte_carlo(
                list(payload.get("returns") or ()),
                config=MonteCarloConfig(**allowed_config),
                regime_labels=regime_labels or None,
                target_regime=target_regime,
            )
            saved = save_monte_carlo_result(
                resolved.db_path,
                asset_id=str(payload.get("asset_id") or ""),
                symbol=str(payload.get("symbol") or ""),
                as_of_time=str(payload.get("as_of_time") or "") or None,
                result=result,
            )
            return {**saved, "research_only": True, "eval_authority": "EVAL only"}
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"monte carlo input invalid: {exc}") from exc

    @app.get("/api/crypto/research/monte-carlo/runs/{run_id}")
    async def monte_carlo_detail(run_id: str):
        value = get_monte_carlo_result(resolved.db_path, run_id)
        if value is None:
            raise HTTPException(status_code=404, detail="monte carlo run not found")
        return value

    @app.get("/api/crypto/research/monte-carlo/{asset_id:path}")
    async def latest_monte_carlo(asset_id: str):
        item = latest_monte_carlo_result(resolved.db_path, asset_id)
        return {"status": "available" if item else "not_collected", "item": item, "research_only": True}

    @app.post("/api/crypto/validation/roll-runs")
    async def create_roll_validation_run(payload: dict[str, Any]):
        try:
            raw_series = payload.get("series") or {}
            if not isinstance(raw_series, dict) or not raw_series:
                raise ValueError("series must be a non-empty symbol to bars mapping")
            series = {
                str(symbol): tuple(RollBar.from_mapping(item) for item in values)
                for symbol, values in raw_series.items()
                if isinstance(values, list)
            }
            raw_config = dict(payload.get("config") or {})
            allowed_config = {key: raw_config[key] for key in (
                "target_return", "stop_return", "max_hold_bars", "fee_bps_per_side",
                "slippage_bps_per_side", "train_ratio", "validation_ratio", "embargo_bars",
                "bootstrap_iterations", "bootstrap_seed", "oos_folds",
            ) if key in raw_config}
            report = run_roll_walk_forward(series, config=RollValidationConfig(**allowed_config))
            run_id = save_roll_validation_report(resolved.db_path, report)
            return {"status": "created", "run_id": run_id, "report": report, "research_only": True}
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"roll validation input invalid: {exc}") from exc

    @app.post("/api/crypto/validation/roll-runs/from-parquet")
    async def create_roll_validation_run_from_parquet(payload: dict[str, Any]):
        """Run the frozen roll policy from persisted closed bars only."""

        try:
            raw_symbols = payload.get("symbols")
            symbols = tuple(str(item).upper() for item in raw_symbols) if isinstance(raw_symbols, list) else None
            interval = str(payload.get("interval") or "1h").strip().lower()
            min_bars = max(55, int(payload.get("min_bars") or 220))
            max_hold_bars = max(1, int(payload.get("max_hold_bars") or 24))
            include_derivatives = bool(payload.get("include_derivatives"))
            dataset = load_parquet_validation_dataset(
                resolved.data_dir,
                symbols=symbols,
                interval=interval,
                min_bars=min_bars,
                include_derivatives=include_derivatives,
            )
            if not dataset.series:
                return {
                    "status": "NO_GO",
                    "reason": "no eligible closed-bar series",
                    "dataset_coverage": dataset.coverage,
                    "research_only": True,
                }
            suffix = interval[-1:].lower()
            unit_minutes = {"m": 1, "h": 60, "d": 1440}.get(suffix)
            if unit_minutes is None:
                raise ValueError("interval must end with m, h or d")
            interval_minutes = max(1, int(interval[:-1]) * unit_minutes)
            roll_series, roll_coverage = build_roll_series_from_validation(
                dataset.series,
                source_dataset_id=str(dataset.coverage.get("dataset_hash") or "unknown"),
                interval_minutes=interval_minutes,
                min_history_bars=min_bars,
            )
            report = run_roll_walk_forward(
                roll_series,
                config=RollValidationConfig(
                    max_hold_bars=max_hold_bars,
                    bootstrap_iterations=max(100, int(payload.get("bootstrap_iterations") or 1000)),
                ),
            )
            report["dataset_coverage"] = dataset.coverage
            report["roll_input_coverage"] = roll_coverage
            report["source_contract"] = "closed_binance_spot_parquet_only"
            run_id = save_roll_validation_report(resolved.db_path, report)
            return {
                "status": "created",
                "run_id": run_id,
                "report": report,
                "research_only": True,
            }
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"roll Parquet validation input invalid: {exc}") from exc

    @app.get("/api/crypto/validation/roll-latest")
    async def roll_validation_latest():
        report = latest_roll_validation_report(resolved.db_path)
        return {"status": "available" if report else "not_collected", "report": report, "research_only": True}

    @app.get("/api/crypto/validation/roll-runs/{run_id}")
    async def roll_validation_detail(run_id: str):
        report = get_roll_validation_report(resolved.db_path, run_id)
        if report is None:
            raise HTTPException(status_code=404, detail="roll validation run not found")
        return {"run_id": run_id, "report": report, "research_only": True}

    @app.get("/api/crypto/shadow/summary")
    async def shadow_observation_summary():
        report = latest_roll_validation_report(resolved.db_path)
        validation_status = str((report or {}).get("validation_gate", {}).get("status") or "NO_GO")
        return shadow_summary(resolved.db_path, validation_gate_status=validation_status)

    @app.get("/api/crypto/shadow/observations")
    async def shadow_observations(limit: int = 100):
        report = latest_roll_validation_report(resolved.db_path)
        validation_status = str((report or {}).get("validation_gate", {}).get("status") or "NO_GO")
        return {
            "items": list_shadow_observations(resolved.db_path, limit),
            "summary": shadow_summary(resolved.db_path, validation_gate_status=validation_status),
            "research_only": True,
        }

    @app.post("/api/crypto/shadow/observations")
    async def create_shadow_observation(payload: dict[str, Any]):
        try:
            action = str(payload.get("action") or "").upper()
            # Blocked/waiting/invalidated rows are useful audit observations,
            # but an active shadow action must be explicitly released by EVAL.
            if action not in {"DATA_BLOCKED", "WAIT", "INVALIDATED"}:
                evaluation_id = str(payload.get("evaluation_id") or "")
                evaluation = get_evaluation(resolved.db_path, evaluation_id) if evaluation_id else None
                if not evaluation or not bool(evaluation.get("allowed_shadow")):
                    raise HTTPException(status_code=409, detail="shadow observation requires an EVAL-approved shadow decision")
            value, created = save_shadow_observation(resolved.db_path, payload)
            return {"observation": value, "created": created, "research_only": True}
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"shadow observation invalid: {exc}") from exc

    @app.get("/api/crypto/shadow/{observation_id}/audit")
    async def shadow_observation_audit(observation_id: str):
        if get_shadow_observation(resolved.db_path, observation_id) is None:
            raise HTTPException(status_code=404, detail="shadow observation not found")
        return {"items": list_shadow_audit_events(resolved.db_path, observation_id), "research_only": True}

    @app.get("/api/crypto/shadow/{observation_id}")
    async def shadow_observation_detail(observation_id: str):
        value = get_shadow_observation(resolved.db_path, observation_id)
        if value is None:
            raise HTTPException(status_code=404, detail="shadow observation not found")
        return value

    @app.post("/api/crypto/shadow/{observation_id}/review")
    async def review_shadow(observation_id: str, payload: dict[str, Any]):
        try:
            return review_shadow_observation(
                resolved.db_path,
                observation_id,
                user_status=str(payload.get("user_status") or ""),
                user_note=str(payload.get("user_note") or ""),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="shadow observation not found") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"shadow review invalid: {exc}") from exc

    @app.post("/api/crypto/shadow/{observation_id}/outcome")
    async def complete_shadow_outcome(observation_id: str, payload: dict[str, Any]):
        try:
            return record_shadow_outcome(
                resolved.db_path,
                observation_id,
                outcome_status=str(payload.get("outcome_status") or ""),
                outcome=dict(payload.get("outcome") or {}),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="shadow observation not found") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"shadow outcome invalid: {exc}") from exc

    @app.get("/api/crypto/evaluations/latest")
    async def evaluations_latest():
        return {"items": latest_evaluations(resolved.db_path, 50)}

    @app.get("/api/crypto/models")
    async def models():
        return {"items": model_registry.list(100), "execution_enabled": False}

    @app.get("/api/crypto/models/{model_id}")
    async def model_detail(model_id: str):
        value = model_registry.get(model_id)
        if value is None:
            raise HTTPException(status_code=404, detail="model artifact not found")
        allowed, reasons, _ = model_registry.evidence_gate(model_id)
        return {**value, "evidence_gate": {"passed": allowed, "reasons": reasons}}

    @app.get("/api/crypto/evaluations/{evaluation_id}")
    async def evaluation_detail(evaluation_id: str):
        value = get_evaluation(resolved.db_path, evaluation_id)
        if value is None:
            raise HTTPException(status_code=404, detail="评估记录不存在。")
        return value

    @app.get("/api/crypto/evaluations/{evaluation_id}/advisories")
    async def evaluation_advisories(evaluation_id: str):
        if get_evaluation(resolved.db_path, evaluation_id) is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        return {"items": list_advisory_reviews(resolved.db_path, evaluation_id, 50), "authority": "EVAL"}

    @app.post("/api/crypto/evaluations/{evaluation_id}/advisory")
    async def evaluation_advisory(evaluation_id: str, payload: dict[str, Any]):
        evaluation = get_evaluation(resolved.db_path, evaluation_id)
        if evaluation is None:
            raise HTTPException(status_code=404, detail="evaluation not found")
        advisory = payload.get("advisory") if isinstance(payload.get("advisory"), dict) else payload
        return save_advisory_review(
            resolved.db_path,
            evaluation,
            dict(advisory),
            factor_registry.ids | meme_factor_registry.ids,
            provider=str(payload.get("provider") or "local_advisory"),
            model=str(payload.get("model") or "deterministic_contract"),
        )

    @app.post("/api/crypto/evaluations/{plan_id}/rerun")
    async def evaluation_rerun(plan_id: str):
        try:
            return EvaluationAgent(
                resolved.db_path,
                factor_registry,
                model_registry,
                additional_factor_ids=meme_factor_registry.ids,
            ).rerun(plan_id).to_mapping()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="交易计划不存在。") from exc

    @app.get("/api/crypto/alerts")
    async def alerts():
        return {
            "items": list_evaluated_notifications(resolved.db_path, 100),
            "source": "eval_only",
            "delivery_enabled": bool(resolved.notifications_enabled),
        }

    @app.get("/api/crypto/providers/status")
    async def providers_status():
        return {"providers": _current_provider_health(), "dex_discovery": getattr(getattr(app.state, "dex_discovery_runtime", None), "status", lambda: {"status": "disabled"})(), "symbols": list(resolved.core_symbols), "market_data_only": True}

    @app.get("/api/crypto/evidence/capabilities")
    async def evidence_capabilities():
        return evidence_source_capabilities()

    @app.get("/api/crypto/evidence/coverage")
    async def external_evidence_coverage():
        return evidence_coverage(
            resolved.db_path,
            tuple(f"asset:{symbol.lower()}" for symbol in SUPPORTED_EVIDENCE_ASSETS),
        )

    @app.post("/api/crypto/evidence")
    async def save_external_evidence(payload: dict[str, Any]):
        try:
            snapshot = normalize_provider_evidence(
                dict(payload.get("values") or {}),
                asset_id=str(payload.get("asset_id") or ""),
                symbol=str(payload.get("symbol") or ""),
                category=str(payload.get("category") or ""),
                source=str(payload.get("source") or ""),
                source_status=str(payload.get("source_status") or "unknown"),
                source_time=str(payload.get("source_time") or "") or None,
                published_at=str(payload.get("published_at") or "") or None,
                available_at=str(payload.get("available_at") or ""),
            )
            return {"snapshot": save_evidence_snapshot(resolved.db_path, snapshot), "research_only": True}
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"external evidence invalid: {exc}") from exc

    @app.post("/api/crypto/evidence/fetch-configured")
    async def fetch_configured_external_evidence(payload: dict[str, Any]):
        """Fetch an optional research feed; missing fields remain N/A."""

        source = str(payload.get("source") or "")
        category = str(payload.get("category") or "")
        symbol = str(payload.get("symbol") or "")
        asset_id = str(payload.get("asset_id") or f"asset:{symbol.lower()}")
        if source == "official_etf_feed":
            url = resolved.etf_evidence_url
        elif source == "onchain_metrics_feed":
            url = resolved.onchain_evidence_url
        else:
            url = ""
        try:
            result = await asyncio.to_thread(
                fetch_configured_evidence,
                url=url,
                source=source,
                category=category,
                asset_id=asset_id,
                symbol=symbol,
            )
            snapshot = result.get("snapshot") or {}
            if snapshot:
                save_evidence_snapshot(resolved.db_path, normalize_provider_evidence(
                    snapshot.get("values") or {},
                    source=source,
                    category=category,
                    asset_id=asset_id,
                    symbol=symbol,
                source_status=snapshot.get("source_status") or "provider_unavailable",
                source_version=snapshot.get("source_version") or source,
                available_at=snapshot.get("available_at") or "",
                source_time=snapshot.get("source_time"),
                published_at=snapshot.get("published_at"),
                collected_at=snapshot.get("collected_at"),
                ))
            return result
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"configured evidence invalid: {exc}") from exc

    @app.post("/api/crypto/evidence/fetch-public")
    async def fetch_public_external_evidence(payload: dict[str, Any]):
        """Fetch a registered public source without account credentials."""

        source = str(payload.get("source") or "binance_public_derivatives")
        default_category = "market_structure" if source == "binance_public_market_structure" else "exchange_derivatives"
        category = str(payload.get("category") or default_category)
        symbol = str(payload.get("symbol") or ("BTC" if source == "binance_public_market_structure" else ""))
        asset_id = str(payload.get("asset_id") or f"asset:{symbol.lower()}")
        if source == "binance_public_market_structure":
            if category != "market_structure":
                raise HTTPException(status_code=422, detail="Binance market structure source supports market_structure only")
            latest_regime = getattr(getattr(app.state, "market_regime_runtime", None), "latest", lambda: None)() or {}
            result = await asyncio.to_thread(
                fetch_binance_market_structure_evidence,
                asset_id=asset_id or "asset:btc",
                symbol=symbol or "BTC",
                universe_symbols=resolved.core_symbols,
            )
            saved = save_evidence_snapshot(resolved.db_path, result.snapshot)
            return {
                **result.to_mapping(),
                "snapshot": saved,
                "regime_context": {
                    "regime": latest_regime.get("regime"),
                    "as_of_time": latest_regime.get("as_of_time"),
                    "source": "market_regime_runtime",
                },
            }
        if source == "defillama_public":
            if category not in {"onchain", "protocol_metric"}:
                raise HTTPException(status_code=422, detail="DefiLlama public source supports on-chain and protocol metrics only")
            result = await asyncio.to_thread(
                DefiLlamaPublicAdapter().fetch,
                asset_id=asset_id,
                symbol=symbol,
                category=category,
                enabled=resolved.providers.defillama,
            )
            saved = save_evidence_snapshot(resolved.db_path, result.snapshot)
            return {**result.to_mapping(), "snapshot": saved, "provider_enabled": resolved.providers.defillama}
        if source not in {"binance_public_derivatives", "okx_public_derivatives"} or category != "exchange_derivatives":
            raise HTTPException(status_code=422, detail="only registered public evidence sources are available")
        try:
            collector = fetch_binance_derivatives_evidence if source == "binance_public_derivatives" else fetch_okx_derivatives_evidence
            result = await asyncio.to_thread(
                collector,
                asset_id=asset_id,
                symbol=symbol,
            )
            saved = save_evidence_snapshot(resolved.db_path, result.snapshot)
            return {**result.to_mapping(), "snapshot": saved, "research_only": True}
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"public evidence invalid: {exc}") from exc

    @app.post("/api/crypto/evidence/fetch-coinglass")
    async def fetch_coinglass_external_evidence(payload: dict[str, Any]):
        """Fetch optional CoinGlass evidence without exposing credentials."""

        category = str(payload.get("category") or "exchange_derivatives").lower()
        symbol = str(payload.get("symbol") or "").upper()
        asset_id = str(payload.get("asset_id") or f"asset:{symbol.lower()}")
        if category not in {"exchange_derivatives", "etf_flow", "onchain", "whale"} or not symbol or not asset_id:
            raise HTTPException(status_code=422, detail="CoinGlass requires a supported category and symbol")
        api_key = resolved.coinglass_api_key if resolved.providers.coinglass else ""
        adapter = CoinGlassPublicAdapter(api_key=api_key)
        result = await asyncio.to_thread(
            adapter.fetch,
            asset_id=asset_id,
            symbol=symbol,
            category=category,
        )
        saved = save_evidence_snapshot(resolved.db_path, result.snapshot)
        return {
            **result.to_mapping(),
            "snapshot": saved,
            "provider_enabled": resolved.providers.coinglass,
            "research_only": True,
        }

    @app.get("/api/crypto/assets/{asset_id:path}/evidence/history")
    async def asset_evidence_history(asset_id: str, limit: int = 50):
        return {"items": list_latest_evidence(resolved.db_path, asset_id, limit), "research_only": True}

    @app.get("/api/crypto/assets/{asset_id:path}/evidence")
    async def asset_evidence(asset_id: str):
        return evidence_bundle(resolved.db_path, asset_id)

    @app.get("/api/crypto/data/coverage")
    async def data_coverage():
        runtime = getattr(app.state, "market_runtime", None)
        storage = runtime.coverage() if runtime else {"storage": {"status": "not_collected"}, "in_memory_instruments": []}
        from ..db.migrations import connect

        storage_streams = {
            str(item.get("instrument_id")): item
            for item in storage.get("storage", {}).get("streams", [])
            if item.get("instrument_id")
        }
        assets_by_id: dict[str, dict[str, Any]] = {}
        with connect(resolved.db_path) as conn:
            rows = conn.execute(
                """
                SELECT a.asset_id, a.symbol, a.asset_kind, a.status AS asset_status,
                       i.instrument_id, i.venue_id, i.market_type,
                       i.provider_symbol, i.quote_asset, i.status AS instrument_status
                FROM crypto_assets a
                LEFT JOIN crypto_instruments i ON i.asset_id=a.asset_id
                ORDER BY a.symbol, i.instrument_id
                """
            ).fetchall()
        for row in rows:
            asset = assets_by_id.setdefault(row["asset_id"], {
                "asset_id": row["asset_id"],
                "symbol": row["symbol"],
                "asset_kind": row["asset_kind"],
                "status": row["asset_status"],
                "instruments": [],
            })
            if row["instrument_id"]:
                stream = storage_streams.get(row["instrument_id"])
                asset["instruments"].append({
                    "instrument_id": row["instrument_id"],
                    "venue": row["venue_id"],
                    "market_type": row["market_type"],
                    "provider_symbol": row["provider_symbol"],
                    "quote_asset": row["quote_asset"],
                    "status": row["instrument_status"],
                    "coverage": stream or {"status": "not_collected", "instrument_id": row["instrument_id"]},
                })
        required_symbols = sorted({str(symbol).strip().upper() for symbol in resolved.core_symbols if str(symbol).strip()})
        eligible_symbols = sorted({
            str(item.get("provider_symbol") or "").upper()
            for asset in assets_by_id.values()
            for item in asset["instruments"]
            if item.get("venue") == "binance"
            and item.get("market_type") == "spot"
            and item.get("provider_symbol")
            and "kline" in (item.get("coverage") or {}).get("event_types", [])
            and float((item.get("coverage") or {}).get("span_hours") or 0.0) >= 23.0
        })
        missing_symbols = sorted(set(required_symbols) - set(eligible_symbols))
        persisted_ratio = len(eligible_symbols) / len(required_symbols) if required_symbols else 0.0
        coverage_gate = {
            "status": "PASS" if not missing_symbols else "NO_GO",
            "required_symbols": required_symbols,
            "eligible_symbols": eligible_symbols,
            "missing_symbols": missing_symbols,
            "coverage_ratio": round(persisted_ratio, 6),
            "minimum_span_hours": 23.0,
            "evidence_scope": "persisted_parquet_span",
            "note": "This is storage coverage evidence; it is not proof of one uninterrupted collector session.",
        }
        continuous_gate: dict[str, Any]
        session = read_collection_session(resolved.outputs_dir)
        if session.get("status") == "completed":
            continuous_gate = session.get("collection_gate") or {
                "status": "NO_GO",
                "evidence_scope": "independent_collector_session",
                "failed_checks": ["invalid_collection_report"],
            }
        elif session.get("status") == "stale":
            continuous_gate = {
                "status": "NO_GO",
                "evidence_scope": "independent_collector_session",
                "failed_checks": list(session.get("failed_checks") or ["collector_stale"]),
                "heartbeat": session,
            }
        else:
            continuous_gate = {
                "status": "PENDING",
                "evidence_scope": "independent_collector_session",
                "failed_checks": ["collector_report_pending"],
                "heartbeat": session,
            }
        return {
            "status": storage.get("storage", {}).get("status", "not_collected"),
            "providers": provider_health(resolved, getattr(app.state, "provider_supervisor", None)),
            "assets": list(assets_by_id.values()),
            "registry": {
                "asset_count": len(assets_by_id),
                "instrument_count": sum(len(item["instruments"]) for item in assets_by_id.values()),
            },
            "coverage_gate": coverage_gate,
            "continuous_collection_gate": continuous_gate,
            "storage": storage,
            "note": "覆盖率只统计已经落地的公开行情，不代表策略或 Paper 证据。",
        }

    @app.get("/api/crypto/data/snapshots/{snapshot_id}")
    async def data_snapshot(snapshot_id: str):
        value = DataTrustStore(resolved.db_path).get(snapshot_id)
        if value is None:
            raise HTTPException(status_code=404, detail="数据快照不存在。")
        return value

    @app.get("/api/crypto/factors/registry")
    async def factor_registry_endpoint():
        factor_registry.register()
        return {
            "factor_version": factor_registry.definitions[0].factor_version if factor_registry.definitions else None,
            "items": factor_registry.list_definitions(),
            "registered_factor_ids": sorted(factor_registry.ids),
            "meme_factor_version": meme_factor_registry.factor_version,
            "meme_registered_factor_ids": sorted(meme_factor_registry.ids),
            "llm_can_modify": False,
        }

    @app.get("/api/crypto/assets/{asset_id}/factors/current")
    async def current_factor_snapshot(asset_id: str):
        snapshot = factor_registry.latest_snapshot(asset_id)
        if snapshot is None:
            return {
                "asset_id": asset_id,
                "status": "not_collected",
                "factor_version": factor_registry.definitions[0].factor_version if factor_registry.definitions else None,
                "items": [],
            }
        return {"status": "available", **snapshot}

    @app.get("/api/crypto/dex/pairs/latest")
    async def latest_dex_pairs(limit: int = 100):
        migrate(resolved.db_path)
        from ..db.migrations import connect

        with connect(resolved.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM crypto_dex_market_snapshots ORDER BY source_time DESC, fetched_at DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            items.append(item)
        return {"status": "available" if items else "not_collected", "items": items}

    @app.get("/api/crypto/assets/{asset_id}/security/latest")
    async def latest_security_snapshot(asset_id: str):
        migrate(resolved.db_path)
        from ..db.migrations import connect

        with connect(resolved.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM crypto_token_security_snapshots WHERE asset_id=? ORDER BY source_time DESC, fetched_at DESC LIMIT 1",
                (asset_id,),
            ).fetchone()
        if row is None:
            return {"asset_id": asset_id, "status": "not_collected", "eval_allowed": False}
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        item["eval_allowed"] = item["status"] == "passed"
        return item

    @app.get("/api/crypto/assets/{asset_id}/holders/latest")
    async def latest_holder_snapshot(asset_id: str):
        value = DexSecurityStore(resolved.db_path).latest_holder(asset_id)
        if value is None:
            return {"asset_id": asset_id, "status": "not_collected", "data_only": True, "eval_allowed": False}
        return {"status": "available", "data_only": True, "eval_allowed": False, **value}

    @app.get("/api/crypto/assets/{asset_id}/meme-factors")
    async def meme_factors(asset_id: str, as_of: str | None = None):
        migrate(resolved.db_path)
        from ..db.migrations import connect

        with connect(resolved.db_path) as conn:
            query = """
                SELECT d.source_time, d.price_usd, d.liquidity_usd, d.volume_5m_usd,
                       d.buys_5m, d.sells_5m,
                       COALESCE((
                         SELECT s.status
                         FROM crypto_token_security_snapshots s
                         WHERE s.asset_id=p.base_asset_id
                           AND s.source_time <= d.source_time
                         ORDER BY s.source_time DESC, s.fetched_at DESC
                         LIMIT 1
                       ), 'unknown') AS security_status,
                       (
                         SELECT h.holder_count
                         FROM crypto_holder_snapshots h
                         WHERE h.asset_id=p.base_asset_id
                           AND h.source_time <= d.source_time
                         ORDER BY h.source_time DESC, h.created_at DESC
                         LIMIT 1
                       ) AS holder_count,
                       (
                         SELECT h.top10_concentration
                         FROM crypto_holder_snapshots h
                         WHERE h.asset_id=p.base_asset_id
                           AND h.source_time <= d.source_time
                         ORDER BY h.source_time DESC, h.created_at DESC
                         LIMIT 1
                       ) AS top10_concentration
                FROM crypto_dex_market_snapshots d
                JOIN crypto_liquidity_pools p ON p.pool_id=d.pool_id
                WHERE p.base_asset_id=?
            """
            params: list[Any] = [asset_id]
            if as_of:
                query += " AND d.source_time <= ?"
                params.append(as_of)
            query += " ORDER BY d.source_time ASC, d.fetched_at ASC LIMIT 500"
            rows = conn.execute(query, params).fetchall()
        if not rows:
            return {"asset_id": asset_id, "status": "not_collected"}
        observations = [MemeObservation(
            asset_id=asset_id,
            as_of=str(row["source_time"]),
            price_usd=row["price_usd"],
            liquidity_usd=row["liquidity_usd"],
            volume_5m_usd=row["volume_5m_usd"],
            buys_5m=row["buys_5m"],
            sells_5m=row["sells_5m"],
            holder_count=row["holder_count"],
            top10_concentration=row["top10_concentration"],
            security_status=str(row["security_status"] or "unknown"),
        ) for row in rows]
        return {"status": "available", **compute_meme_factors(observations, as_of=as_of).as_dict()}

    @app.get("/api/crypto/security/latest")
    async def latest_security_snapshots(limit: int = 20):
        migrate(resolved.db_path)
        from ..db.migrations import connect

        with connect(resolved.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM crypto_token_security_snapshots ORDER BY source_time DESC, fetched_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            item["eval_allowed"] = item["status"] == "passed"
            items.append(item)
        return {"status": "available" if items else "not_collected", "items": items, "eval_unknown_is_rejected": True}

    @app.get("/api/crypto/security/coverage")
    async def security_coverage():
        migrate(resolved.db_path)
        from ..db.migrations import connect

        with connect(resolved.db_path) as conn:
            total_assets = int(conn.execute(
                "SELECT COUNT(*) FROM crypto_token_contracts WHERE status != 'blocked'"
            ).fetchone()[0])
            checked_assets = int(conn.execute(
                "SELECT COUNT(DISTINCT asset_id) FROM crypto_token_security_snapshots"
            ).fetchone()[0])
            latest = conn.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM crypto_token_security_snapshots s
                WHERE fetched_at = (
                  SELECT MAX(s2.fetched_at)
                  FROM crypto_token_security_snapshots s2
                  WHERE s2.asset_id = s.asset_id
                )
                GROUP BY status
                ORDER BY status
                """
            ).fetchall()
        ratio = checked_assets / total_assets if total_assets else 0.0
        if not resolved.providers.goplus:
            status = "provider_disabled"
        elif checked_assets == 0:
            status = "not_collected"
        elif checked_assets < total_assets:
            status = "partial"
        else:
            status = "complete"
        return {
            "status": status,
            "provider": "goplus",
            "provider_enabled": resolved.providers.goplus,
            "provider_key_configured": bool(resolved.goplus_api_key),
            "token_assets": total_assets,
            "checked_assets": checked_assets,
            "coverage_ratio": round(ratio, 6),
            "latest_status_counts": {str(row["status"]): int(row["count"]) for row in latest},
            "unknown_security_eval_allowed": False,
        }

    @app.get("/api/crypto/universe/current")
    async def current_universe():
        migrate(resolved.db_path)
        from ..db.migrations import connect

        with connect(resolved.db_path) as conn:
            row = conn.execute("SELECT * FROM crypto_universe_snapshots ORDER BY as_of_time DESC LIMIT 1").fetchone()
        if row is None:
            return {"status": "not_collected", "items": []}
        value = dict(row)
        value["members"] = json.loads(value.pop("members_json"))
        return {"status": "available", **value}

    @app.get("/api/crypto/market-regime/current")
    async def current_market_regime():
        migrate(resolved.db_path)
        from ..db.migrations import connect

        with connect(resolved.db_path) as conn:
            row = conn.execute("SELECT * FROM crypto_market_regime_snapshots ORDER BY as_of_time DESC LIMIT 1").fetchone()
        if row is None:
            return {"regime": "DATA_CAUTION", "confidence": "low", "evidence": ["regime_snapshot_not_collected"]}
        value = dict(row)
        value["evidence"] = json.loads(value.pop("evidence_json"))
        value["data_snapshot_ids"] = json.loads(value.pop("data_snapshot_ids_json"))
        return value

    @app.get("/api/crypto/validation/latest")
    async def latest_validation():
        value = latest_validation_run(resolved.db_path)
        if value is None:
            return {"status": "not_collected", "items": []}
        value["report"].setdefault("validation_gate", evaluate_validation_gate(value["report"]))
        return {"status": "available", **value}

    @app.get("/api/crypto/validation/gate")
    async def latest_validation_gate():
        value = latest_validation_run(resolved.db_path)
        if value is None:
            return {"status": "not_collected", "validation_gate": None}
        return {
            "status": "available",
            "run_id": value["run_id"],
            "validation_gate": evaluate_validation_gate(value["report"]),
        }

    @app.get("/api/crypto/validation/model-benchmarks/latest")
    async def latest_model_benchmarks():
        value = latest_validation_run(resolved.db_path)
        if value is None:
            return {"status": "not_collected", "model_benchmarks": None}
        benchmark = value.get("report", {}).get("model_benchmarks")
        if not benchmark:
            return {
                "status": "not_collected",
                "run_id": value["run_id"],
                "model_benchmarks": None,
                "validation_gate": evaluate_validation_gate(value["report"]),
            }
        return {
            "status": "available",
            "run_id": value["run_id"],
            "model_benchmarks": benchmark,
            "validation_gate": evaluate_validation_gate(value["report"]),
        }

    @app.get("/api/crypto/paper-observations")
    async def paper_observations(limit: int = 100):
        return {"status": "available", "items": list_paper_observations(resolved.db_path, limit)}

    @app.post("/api/crypto/paper-observations")
    async def create_paper_observation_route(payload: dict[str, Any]):
        try:
            return create_paper_observation(resolved.db_path, payload)
        except PaperGateError as exc:
            raise HTTPException(status_code=409, detail=f"纸面观察未通过 EVAL：{exc}") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"纸面观察输入无效：{exc}") from exc

    @app.post("/api/crypto/paper-observations/{observation_id}/close")
    async def close_paper_observation_route(observation_id: str, payload: dict[str, Any]):
        try:
            return close_paper_observation(
                resolved.db_path,
                observation_id,
                exit_price=float(payload.get("exit_price")),
                exit_snapshot_id=str(payload.get("exit_snapshot_id") or ""),
                status=str(payload.get("status") or "CLOSED"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="纸面观察不存在。") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"纸面观察退出输入无效：{exc}") from exc

    @app.post("/api/crypto/validation/runs")
    async def create_validation_run(payload: dict[str, Any]):
        """Run a local deterministic replay; this never calls a broker."""
        try:
            raw_series = payload.get("series") or []
            if not raw_series:
                raise ValueError("series 不能为空。")

            def parse_bars(values: list[dict[str, Any]]) -> tuple[BacktestBar, ...]:
                return tuple(BacktestBar(
                    start_time=str(item["start_time"]),
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item.get("volume", 0.0)),
                ) for item in values)

            series = []
            for item in raw_series:
                benchmark_values = {
                    str(name): parse_bars(values)
                    for name, values in (item.get("benchmark_bars") or {}).items()
                }
                series.append(ValidationSeries(
                    asset_id=str(item["asset_id"]),
                    symbol=str(item["symbol"]),
                    bars=parse_bars(item.get("bars") or []),
                    benchmark_bars=benchmark_values,
                ))
            raw_backtest = payload.get("backtest") or {}
            allowed_backtest = {
                key: raw_backtest[key]
                for key in (
                    "setup_threshold", "stop_atr_multiple", "target_r_multiple",
                    "max_hold_bars", "fee_bps_per_side", "slippage_bps_per_side",
                    "min_history_bars",
                ) if key in raw_backtest
            }
            config = ValidationConfig(
                strategy_version=str(payload.get("strategy_version") or "crypto_early_v1.0.0"),
                dataset_version=str(payload.get("dataset_version") or "crypto_dataset_v1.0.0"),
                feature_scope=str(payload.get("feature_scope") or "full_realtime"),
                bar_interval=str(payload.get("bar_interval") or "1m"),
                train_ratio=float(payload.get("train_ratio", 0.60)),
                validation_ratio=float(payload.get("validation_ratio", 0.20)),
                embargo_bars=int(payload.get("embargo_bars", 8)),
                backtest=BacktestConfig(**allowed_backtest),
                bootstrap_iterations=int(payload.get("bootstrap_iterations", 1000)),
                bootstrap_seed=int(payload.get("bootstrap_seed", 7)),
                oos_folds=int(payload.get("oos_folds", 3)),
            )
            result = run_walk_forward_validation(
                series,
                registry=factor_registry,
                weights={str(key): float(value) for key, value in (payload.get("weights") or {}).items()},
                config=config,
            )
            report = result["report"]
            run_id = save_validation_run(
                resolved.db_path,
                strategy_version=config.strategy_version,
                dataset_version=config.dataset_version,
                split_config=report["split_config"],
                backtest_config=report["backtest_config"],
                status=report["test_evidence_status"],
                report=report,
                outcomes=result["outcomes"],
                partition_outcomes=result.get("partition_outcomes"),
                oos_outcomes_by_fold=result.get("oos_outcomes_by_fold"),
            )
            return {"status": "created", "run_id": run_id, "report": report}
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"验证输入无效：{exc}") from exc

    @app.post("/api/crypto/validation/runs/from-parquet")
    async def create_validation_run_from_parquet(payload: dict[str, Any]):
        """Replay only closed Binance spot Parquet data; never synthesize bars."""

        try:
            raw_symbols = payload.get("symbols")
            symbols = tuple(str(item).upper() for item in raw_symbols) if isinstance(raw_symbols, list) else None
            dataset = load_parquet_validation_dataset(
                resolved.data_dir,
                symbols=symbols,
                interval=str(payload.get("interval") or "1m"),
                min_bars=int(payload.get("min_bars", 55)),
                limit=int(payload.get("limit", 250_000)),
                include_derivatives=bool(payload.get("include_derivatives", False)),
            )
            if not dataset.series:
                return {
                    "status": "NO_GO",
                    "reason": "no eligible closed Binance spot series",
                    "dataset": dataset.coverage,
                    "report": None,
                }
            raw_backtest = payload.get("backtest") or {}
            allowed_backtest = {
                key: raw_backtest[key]
                for key in (
                    "setup_threshold", "stop_atr_multiple", "target_r_multiple",
                    "max_hold_bars", "fee_bps_per_side", "slippage_bps_per_side",
                    "min_history_bars",
                ) if key in raw_backtest
            }
            interval = str(payload.get("interval") or "1m")
            if "max_hold_bars" not in allowed_backtest:
                allowed_backtest["max_hold_bars"] = bars_for_duration(interval, hours=24)
            include_derivatives = bool(payload.get("include_derivatives", False))
            default_strategy_version = "crypto_historical_derivatives_v1.0.0" if include_derivatives else "crypto_historical_ohlcv_v1.0.0"
            default_scope = "ohlcv_plus_derivatives_limited" if include_derivatives else "ohlcv_only_limited"
            default_dataset_suffix = "derivatives" if include_derivatives else "ohlcv"
            config = ValidationConfig(
                strategy_version=str(payload.get("strategy_version") or default_strategy_version),
                dataset_version=str(payload.get("dataset_version") or f"parquet_{dataset.coverage['dataset_hash'][:16]}_{default_dataset_suffix}"),
                feature_scope=str(payload.get("feature_scope") or default_scope),
                bar_interval=interval,
                train_ratio=float(payload.get("train_ratio", 0.60)),
                validation_ratio=float(payload.get("validation_ratio", 0.20)),
                embargo_bars=int(payload.get("embargo_bars", 8)),
                backtest=BacktestConfig(**allowed_backtest),
                bootstrap_iterations=int(payload.get("bootstrap_iterations", 1000)),
                bootstrap_seed=int(payload.get("bootstrap_seed", 7)),
                oos_folds=int(payload.get("oos_folds", 3)),
            )
            raw_weights = payload.get("weights")
            if raw_weights:
                weights = {str(key): float(value) for key, value in raw_weights.items()}
            else:
                from ..strategy_scopes import HISTORICAL_DERIVATIVE_WEIGHTS, HISTORICAL_OHLCV_WEIGHTS

                weights = dict(HISTORICAL_DERIVATIVE_WEIGHTS if include_derivatives else HISTORICAL_OHLCV_WEIGHTS)
            result = run_walk_forward_validation(dataset.series, registry=factor_registry, weights=weights, config=config)
            report = result["report"]
            report["dataset_coverage"] = dataset.coverage
            if bool(payload.get("include_model_benchmarks", False)):
                report["model_benchmarks"] = run_model_benchmark(
                    result.get("partition_outcomes", {}),
                    feature_order=tuple(sorted(weights)),
                    dataset_hash=report["dataset_hash"],
                    strategy_version=config.strategy_version,
                )
            run_id = save_validation_run(
                resolved.db_path,
                strategy_version=config.strategy_version,
                dataset_version=config.dataset_version,
                split_config=report["split_config"],
                backtest_config=report["backtest_config"],
                status=report["test_evidence_status"],
                report=report,
                outcomes=result["outcomes"],
                partition_outcomes=result.get("partition_outcomes"),
                oos_outcomes_by_fold=result.get("oos_outcomes_by_fold"),
            )
            return {"status": "created", "run_id": run_id, "dataset": dataset.coverage, "report": report}
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"Parquet validation input invalid: {exc}") from exc

    @app.get("/api/crypto/assets/{asset_id}/market-snapshot")
    async def market_snapshot(asset_id: str):
        runtime = getattr(app.state, "market_runtime", None)
        if runtime is None:
            return {"asset_id": asset_id, "status": "unavailable"}
        candidates = runtime.buffer.instruments_for_asset(asset_id)
        if not candidates:
            return {"asset_id": asset_id, "status": "unavailable", "trust": "unavailable", "forming_candles_allowed_for_eval": False}
        return {"asset_id": asset_id, "status": "available", "instruments": [runtime.snapshot(item) for item in candidates], "forming_candles_allowed_for_eval": False}

    @app.get("/api/crypto/alerts/stream")
    async def alert_stream():
        queue = hub.subscribe()

        async def stream():
            try:
                yield "event: ready\ndata: {\"source\":\"eval_only\",\"delivery_enabled\":false}\n\n"
                while True:
                    message = await queue.get()
                    yield f"event: alert\ndata: {message}\n\n"
            finally:
                hub.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/crypto/alerts/{notification_id}/ack")
    async def alert_ack(notification_id: str):
        return {"acknowledged": acknowledge_notification(resolved.db_path, notification_id)}

    @app.get("/api/notifications/status")
    async def notifications():
        return notification_status(resolved, resolved.db_path)

    @app.get("/api/notifications/web-push/public-key")
    async def web_push_public_key():
        return {"configured": bool(resolved.web_push_public_key), "public_key": resolved.web_push_public_key or None}

    @app.post("/api/notifications/web-push/subscribe")
    async def web_push_subscribe(payload: WebPushSubscriptionRequest, request: Request):
        try:
            return save_web_push_subscription(resolved.db_path, request.state.user_email, payload.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/notifications/web-push/subscribe")
    async def web_push_unsubscribe(payload: WebPushRemoveRequest, request: Request):
        return {"removed": remove_web_push_subscription(resolved.db_path, request.state.user_email, payload.endpoint)}

    @app.post("/api/notifications/web-push/test")
    async def web_push_test(request: Request):
        payload = record_notification(resolved.db_path, severity="INFO", title="KQUANT Crypto 测试通知", body="这是只读研究终端的测试推送。", deep_link="/")
        delivery = deliver_web_push(resolved, resolved.db_path, payload)
        return {"notification_id": payload["notification_id"], **delivery}

    @app.get("/api/notifications/preferences")
    async def notification_preferences(request: Request):
        return get_notification_preferences(resolved.db_path, request.state.user_email)

    @app.put("/api/notifications/preferences")
    async def update_notification_preferences(payload: NotificationPreferencesRequest, request: Request):
        return set_notification_preferences(resolved.db_path, request.state.user_email, payload.model_dump())

    @app.get("/api/runtime/boundary")
    async def runtime_boundary():
        return {
            "read_only": True,
            "allowed": ["market_research", "paper_observation", "shadow_observation"],
            "forbidden": ["account_access", "wallet_access", "private_keys", "order_submission", "automatic_execution"],
            "eval_is_final_reviewer": True,
            "llm_is_advisory_only": True,
        }

    @app.get("/manifest.webmanifest")
    async def manifest():
        path = resolved.root_dir / "web" / "public" / "manifest.webmanifest"
        if path.exists():
            return FileResponse(path, media_type="application/manifest+json")
        return JSONResponse({"name": "KQUANT CRYPTO", "display": "standalone"})

    @app.get("/service-worker.js")
    async def service_worker():
        path = resolved.root_dir / "web" / "public" / "service-worker.js"
        if path.exists():
            return FileResponse(path, media_type="application/javascript")
        return Response("self.addEventListener('fetch',()=>{});", media_type="application/javascript")

    @app.get("/favicon.svg")
    async def favicon():
        path = resolved.root_dir / "web" / "public" / "favicon.svg"
        if path.exists():
            return FileResponse(path, media_type="image/svg+xml")
        return Response("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><rect width='64' height='64' rx='12' fill='#08111d'/><text x='12' y='42' fill='#6ad2ff' font-size='24'>KQ</text></svg>", media_type="image/svg+xml")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        path = _frontend_index(resolved)
        if path:
            return FileResponse(path)
        return HTMLResponse("<h1>KQUANT CRYPTO</h1><p>Read-only research terminal.</p>")

    @app.get("/{asset_path:path}")
    async def static_fallback(asset_path: str):
        path = resolved.web_dist_dir / asset_path
        if path.exists() and path.is_file():
            return FileResponse(path)
        index = _frontend_index(resolved)
        if index:
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="页面不存在。")

    return app


app = create_app()
