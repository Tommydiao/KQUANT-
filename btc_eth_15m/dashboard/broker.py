from __future__ import annotations

import json
from abc import ABC, abstractmethod
from decimal import Decimal
from uuid import uuid4

import requests

from btc_eth_15m.config import AppConfig
from btc_eth_15m.data import market_freshness
from btc_eth_15m.dashboard.binance import (
    LIVE_BASE_URL,
    TESTNET_BASE_URL,
    BinanceCredentials,
    BinanceFuturesClient,
    SymbolRules,
)
from btc_eth_15m.dashboard.models import OrderDraft
from btc_eth_15m.dashboard.risk import daily_loss_within_cap
from btc_eth_15m.dashboard.redaction import safe_error_detail
from btc_eth_15m.dashboard.state import (
    dashboard_connection,
    daily_loss_used,
    daily_margin_used,
    latest_exchange_sync,
    latest_exchange_self_check_summary,
    latest_exchange_sync_summary,
    latest_events,
    latest_orders,
    kill_switch_enabled,
    now_iso,
    open_margin,
    open_position_count,
    open_positions,
)


class BrokerError(RuntimeError):
    pass


class Broker(ABC):
    mode: str

    @abstractmethod
    def status(self) -> dict:
        raise NotImplementedError

    @abstractmethod
    def positions(self) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def orders(self) -> list[dict]:
        raise NotImplementedError

    @abstractmethod
    def submit_order_draft(self, draft: OrderDraft, *, leverage: int | None = None) -> dict:
        raise NotImplementedError

    @abstractmethod
    def close_position(self, position_id: str, *, reason: str = "manual") -> dict:
        raise NotImplementedError

    @abstractmethod
    def self_check(self, *, include_user_stream: bool = True) -> dict:
        raise NotImplementedError

    @abstractmethod
    def sync_snapshot(self) -> dict:
        raise NotImplementedError


