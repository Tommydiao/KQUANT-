from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from uuid import uuid4

from .config import ExecutionMode, ExecutionSettings
from .execution_models import AccountRiskSnapshot, ExecutionIntent, ExecutionRiskDecision, SymbolTradingRules
from .strategy_manifest import strategy_manifest


def _expired(timestamp: str, now: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC) <= now.astimezone(UTC)


def _round_down(value: float, step: float) -> float:
    if step <= 0:
        return max(0.0, float(value))
    decimal_value = Decimal(str(value))
    decimal_step = Decimal(str(step))
    return float((decimal_value / decimal_step).to_integral_value(rounding=ROUND_DOWN) * decimal_step)


def evaluate_execution_risk(
    intent: ExecutionIntent,
    account: AccountRiskSnapshot,
    rules: SymbolTradingRules,
    settings: ExecutionSettings,
    *,
    armed: bool,
    evaluation_decision: str,
    now: datetime | None = None,
) -> ExecutionRiskDecision:
    checked_at = now or datetime.now(UTC)
    blockers: list[str] = []
    warnings: list[str] = []

    if settings.mode == ExecutionMode.DISABLED:
        blockers.append("execution_disabled")
    if not settings.autotrade_enabled:
        blockers.append("autotrade_disabled")
    if not settings.credentials_configured:
        blockers.append("credentials_missing")
    if not armed:
        blockers.append("runtime_not_armed")
    if intent.validation_gate_status != "PASS":
        blockers.append("validation_gate_not_passed")
    if evaluation_decision != "SHADOW_ELIGIBLE":
        blockers.append("eval_not_shadow_eligible")
    if intent.symbol not in settings.symbols:
        blockers.append("symbol_not_allowlisted")
    if intent.market_type not in {"spot", "perpetual"}:
        blockers.append("unsupported_market_type")
    if intent.direction not in {"long", "short"}:
        blockers.append("unsupported_direction")
    if intent.market_type == "spot" and intent.direction != "long":
        blockers.append("spot_short_forbidden")
    if _expired(intent.expires_at, checked_at):
        blockers.append("intent_expired")
    manifest = strategy_manifest(intent.strategy_version)
    if manifest is None:
        blockers.append("strategy_not_registered")
    elif manifest.status not in {"frozen_baseline", "validated"}:
        blockers.append("strategy_not_validated")
    elif not manifest.executable:
        blockers.append("strategy_execution_not_supported")
    if not rules.tradable:
        blockers.append("symbol_not_tradable")

    if intent.entry_limit <= 0 or intent.stop_price <= 0 or intent.target_price <= 0:
        blockers.append("invalid_plan_prices")
    elif intent.direction == "long" and not (intent.stop_price < intent.entry_limit < intent.target_price):
        blockers.append("invalid_long_plan_geometry")
    elif intent.direction == "short" and not (intent.target_price < intent.entry_limit < intent.stop_price):
        blockers.append("invalid_short_plan_geometry")

    capital = min(max(0.0, account.equity_usdt), settings.live_capital_limit)
    if capital <= 0:
        blockers.append("capital_unavailable")
    if account.daily_realized_pnl_usdt <= -(capital * settings.daily_loss_fraction):
        blockers.append("daily_loss_limit_reached")
    if account.positions:
        blockers.append("existing_position_blocks_new_entry")
    if account.open_risk_usdt >= capital * settings.total_open_risk_fraction and capital > 0:
        blockers.append("total_open_risk_limit_reached")

    quantity = 0.0
    notional = 0.0
    risk_usdt = 0.0
    price_risk = abs(intent.entry_limit - intent.stop_price)
    if price_risk > 0 and capital > 0:
        requested_fraction = min(max(0.0, intent.requested_risk_fraction), settings.risk_per_trade_fraction)
        risk_budget = capital * requested_fraction
        raw_quantity = risk_budget / price_risk
        leverage = settings.max_leverage if intent.market_type == "perpetual" else 1
        raw_quantity = min(raw_quantity, capital * leverage / intent.entry_limit)
        quantity = _round_down(raw_quantity, rules.step_size)
        notional = quantity * intent.entry_limit
        risk_usdt = quantity * price_risk
    if quantity < rules.min_qty:
        blockers.append("minimum_quantity_not_met")
    if notional < rules.min_notional:
        blockers.append("minimum_notional_not_met")
    if risk_usdt > capital * settings.risk_per_trade_fraction + 1e-9:
        blockers.append("per_trade_risk_limit_exceeded")
    if account.open_risk_usdt + risk_usdt > capital * settings.total_open_risk_fraction + 1e-9:
        blockers.append("total_open_risk_limit_exceeded")
    if account.available_usdt <= 0:
        blockers.append("available_balance_unavailable")
    leverage = settings.max_leverage if intent.market_type == "perpetual" else 1
    required_balance = notional / leverage if leverage > 0 else notional
    if required_balance > account.available_usdt + 1e-9:
        blockers.append("insufficient_available_balance")
    if account.open_order_count:
        warnings.append("open_orders_require_reconciliation")

    return ExecutionRiskDecision(
        decision_id=f"risk_{uuid4().hex}",
        intent_id=intent.intent_id,
        allowed=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        warnings=tuple(dict.fromkeys(warnings)),
        quantity=quantity,
        estimated_notional=notional,
        estimated_risk_usdt=risk_usdt,
        capital_basis_usdt=capital,
        decided_at=checked_at.astimezone(UTC).isoformat(),
    )
