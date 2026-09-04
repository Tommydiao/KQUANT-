from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .binance_execution import BinanceCredentials, BinanceExecutionClient, BinanceExecutionError
from .config import ExecutionMode, ExecutionSettings
from .execution_store import (
    latest_validation_gate_for_strategy,
    list_execution_positions,
    list_execution_orders,
    list_orders_for_intent,
    local_daily_realized_pnl,
    record_kill_switch,
    register_strategy_manifests,
    save_reconciliation,
    save_risk_decision,
    testnet_release_gate,
)
from .execution_models import AccountRiskSnapshot, ExchangePosition, ExecutionIntent, SymbolTradingRules
from .execution_risk import evaluate_execution_risk
from .order_manager import BinanceOrderManager
from .strategy_manifest import STRATEGY_MANIFESTS


def parse_symbol_rules(payload: dict[str, Any], symbol: str, market_type: str) -> dict[str, Any]:
    target = next((item for item in payload.get("symbols", ()) if str(item.get("symbol")) == symbol), None)
    if target is None:
        raise ValueError("symbol_not_found_in_exchange_info")
    filters = {str(item.get("filterType")): item for item in target.get("filters", ())}
    lot = filters.get("LOT_SIZE", {})
    price = filters.get("PRICE_FILTER", {})
    notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
    minimum_notional = notional.get("minNotional", notional.get("notional", 0))
    return {
        "symbol": symbol,
        "market_type": market_type,
        "status": str(target.get("status") or "UNKNOWN"),
        "tradable": str(target.get("status") or "").upper() == "TRADING",
        "min_qty": float(lot.get("minQty") or 0.0),
        "step_size": float(lot.get("stepSize") or 0.0),
        "min_notional": float(minimum_notional or 0.0),
        "tick_size": float(price.get("tickSize") or 0.0),
    }