class PaperBroker(Broker):
    mode = "paper"

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "connected": True,
            "order_sync_ok": True,
            "position_sync_ok": True,
            "exchange_rules_ok": True,
            "order_submission_enabled": True,
            "message": "Paper broker is local and ready.",
        }

    def positions(self) -> list[dict]:
        return [row for row in open_positions(self.config.db_path) if row["mode"] == self.mode]

    def orders(self) -> list[dict]:
        return [row for row in latest_orders(self.config.db_path) if row["mode"] == self.mode]

    def submit_order_draft(self, draft: OrderDraft, *, leverage: int | None = None) -> dict:
        requested_leverage = leverage or draft.leverage
        _require_kill_switch_off(self.config)
        _validate_order_draft(
            self.config,
            self.mode,
            draft,
            requested_leverage,
            current_symbol_positions=open_position_count(self.config.db_path, self.mode, draft.symbol),
            current_open_margin_usdt=open_margin(self.config.db_path, self.mode),
            current_daily_margin_used_usdt=daily_margin_used(self.config.db_path, self.mode),
            current_daily_loss_usdt=daily_loss_used(self.config.db_path, self.mode),
        )

        notional = draft.margin_usdt * requested_leverage
        quantity = notional / draft.entry_price if draft.entry_price > 0 else 0.0
        order_id = "paper-" + uuid4().hex[:12]
        position_id = "pos-" + uuid4().hex[:12]
        created_at = now_iso()
        explanation_json = json.dumps(draft.explanation, ensure_ascii=False, sort_keys=True)
        with dashboard_connection(self.config.db_path) as connection:
            connection.execute(
                """
                INSERT INTO dashboard_orders (
                    id, mode, symbol, side, leverage, margin_usdt, notional_usdt,
                    quantity, entry_price, stop_price, target_price, status,
                    source_draft_id, explanation_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    self.mode,
                    draft.symbol,
                    draft.side,
                    requested_leverage,
                    draft.margin_usdt,
                    notional,
                    quantity,
                    draft.entry_price,
                    draft.stop_price,
                    draft.target_price,
                    "FILLED",
                    draft.id,
                    explanation_json,
                    created_at,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO dashboard_positions (
                    id, order_id, mode, symbol, side, leverage, margin_usdt,
                    notional_usdt, quantity, entry_price, mark_price,
                    unrealized_pnl, status, opened_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    position_id,
                    order_id,
                    self.mode,
                    draft.symbol,
                    draft.side,
                    requested_leverage,
                    draft.margin_usdt,
                    notional,
                    quantity,
                    draft.entry_price,
                    draft.entry_price,
                    0.0,
                    "OPEN",
                    created_at,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO dashboard_events (level, message, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "info",
                    f"Paper order filled: {draft.symbol} {draft.side} {requested_leverage}x",
                    json.dumps({"order_id": order_id, "draft_id": draft.id}, ensure_ascii=False),
                    created_at,
                ),
            )
            connection.commit()
        return {"order_id": order_id, "position_id": position_id, "status": "FILLED"}

    def events(self) -> list[dict]:
        return latest_events(self.config.db_path)

    def close_position(self, position_id: str, *, reason: str = "manual") -> dict:
        closed_at = now_iso()
        with dashboard_connection(self.config.db_path) as connection:
            row = connection.execute(
                """
                SELECT id, order_id, mode, symbol, side, leverage, margin_usdt,
                       notional_usdt, quantity, entry_price, mark_price, status
                FROM dashboard_positions
                WHERE id = ? AND mode = ? AND status = 'OPEN'
                """,
                (position_id, self.mode),
            ).fetchone()
            if row is None:
                raise BrokerError("Open paper position was not found.")

            columns = [
                "id",
                "order_id",
                "mode",
                "symbol",
                "side",
                "leverage",
                "margin_usdt",
                "notional_usdt",
                "quantity",
                "entry_price",
                "mark_price",
                "status",
            ]
            position = dict(zip(columns, row, strict=True))
            side_multiplier = 1 if position["side"] == "long" else -1
            exit_price = float(position["mark_price"])
            entry_price = float(position["entry_price"])
            quantity = float(position["quantity"])
            pnl = (exit_price - entry_price) * quantity * side_multiplier
            close_order_id = "paper-close-" + uuid4().hex[:12]
            connection.execute(
                """
                UPDATE dashboard_positions
                SET status = 'CLOSED', unrealized_pnl = ?, updated_at = ?
                WHERE id = ?
                """,
                (pnl, closed_at, position_id),
            )
            connection.execute(
                """
                INSERT INTO dashboard_orders (
                    id, mode, symbol, side, leverage, margin_usdt, notional_usdt,
                    quantity, entry_price, stop_price, target_price, status,
                    source_draft_id, explanation_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    close_order_id,
                    self.mode,
                    position["symbol"],
                    "short" if position["side"] == "long" else "long",
                    int(position["leverage"]),
                    0.0,
                    float(position["notional_usdt"]),
                    quantity,
                    exit_price,
                    0.0,
                    0.0,
                    "FILLED",
                    position_id,
                    json.dumps({"reason": reason, "pnl": pnl}, ensure_ascii=False),
                    closed_at,
                    closed_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO dashboard_events (level, message, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    "info",
                    f"Paper position closed: {position['symbol']} {position['side']}",
                    json.dumps(
                        {"position_id": position_id, "close_order_id": close_order_id, "reason": reason, "pnl": pnl},
                        ensure_ascii=False,
                    ),
                    closed_at,
                ),
            )
            connection.commit()
        return {"position_id": position_id, "close_order_id": close_order_id, "status": "CLOSED", "pnl": pnl}

    def self_check(self, *, include_user_stream: bool = True) -> dict:
        return {
            "mode": self.mode,
            "passed": True,
            "checks": [
                {"name": "paper_state", "passed": True, "message": "Local paper state is available."},
                {"name": "manual_confirmation", "passed": True, "message": "Paper orders still require UI confirmation."},
            ],
            "symbol_rules": [],
        }

    def sync_snapshot(self) -> dict:
        return {
            "mode": self.mode,
            "passed": True,
            "synced_at": now_iso(),
            "checks": self.self_check()["checks"],
            "account_summary": {"type": "paper", "message": "Paper mode uses local simulated state."},
            "positions": self.positions(),
            "orders": self.orders(),
            "symbol_rules": [],
        }


class BinanceFuturesBroker(Broker):
    def __init__(self, config: AppConfig, *, mode: str, base_url: str, env_prefix: str, live_enabled: bool = False) -> None:
        self.config = config
        self.mode = mode
        self.base_url = base_url
        self.env_prefix = env_prefix
        self.credentials = BinanceCredentials.from_env(env_prefix)
        self.client = BinanceFuturesClient(base_url, self.credentials)
        self.live_enabled = live_enabled

    def status(self) -> dict:
        if self.mode == "live" and not self.live_enabled:
            return {
                "mode": self.mode,
                "connected": False,
                "order_sync_ok": False,
                "position_sync_ok": False,
                "exchange_rules_ok": False,
                "order_submission_enabled": False,
                "credentials_configured": bool(self.credentials),
                "base_url": self.base_url,
                "message": "Live broker is locked by configuration.",
            }
        if not self.credentials:
            return {
                "mode": self.mode,
                "connected": False,
                "order_sync_ok": False,
                "position_sync_ok": False,
                "exchange_rules_ok": False,
                "order_submission_enabled": False,
                "credentials_configured": False,
                "base_url": self.base_url,
                "message": "API credentials are not configured.",
            }
        sync_summary = latest_exchange_sync_summary(
            self.config.db_path,
            self.mode,
            max_age_seconds=self.config.exchange_sync_max_age_seconds,
        )
        self_check_summary = latest_exchange_self_check_summary(
            self.config.db_path,
            self.mode,
            max_age_seconds=self.config.exchange_self_check_max_age_seconds,
        )
        sync_ok = bool(sync_summary and sync_summary.get("passed") and sync_summary.get("is_fresh"))
        self_check_ok = bool(
            self_check_summary and self_check_summary.get("passed") and self_check_summary.get("is_fresh")
        )
        exchange_ok = bool(sync_ok and self_check_ok)
        return {
            "mode": self.mode,
            "connected": exchange_ok,
            "order_sync_ok": exchange_ok,
            "position_sync_ok": exchange_ok,
            "exchange_rules_ok": exchange_ok,
            "order_submission_enabled": self.mode == "testnet" and exchange_ok,
            "credentials_configured": True,
            "base_url": self.base_url,
            "message": _exchange_status_message(self.mode, self_check_summary, sync_summary),
        }

    def positions(self) -> list[dict]:
        payload = latest_exchange_sync(self.config.db_path, self.mode)
        return payload.get("positions", []) if payload else []

    def orders(self) -> list[dict]:
        payload = latest_exchange_sync(self.config.db_path, self.mode)
        return payload.get("orders", []) if payload else []

    def submit_order_draft(self, draft: OrderDraft, *, leverage: int | None = None) -> dict:
        if self.mode == "live" and not self.live_enabled:
            raise BrokerError("Live broker is locked by configuration.")
        if not self.credentials:
            raise BrokerError("Binance API credentials are not configured.")
        requested_leverage = leverage or draft.leverage
        _require_kill_switch_off(self.config)
        if self.mode == "testnet":
            _require_fresh_exchange_sync(self.config, self.mode)
            _require_fresh_exchange_self_check(self.config, self.mode)
        _validate_order_draft(
            self.config,
            self.mode,
            draft,
            requested_leverage,
            current_symbol_positions=None,
            current_open_margin_usdt=open_margin(self.config.db_path, self.mode),
            current_daily_margin_used_usdt=daily_margin_used(self.config.db_path, self.mode),
            current_daily_loss_usdt=daily_loss_used(self.config.db_path, self.mode),
        )
        if self.mode == "testnet":
            _require_fresh_market_data(self.config, draft.symbol)
            _validate_symbol_position_cap(self.config, draft.symbol, self._current_symbol_position_count(draft.symbol))
            payload, plan = self._test_order_payload(draft, requested_leverage)
            self.client.post("/fapi/v1/leverage", {"symbol": draft.symbol, "leverage": requested_leverage})
            # Test order validates signing and exchange-side order shape without creating a fill.
            result = self.client.post("/fapi/v1/order/test", payload)
            return {"status": "TEST_ORDER_ACCEPTED", "exchange_response": result, "order_plan": plan}
        raise BrokerError("Live order submission is intentionally not wired until readiness gates pass.")

    def _test_order_payload(self, draft: OrderDraft, requested_leverage: int) -> tuple[dict, dict]:
        rules = self.symbol_rules(draft.symbol)
        quantity = Decimal(str(draft.margin_usdt)) * Decimal(str(requested_leverage)) / Decimal(str(draft.entry_price))
        rounded_quantity = rules.round_quantity(quantity)
        price = Decimal(str(draft.entry_price))
        validation_errors = rules.validate_market_order(rounded_quantity, price)
        if validation_errors:
            raise BrokerError("Exchange rule validation failed: " + "; ".join(validation_errors))
        payload = {
            "symbol": draft.symbol,
            "side": "BUY" if draft.side == "long" else "SELL",
            "type": "MARKET",
            "quantity": _decimal_to_plain(rounded_quantity),
        }
        plan = {
            "symbol": draft.symbol,
            "requested_leverage": requested_leverage,
            "raw_quantity": _decimal_to_plain(quantity),
            "rounded_quantity": _decimal_to_plain(rounded_quantity),
            "notional_usdt": _decimal_to_plain(rounded_quantity * price),
            "rules": rules.to_dict(),
        }
        return payload, plan

    def close_position(self, position_id: str, *, reason: str = "manual") -> dict:
        raise BrokerError(f"{self.mode} close-position is not enabled from the local console yet.")

    def _current_symbol_position_count(self, symbol: str) -> int:
        try:
            payload = self.client.get("/fapi/v3/positionRisk")
        except (requests.RequestException, ValueError) as exc:
            reason = safe_error_detail(str(exc))
            raise BrokerError(f"Position sync failed before order confirmation: {reason}") from exc
        count = 0
        for row in payload if isinstance(payload, list) else []:
            if row.get("symbol") != symbol:
                continue
            amount = float(row.get("positionAmt", 0) or 0)
            if amount != 0:
                count += 1
        return count

    def symbol_rules(self, symbol: str) -> SymbolRules:
        payload = self.client.public_get("/fapi/v1/exchangeInfo", {"symbol": symbol})
        symbols = payload.get("symbols", []) if isinstance(payload, dict) else []
        if not symbols:
            raise BrokerError(f"Exchange rules were not returned for {symbol}.")
        return SymbolRules.from_exchange_info(symbols[0])

    def self_check(self, *, include_user_stream: bool = True) -> dict:
        checks = []
        symbol_rules = []
        try:
            delta_ms = self.client.server_time_delta_ms()
            checks.append(
                {
                    "name": "server_time",
                    "passed": abs(delta_ms) <= 10_000,
                    "message": f"Server time delta is {delta_ms} ms.",
                }
            )
        except (requests.RequestException, ValueError) as exc:
            reason = safe_error_detail(str(exc))
            checks.append({"name": "server_time", "passed": False, "message": f"Server time endpoint failed: {reason}"})
        credentials_ok = bool(self.credentials)
        checks.append(
            {
                "name": "credentials",
                "passed": credentials_ok,
                "message": "API credentials are configured." if credentials_ok else "API credentials are not configured.",
            }
        )
        if self.mode == "live" and not self.live_enabled:
            checks.append({"name": "live_enabled", "passed": False, "message": "Live broker is locked by configuration."})
        if credentials_ok and (self.mode != "live" or self.live_enabled):
            for name, call in [
                ("account", lambda: self.client.get("/fapi/v3/account")),
                ("positions", lambda: self.client.get("/fapi/v3/positionRisk")),
            ]:
                try:
                    payload = call()
                    summary = _sync_summary(name, payload)
                    checks.append({"name": name, "passed": True, "message": f"{name} endpoint is reachable. {summary}"})
                except (requests.RequestException, ValueError) as exc:
                    reason = safe_error_detail(str(exc))
                    checks.append({"name": name, "passed": False, "message": f"{name} endpoint failed: {reason}"})
            open_orders_ok = True
            open_order_messages = []
            for symbol in self.config.symbols:
                try:
                    self.client.get("/fapi/v1/openOrders", {"symbol": symbol})
                    open_order_messages.append(f"{symbol} openOrders ok")
                except (requests.RequestException, ValueError) as exc:
                    reason = safe_error_detail(str(exc))
                    open_orders_ok = False
                    open_order_messages.append(f"{symbol} openOrders failed: {reason}")
            checks.append({"name": "open_orders", "passed": open_orders_ok, "message": "; ".join(open_order_messages)})
            for symbol in self.config.symbols:
                try:
                    rules = self.symbol_rules(symbol)
                    symbol_rules.append(rules.to_dict())
                    checks.append({"name": f"{symbol}_exchange_rules", "passed": True, "message": "Exchange filters loaded."})
                except (requests.RequestException, ValueError, BrokerError) as exc:
                    reason = safe_error_detail(str(exc))
                    checks.append({"name": f"{symbol}_exchange_rules", "passed": False, "message": f"Exchange filters failed: {reason}"})
            if include_user_stream:
                try:
                    listen_key_payload = self.client.start_user_data_stream()
                    listen_key_ok = isinstance(listen_key_payload, dict) and bool(listen_key_payload.get("listenKey"))
                    checks.append(
                        {
                            "name": "user_data_stream",
                            "passed": listen_key_ok,
                            "message": "listenKey acquired; value hidden." if listen_key_ok else "listenKey was not returned.",
                        }
                    )
                except (requests.RequestException, ValueError) as exc:
                    reason = safe_error_detail(str(exc))
                    checks.append({"name": "user_data_stream", "passed": False, "message": f"listenKey failed: {reason}"})
        return {
            "mode": self.mode,
            "passed": all(check["passed"] for check in checks),
            "base_url": self.base_url,
            "credentials_configured": credentials_ok,
            "checks": checks,
            "symbol_rules": symbol_rules,
        }

    def sync_snapshot(self) -> dict:
        if self.mode == "live" and not self.live_enabled:
            return {
                "mode": self.mode,
                "passed": False,
                "synced_at": now_iso(),
                "checks": [{"name": "live_enabled", "passed": False, "message": "Live broker is locked by configuration."}],
                "account_summary": None,
                "positions": [],
                "orders": [],
                "symbol_rules": [],
            }
        check = self.self_check(include_user_stream=False)
        if not check.get("passed"):
            return {
                "mode": self.mode,
                "passed": False,
                "synced_at": now_iso(),
                "checks": check.get("checks", []),
                "account_summary": None,
                "positions": [],
                "orders": [],
                "symbol_rules": check.get("symbol_rules", []),
            }
        try:
            account = self.client.get("/fapi/v3/account")
            position_payload = self.client.get("/fapi/v3/positionRisk")
            position_rows = _position_rows_from_payload(self.mode, position_payload)
            order_rows = []
            for symbol in self.config.symbols:
                order_rows.extend(
                    _order_rows_from_payload(
                        self.mode,
                        self.client.get("/fapi/v1/openOrders", {"symbol": symbol}),
                    )
                )
        except (requests.RequestException, TypeError, ValueError) as exc:
            return _failed_sync_snapshot(
                self.mode,
                check.get("checks", []),
                check.get("symbol_rules", []),
                "snapshot_fetch",
                f"Sync snapshot fetch failed: {safe_error_detail(str(exc))}",
            )
        return {
            "mode": self.mode,
            "passed": True,
            "synced_at": now_iso(),
            "checks": check.get("checks", []),
            "account_summary": _account_summary(account),
            "positions": position_rows,
            "orders": order_rows,
            "symbol_rules": check.get("symbol_rules", []),
        }


def broker_for_mode(config: AppConfig, mode: str) -> Broker:
    if mode == "paper":
        return PaperBroker(config)
    if mode == "testnet":
        return BinanceFuturesBroker(
            config,
            mode="testnet",
            base_url=TESTNET_BASE_URL,
            env_prefix="BINANCE_FUTURES_TESTNET",
        )
    if mode == "live":
        return BinanceFuturesBroker(
            config,
            mode="live",
            base_url=LIVE_BASE_URL,
            env_prefix="BINANCE_FUTURES_LIVE",
            live_enabled=config.live_enabled,
        )
    raise BrokerError(f"Unsupported broker mode: {mode}")


def _decimal_to_plain(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized, "f")
    return format(normalized, "f").rstrip("0").rstrip(".")


def _failed_sync_snapshot(mode: str, checks: list[dict], symbol_rules: list[dict], name: str, message: str) -> dict:
    return {
        "mode": mode,
        "passed": False,
        "synced_at": now_iso(),
        "checks": [*checks, {"name": name, "passed": False, "message": message}],
        "account_summary": None,
        "positions": [],
        "orders": [],
        "symbol_rules": symbol_rules,
    }


def _position_rows_from_payload(mode: str, payload: dict | list) -> list[dict]:
    positions = []
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, dict):
            continue
        amount = float(row.get("positionAmt", 0) or 0)
        if amount == 0:
            continue
        positions.append(
            {
                "id": f"{mode}-{row.get('symbol')}",
                "order_id": "",
                "mode": mode,
                "symbol": row.get("symbol"),
                "side": "long" if amount > 0 else "short",
                "leverage": int(float(row.get("leverage", 0) or 0)),
                "margin_usdt": float(row.get("isolatedMargin", 0) or 0),
                "notional_usdt": abs(float(row.get("notional", 0) or 0)),
                "quantity": abs(amount),
                "entry_price": float(row.get("entryPrice", 0) or 0),
                "mark_price": float(row.get("markPrice", 0) or 0),
                "unrealized_pnl": float(row.get("unRealizedProfit", 0) or 0),
                "status": "OPEN",
                "opened_at": "",
                "updated_at": now_iso(),
            }
        )
    return positions


def _order_rows_from_payload(mode: str, payload: dict | list) -> list[dict]:
    orders = []
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, dict):
            continue
        orders.append(
            {
                "id": str(row.get("orderId")),
                "mode": mode,
                "symbol": row.get("symbol"),
                "side": str(row.get("side", "")).lower(),
                "leverage": 0,
                "margin_usdt": 0.0,
                "notional_usdt": float(row.get("origQty", 0) or 0) * float(row.get("price", 0) or 0),
                "quantity": float(row.get("origQty", 0) or 0),
                "entry_price": float(row.get("price", 0) or 0),
                "stop_price": 0.0,
                "target_price": 0.0,
                "status": row.get("status", "UNKNOWN"),
                "source_draft_id": "",
                "created_at": "",
                "updated_at": now_iso(),
            }
        )
    return orders


def _validate_order_draft(
    config: AppConfig,
    broker_mode: str,
    draft: OrderDraft,
    requested_leverage: int,
    *,
    current_symbol_positions: int | None,
    current_open_margin_usdt: float,
    current_daily_margin_used_usdt: float,
    current_daily_loss_usdt: float,
) -> None:
    if draft.mode != broker_mode:
        raise BrokerError(f"Order draft mode {draft.mode} does not match broker mode {broker_mode}.")
    if draft.status != "ready":
        reasons = "; ".join(draft.blocked_reasons) or "no blocker details provided"
        raise BrokerError("Order draft is blocked: " + reasons)
    if requested_leverage < config.min_execution_leverage:
        raise BrokerError("Requested leverage is below the configured minimum leverage.")
    if requested_leverage > draft.max_allowed_leverage:
        raise BrokerError("Requested leverage exceeds the strategy-approved leverage.")
    if requested_leverage > config.max_execution_leverage:
        raise BrokerError("Requested leverage exceeds the configured maximum leverage.")
    if draft.margin_usdt <= 0:
        raise BrokerError("Order draft has no executable margin budget.")
    if draft.margin_usdt > config.live_single_order_margin_cap_usdt:
        raise BrokerError(
            f"Single-order margin cap would be exceeded: "
            f"{draft.margin_usdt:.2f} / {config.live_single_order_margin_cap_usdt:.2f} USDT."
        )
    projected_open_margin = current_open_margin_usdt + draft.margin_usdt
    if projected_open_margin > config.live_margin_cap_usdt:
        raise BrokerError(
            f"Open margin cap would be exceeded: "
            f"{projected_open_margin:.2f} / {config.live_margin_cap_usdt:.2f} USDT."
        )
    projected_daily_margin = current_daily_margin_used_usdt + draft.margin_usdt
    if projected_daily_margin > config.live_daily_margin_cap_usdt:
        raise BrokerError(
            f"Daily margin cap would be exceeded: "
            f"{projected_daily_margin:.2f} / {config.live_daily_margin_cap_usdt:.2f} USDT."
        )
    if current_symbol_positions is not None:
        _validate_symbol_position_cap(config, draft.symbol, current_symbol_positions)
    max_daily_loss_usdt = config.initial_equity * config.max_daily_loss
    if not daily_loss_within_cap(current_daily_loss_usdt, max_daily_loss_usdt):
        raise BrokerError(
            f"Daily loss cap reached: {current_daily_loss_usdt:.2f} / {max_daily_loss_usdt:.2f} USDT."
        )