class ExecutionController:
    """Process-local execution arming and secret-free Binance operations."""

    def __init__(
        self,
        db_path: Path,
        settings: ExecutionSettings,
        *,
        client_factory: Callable[[], BinanceExecutionClient] | None = None,
    ):
        self.db_path = db_path
        self.settings = settings
        self._armed = False
        self._killed = False
        self._client_factory = client_factory or self._new_client
        register_strategy_manifests(db_path)

    @property
    def armed(self) -> bool:
        return self._armed and not self._killed

    def _new_client(self) -> BinanceExecutionClient:
        return BinanceExecutionClient(
            BinanceCredentials(self.settings.api_key, self.settings.api_secret),
            spot_base_url=self.settings.base_url("spot"),
            futures_base_url=self.settings.base_url("perpetual"),
        )

    def validation_gates(self) -> dict[str, Any]:
        return {
            manifest.strategy_version: latest_validation_gate_for_strategy(self.db_path, manifest.strategy_version)
            for manifest in STRATEGY_MANIFESTS
        }

    def status(self) -> dict[str, Any]:
        gates = self.validation_gates()
        validated = sorted(version for version, gate in gates.items() if gate and gate.get("status") == "PASS")
        blockers: list[str] = []
        if self.settings.mode == ExecutionMode.DISABLED:
            blockers.append("execution_disabled")
        if not self.settings.autotrade_enabled:
            blockers.append("autotrade_disabled")
        if not self.settings.credentials_configured:
            blockers.append("credentials_missing")
        if not validated:
            blockers.append("no_strategy_validation_gate_passed")
        release = testnet_release_gate(self.db_path)
        if self.settings.mode == ExecutionMode.LIVE and release["status"] != "PASS":
            blockers.append("testnet_release_gate_not_passed")
        if self._killed:
            blockers.append("kill_switch_active")
        return {
            "mode": self.settings.mode.value,
            "autotrade_enabled": self.settings.autotrade_enabled,
            "credentials_configured": self.settings.credentials_configured,
            "armed": self.armed,
            "kill_switch_active": self._killed,
            "symbols": list(self.settings.symbols),
            "validated_strategies": validated,
            "blockers": blockers,
            "limits": {
                "capital_usdt": self.settings.live_capital_limit,
                "risk_per_trade_fraction": self.settings.risk_per_trade_fraction,
                "daily_loss_fraction": self.settings.daily_loss_fraction,
                "total_open_risk_fraction": self.settings.total_open_risk_fraction,
                "max_leverage": self.settings.max_leverage,
                "max_entry_slippage_bps": self.settings.max_entry_slippage_bps,
            },
            "testnet_release_gate": release,
            "secrets_exposed": False,
        }

    def preflight(self) -> dict[str, Any]:
        """Run a read-only execution readiness check without arming orders."""

        status = self.status()
        checks: dict[str, bool] = {
            "execution_mode_selected": self.settings.mode != ExecutionMode.DISABLED,
            "autotrade_enabled": self.settings.autotrade_enabled,
            "credentials_configured": self.settings.credentials_configured,
            "strategy_validation_gate": bool(status["validated_strategies"]),
            "account_readable": False,
            "allowlisted_spot_rules_available": False,
        }
        account: dict[str, Any] = {
            "status": "not_checked",
            "reason": "credentials_or_mode_missing",
            "secrets_exposed": False,
        }
        rules: list[dict[str, Any]] = []
        network_error: str | None = None
        if checks["execution_mode_selected"] and checks["credentials_configured"]:
            try:
                account = self.account_summary()
                checks["account_readable"] = account.get("status") == "available"
                rules = self.exchange_rules()
                checks["allowlisted_spot_rules_available"] = any(
                    item.get("market_type") == "spot"
                    and item.get("symbol") in self.settings.symbols
                    and item.get("tradable") is True
                    and float(item.get("min_notional") or 0.0) <= self.settings.live_capital_limit
                    for item in rules
                )
            except Exception as exc:
                network_error = type(exc).__name__
                account = {
                    "status": "unavailable",
                    "reason": f"binance_read_only_preflight_failed:{network_error}",
                    "secrets_exposed": False,
                }
        blockers = [name for name, passed in checks.items() if not passed]
        return {
            "status": "PASS" if not blockers else "NO_GO",
            "mode": self.settings.mode.value,
            "armed": self.armed,
            "checks": checks,
            "blockers": blockers,
            "account": account,
            "rules": rules,
            "network_error": network_error,
            "observation_release_gate": status["testnet_release_gate"],
            "side_effects": False,
            "secrets_exposed": False,
        }

    def arm(self, confirmation: str) -> dict[str, Any]:
        status = self.status()
        expected = "ARM LIVE 50 USDT" if self.settings.mode == ExecutionMode.LIVE else "ARM TESTNET AUTO"
        if confirmation.strip() != expected:
            raise ValueError("confirmation_phrase_mismatch")
        if status["blockers"]:
            raise ValueError("execution_gate_blocked:" + ",".join(status["blockers"]))
        self._killed = False
        self._armed = True
        record_kill_switch(self.db_path, action="armed", reason="operator_confirmation", source="api", details={"mode": self.settings.mode.value})
        return self.status()

    def disarm(self, reason: str = "operator_request") -> dict[str, Any]:
        self._armed = False
        record_kill_switch(self.db_path, action="disarmed", reason=reason, source="api", details={"mode": self.settings.mode.value})
        return self.status()

    def kill(self, reason: str) -> dict[str, Any]:
        self._armed = False
        self._killed = True
        record_kill_switch(self.db_path, action="activated", reason=reason or "operator_request", source="api", details={"mode": self.settings.mode.value})
        return self.status()

    def account_summary(self) -> dict[str, Any]:
        if not self.settings.credentials_configured or self.settings.mode == ExecutionMode.DISABLED:
            return {"status": "unavailable", "reason": "execution_credentials_not_configured", "secrets_exposed": False}
        client = self._client_factory()
        try:
            client.sync_clock("spot")
            spot = client.account("spot")
            futures = client.account("perpetual")
            spot_usdt = next((item for item in spot.get("balances", ()) if item.get("asset") == "USDT"), {})
            return {
                "status": "available",
                "mode": self.settings.mode.value,
                "spot": {
                    "usdt_free": float(spot_usdt.get("free") or 0.0),
                    "usdt_locked": float(spot_usdt.get("locked") or 0.0),
                    "can_trade": bool(spot.get("canTrade", False)),
                },
                "futures": {
                    "wallet_balance_usdt": float(futures.get("totalWalletBalance") or 0.0),
                    "available_balance_usdt": float(futures.get("availableBalance") or 0.0),
                    "unrealized_pnl_usdt": float(futures.get("totalUnrealizedProfit") or 0.0),
                },
                "secrets_exposed": False,
            }
        finally:
            client.close()

    def exchange_rules(self) -> list[dict[str, Any]]:
        if not self.settings.credentials_configured or self.settings.mode == ExecutionMode.DISABLED:
            return []
        client = self._client_factory()
        try:
            result: list[dict[str, Any]] = []
            for market_type in ("spot", "perpetual"):
                payload = client.exchange_info(market_type)
                for symbol in self.settings.symbols:
                    try:
                        result.append(parse_symbol_rules(payload, symbol, market_type))
                    except ValueError:
                        result.append({"symbol": symbol, "market_type": market_type, "tradable": False, "status": "MISSING"})
            return result
        finally:
            client.close()

    def execute_intent(self, intent: ExecutionIntent, *, evaluation_decision: str) -> dict[str, Any]:
        """Run account-aware admission and submit through the sole order manager path."""

        client = self._client_factory()
        try:
            client.sync_clock(intent.market_type)
            account_payload = client.account(intent.market_type)
            if intent.market_type == "spot":
                usdt = next((item for item in account_payload.get("balances", ()) if item.get("asset") == "USDT"), {})
                available = float(usdt.get("free") or 0.0)
                equity = available + float(usdt.get("locked") or 0.0)
            else:
                available = float(account_payload.get("availableBalance") or 0.0)
                equity = float(account_payload.get("totalWalletBalance") or 0.0)
            positions = tuple(
                ExchangePosition(
                    symbol=str(item["symbol"]), market_type=str(item["market_type"]),
                    direction=str(item.get("direction") or "long"), quantity=abs(float(item["quantity"])),
                    entry_price=float(item.get("entry_price") or 0.0), mark_price=float(item.get("mark_price") or 0.0),
                    stop_price=float(item["stop_price"]) if item.get("stop_price") is not None else None,
                )
                for item in list_execution_positions(self.db_path)
            )
            from uuid import uuid4
            account = AccountRiskSnapshot(
                snapshot_id=f"account_{uuid4().hex}", mode=self.settings.mode.value,
                equity_usdt=equity, available_usdt=available,
                daily_realized_pnl_usdt=local_daily_realized_pnl(self.db_path, datetime.now(UTC).date().isoformat()),
                positions=positions,
                open_order_count=len(client.open_orders(intent.market_type)),
            )
            rules_payload = parse_symbol_rules(client.exchange_info(intent.market_type), intent.symbol, intent.market_type)
            rules = SymbolTradingRules(
                symbol=rules_payload["symbol"], market_type=rules_payload["market_type"],
                min_qty=rules_payload["min_qty"], step_size=rules_payload["step_size"],
                min_notional=rules_payload["min_notional"], tick_size=rules_payload["tick_size"],
                tradable=rules_payload["tradable"],
            )
            risk = evaluate_execution_risk(
                intent, account, rules, self.settings,
                armed=self.armed, evaluation_decision=evaluation_decision,
            )
            save_risk_decision(self.db_path, account, risk)
            if not risk.allowed:
                return {"status": "risk_blocked", "risk": risk.as_dict()}
            manager = BinanceOrderManager(
                self.db_path, client, execution_mode=self.settings.mode.value,
                max_leverage=self.settings.max_leverage,
                on_critical_failure=self.kill,
            )
            return {"status": "submitted", "risk": risk.as_dict(), "order": manager.submit(intent, risk, rules)}
        finally:
            client.close()

    def cancel_sibling_protection(self, filled_order: dict[str, Any]) -> list[str]:
        if str(filled_order.get("market_type")) != "perpetual" or str(filled_order.get("order_role")) not in {"stop", "target"}:
            return []
        siblings = [
            item for item in list_orders_for_intent(self.db_path, str(filled_order["intent_id"]))
            if item["client_order_id"] != filled_order["client_order_id"]
            and item["order_role"] in {"stop", "target"}
            and item["status"] in {"sending", "unknown", "NEW", "PARTIALLY_FILLED"}
        ]
        canceled: list[str] = []
        client = self._client_factory()
        try:
            for sibling in siblings:
                try:
                    client.cancel_order("perpetual", str(sibling["symbol"]), str(sibling["client_order_id"]))
                    canceled.append(str(sibling["client_order_id"]))
                except BinanceExecutionError:
                    self.kill("protection_sibling_cancel_failed")
                    raise
        finally:
            client.close()
        return canceled

    def reconcile(self) -> dict[str, Any]:
        started_at = datetime.now(UTC).isoformat()
        if not self.settings.credentials_configured or self.settings.mode == ExecutionMode.DISABLED:
            return save_reconciliation(
                self.db_path,
                mode=self.settings.mode.value,
                status="blocked",
                discrepancies=[{"code": "credentials_missing"}],
                started_at=started_at,
            )
        client = self._client_factory()
        try:
            remote = []
            for market_type in ("spot", "perpetual"):
                remote.extend({**item, "market_type": market_type} for item in client.open_orders(market_type))
            remote_ids = {str(item.get("clientOrderId")) for item in remote if item.get("clientOrderId")}
            local = list_execution_orders(self.db_path, limit=500)
            local_ids = {
                str(item["client_order_id"])
                for item in local
                if item["status"] in {"sending", "unknown", "NEW", "PARTIALLY_FILLED"}
            }
            discrepancies = [
                *({"code": "remote_order_missing_locally", "client_order_id": value} for value in sorted(remote_ids - local_ids)),
                *({"code": "local_order_missing_remotely", "client_order_id": value} for value in sorted(local_ids - remote_ids)),
            ]
            status = "matched" if not discrepancies else "mismatch"
            if discrepancies:
                self.kill("reconciliation_mismatch")
            return save_reconciliation(self.db_path, mode=self.settings.mode.value, status=status, discrepancies=discrepancies, started_at=started_at)
        except BinanceExecutionError as exc:
            self.kill("reconciliation_failed")
            return save_reconciliation(
                self.db_path,
                mode=self.settings.mode.value,
                status="error",
                discrepancies=[{"code": str(exc)}],
                started_at=started_at,
            )
        finally:
            client.close()