def _validate_symbol_position_cap(config: AppConfig, symbol: str, current_symbol_positions: int) -> None:
    if current_symbol_positions >= config.max_positions_per_symbol:
        raise BrokerError(
            f"Open position cap reached for {symbol}: "
            f"{current_symbol_positions} / {config.max_positions_per_symbol}."
        )


def _require_fresh_exchange_sync(config: AppConfig, mode: str) -> None:
    summary = latest_exchange_sync_summary(
        config.db_path,
        mode,
        max_age_seconds=config.exchange_sync_max_age_seconds,
    )
    if not summary or not summary.get("passed"):
        raise BrokerError(f"{mode.capitalize()} sync snapshot has not passed.")
    if not summary.get("is_fresh"):
        raise BrokerError(f"{mode.capitalize()} sync snapshot is stale.")


def _require_fresh_exchange_self_check(config: AppConfig, mode: str) -> None:
    summary = latest_exchange_self_check_summary(
        config.db_path,
        mode,
        max_age_seconds=config.exchange_self_check_max_age_seconds,
    )
    if not summary or not summary.get("passed"):
        raise BrokerError(f"{mode.capitalize()} self-check has not passed.")
    if not summary.get("is_fresh"):
        raise BrokerError(f"{mode.capitalize()} self-check is stale.")


def _require_fresh_market_data(config: AppConfig, symbol: str) -> None:
    current = {item["symbol"]: item for item in market_freshness(config)}
    if not current.get(symbol, {}).get("is_fresh"):
        raise BrokerError(f"Market data is stale or missing for {symbol}.")


def _require_kill_switch_off(config: AppConfig) -> None:
    if kill_switch_enabled(config.db_path):
        raise BrokerError("Kill switch is active.")


def _sync_summary(name: str, payload: dict | list) -> str:
    if name == "positions" and isinstance(payload, list):
        open_count = sum(1 for row in payload if float(row.get("positionAmt", 0) or 0) != 0)
        return f"{open_count} open positions returned."
    if name == "account" and isinstance(payload, dict):
        assets = payload.get("assets", [])
        positions = payload.get("positions", [])
        return f"{len(assets)} assets and {len(positions)} position rows returned."
    return ""


def _exchange_status_message(mode: str, self_check_summary: dict | None, sync_summary: dict | None) -> str:
    if self_check_summary is None:
        return "No exchange self-check has been recorded."
    if not self_check_summary.get("passed"):
        failed = ", ".join(self_check_summary.get("failed_checks") or ["unknown"])
        return f"Exchange self-check has not passed: {failed}."
    if not self_check_summary.get("is_fresh"):
        return "Exchange self-check is stale."
    if sync_summary is None:
        return "No exchange sync snapshot has been recorded."
    if not sync_summary.get("passed"):
        failed = ", ".join(sync_summary.get("failed_checks") or ["unknown"])
        return f"Exchange sync snapshot has not passed: {failed}."
    if not sync_summary.get("is_fresh"):
        return "Exchange sync snapshot is stale."
    if mode == "testnet":
        return "Binance USD-M Futures sync is fresh; test-order rehearsal is available."
    return "Binance USD-M Futures account sync is fresh; live order submission is not wired."


def _account_summary(payload: dict | list) -> dict:
    if not isinstance(payload, dict):
        return {"type": "unknown"}
    keys = [
        "availableBalance",
        "totalWalletBalance",
        "totalUnrealizedProfit",
        "totalMaintMargin",
        "totalInitialMargin",
    ]
    summary = {key: payload.get(key) for key in keys if key in payload}
    summary["asset_count"] = len(payload.get("assets", []))
    summary["position_row_count"] = len(payload.get("positions", []))
    return summary
