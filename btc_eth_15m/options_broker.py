from __future__ import annotations

import json
import os
import re
import sqlite3
import urllib.parse
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from btc_eth_15m.dashboard.state import record_event
from btc_eth_15m.options_lab import options_contract
from btc_eth_15m.options_pilot_journal import journal_entry_complete_for_option


OPTIONS_ORDER_INTENTS_TABLE = "options_order_intents"
OPTIONS_PAPER_ORDERS_TABLE = "options_paper_orders"
ALLOWED_ACTIONS = {"buy_to_open", "sell_to_close"}
MAX_CONTRACTS_PER_ORDER = 1
MAX_DAILY_PREMIUM_USD = 500.0
MAX_OPEN_PREMIUM_USD = 1000.0
DEFAULT_ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"


@dataclass
class OptionOrderIntent:
    id: str
    created_at: str
    updated_at: str
    symbol: str
    option_symbol: str
    action: str
    side: str
    order_type: str
    quantity: int
    limit_price: float
    estimated_premium_usd: float
    status: str
    blockers: list[str]
    source_type: str
    journal_entry_id: str | None
    contract: dict[str, Any]
    risk: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OptionOrderTicket:
    intent_id: str
    symbol: str
    option_symbol: str
    action: str
    side: str
    order_type: str
    quantity: int
    limit_price: float
    time_in_force: str = "day"

    def to_alpaca_payload(self) -> dict[str, Any]:
        return {
            "symbol": self.option_symbol,
            "qty": str(self.quantity),
            "side": "buy" if self.action == "buy_to_open" else "sell",
            "type": self.order_type,
            "time_in_force": self.time_in_force,
            "limit_price": str(round(self.limit_price, 2)),
            "position_intent": self.action,
        }

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OptionPaperOrder:
    id: str
    intent_id: str
    broker_order_id: str | None
    status: str
    symbol: str
    option_symbol: str
    action: str
    side: str
    quantity: int
    limit_price: float
    submitted_at: str
    updated_at: str
    broker_response: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OptionPositionSnapshot:
    broker_position_id: str | None
    symbol: str
    option_symbol: str
    quantity: float
    market_value: float | None
    average_entry_price: float | None
    unrealized_pl: float | None
    raw: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AlpacaPaperOptionsBroker:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("ALPACA_PAPER_API_KEY", "")
        self.secret_key = secret_key if secret_key is not None else os.getenv("ALPACA_PAPER_SECRET_KEY", "")
        self.base_url = (base_url or os.getenv("ALPACA_PAPER_BASE_URL") or DEFAULT_ALPACA_PAPER_BASE_URL).rstrip("/")
        self.timeout = timeout

    @property
    def credentials_configured(self) -> bool:
        return bool(self.api_key and self.secret_key)

    def status(self) -> dict[str, Any]:
        return {
            "broker": "alpaca",
            "mode": "paper",
            "asset_class": "us_options",
            "credentials_configured": self.credentials_configured,
            "base_url": self.base_url,
            "paper_order_submission_enabled": self.credentials_configured,
            "live_order_submission_enabled": False,
            "allowed_actions": sorted(ALLOWED_ACTIONS),
            "limits": {
                "max_contracts_per_order": MAX_CONTRACTS_PER_ORDER,
                "max_daily_premium_usd": MAX_DAILY_PREMIUM_USD,
                "max_open_premium_usd": MAX_OPEN_PREMIUM_USD,
                "order_type": "limit",
                "time_in_force": "day",
            },
            "message": "Alpaca Paper options is configured." if self.credentials_configured else "Alpaca Paper credentials are not configured.",
            "safety": _options_order_safety(),
        }

    def account(self) -> dict[str, Any]:
        if not self.credentials_configured:
            return {"available": False, "detail": "Alpaca Paper credentials are not configured.", "safety": _options_order_safety()}
        return {"available": True, "account": self._request_json("GET", "/v2/account"), "safety": _options_order_safety()}

    def positions(self) -> dict[str, Any]:
        if not self.credentials_configured:
            return {"available": False, "positions": [], "detail": "Alpaca Paper credentials are not configured.", "safety": _options_order_safety()}
        raw_positions = self._request_json("GET", "/v2/positions")
        if not isinstance(raw_positions, list):
            raw_positions = []
        positions = [
            _position_from_alpaca(item).to_dict()
            for item in raw_positions
            if _looks_like_option_symbol(str(item.get("symbol") or ""))
        ]
        return {"available": True, "positions": positions, "safety": _options_order_safety()}

    def submit_order(self, ticket: OptionOrderTicket) -> dict[str, Any]:
        if not self.credentials_configured:
            raise ValueError("Alpaca Paper credentials are not configured.")
        return self._request_json("POST", "/v2/orders", ticket.to_alpaca_payload())

    def cancel_order(self, broker_order_id: str) -> dict[str, Any]:
        if not self.credentials_configured:
            raise ValueError("Alpaca Paper credentials are not configured.")
        return self._request_json("DELETE", f"/v2/orders/{urllib.parse.quote(broker_order_id, safe='')}")

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = self.base_url + path
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {"status": response.status}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"Alpaca Paper API rejected request: HTTP {exc.code} {_redact(body)}") from exc
        except Exception as exc:
            raise ValueError(f"Alpaca Paper API request failed: {_redact(str(exc))}") from exc


def broker_status() -> dict[str, Any]:
    return AlpacaPaperOptionsBroker().status()


def broker_account() -> dict[str, Any]:
    return AlpacaPaperOptionsBroker().account()


def broker_positions() -> dict[str, Any]:
    return AlpacaPaperOptionsBroker().positions()


def create_option_order_intent(
    *,
    db_path: str | Path,
    outputs_dir: str | Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    now = _now()
    option_symbol = _clean_option_symbol(payload.get("option_symbol"))
    if not option_symbol:
        raise ValueError("option_symbol is required.")
    action = str(payload.get("action") or "buy_to_open").strip().lower()
    order_type = str(payload.get("order_type") or "limit").strip().lower()
    quantity = _int(payload.get("quantity"), 1)
    source_type = str(payload.get("source_type") or payload.get("source") or "fixture").strip().lower()
    requested_by = str(payload.get("requested_by") or "manual").strip().lower()
    manual_confirmed = _bool(payload.get("manual_confirmed") or payload.get("manual_confirm"))
    contract_detail = _contract_detail(option_symbol, source_type)
    contract = dict(contract_detail.get("contract") or {})
    symbol = _clean_symbol(payload.get("symbol") or contract_detail.get("underlying", {}).get("symbol") or _underlying_from_option_symbol(option_symbol))
    limit_price = _float(payload.get("limit_price"), _float(contract.get("mid"), 0.0))
    side = str(contract.get("option_type") or payload.get("side") or "").lower()
    estimated_premium = round(max(limit_price, 0.0) * max(quantity, 0) * 100.0, 2)
    complete_journal = journal_entry_complete_for_option(outputs_dir, option_symbol, db_path=db_path)
    risk = _order_risk_snapshot(db_path)
    blockers = _intent_blockers(
        action=action,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        estimated_premium=estimated_premium,
        requested_by=requested_by,
        manual_confirmed=manual_confirmed,
        contract_detail=contract_detail,
        complete_journal=complete_journal,
        risk=risk,
    )
    status = "blocked" if blockers else "ready"
    intent = OptionOrderIntent(
        id="opt-intent-" + uuid4().hex[:16],
        created_at=now,
        updated_at=now,
        symbol=symbol,
        option_symbol=option_symbol,
        action=action,
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        estimated_premium_usd=estimated_premium,
        status=status,
        blockers=blockers,
        source_type=source_type,
        journal_entry_id=(complete_journal or {}).get("entry_id"),
        contract=contract,
        risk=risk,
    )
    _write_intent(Path(db_path), intent, payload, complete_journal)
    record_event(
        Path(db_path),
        "options_order",
        f"Options order intent {intent.status}: {intent.option_symbol} {intent.action}.",
        {"intent_id": intent.id, "option_symbol": intent.option_symbol, "status": intent.status, "blockers": intent.blockers},
    )
    return {"intent": intent.to_dict(), "safety": _options_order_safety()}


def submit_option_paper_order(
    *,
    db_path: str | Path,
    intent_id: str,
    manual_confirmed: bool,
    broker: AlpacaPaperOptionsBroker | None = None,
) -> dict[str, Any]:
    intent = _get_intent(Path(db_path), intent_id)
    if intent is None:
        raise ValueError(f"Options order intent was not found: {intent_id}")
    if intent.status != "ready":
        raise ValueError("Options order intent is blocked: " + "; ".join(intent.blockers))
    if not manual_confirmed:
        raise ValueError("manual_confirmed=true is required before submitting a paper options order.")
    ticket = OptionOrderTicket(
        intent_id=intent.id,
        symbol=intent.symbol,
        option_symbol=intent.option_symbol,
        action=intent.action,
        side=intent.side,
        order_type=intent.order_type,
        quantity=intent.quantity,
        limit_price=intent.limit_price,
    )
    broker = broker or AlpacaPaperOptionsBroker()
    response = broker.submit_order(ticket)
    order = _record_paper_order(Path(db_path), intent, response)
    record_event(
        Path(db_path),
        "options_order",
        f"Alpaca Paper options order submitted: {intent.option_symbol} {intent.action}.",
        {"intent_id": intent.id, "order_id": order.id, "broker_order_id": order.broker_order_id},
    )
    return {"order": order.to_dict(), "ticket": ticket.to_dict(), "broker_response": response, "safety": _options_order_safety()}


def cancel_option_paper_order(
    *,
    db_path: str | Path,
    order_id: str,
    broker: AlpacaPaperOptionsBroker | None = None,
) -> dict[str, Any]:
    order = _get_paper_order(Path(db_path), order_id)
    if order is None:
        raise ValueError(f"Options paper order was not found: {order_id}")
    broker_response: dict[str, Any] = {"skipped": True, "reason": "No broker order id was recorded."}
    if order.broker_order_id:
        broker_response = (broker or AlpacaPaperOptionsBroker()).cancel_order(order.broker_order_id)
    updated = _update_paper_order_status(Path(db_path), order_id, "cancel_requested", broker_response)
    record_event(
        Path(db_path),
        "options_order",
        f"Alpaca Paper options order cancel requested: {order.option_symbol}.",
        {"order_id": order_id, "broker_order_id": order.broker_order_id},
    )
    return {"order": updated.to_dict(), "broker_response": broker_response, "safety": _options_order_safety()}


def _intent_blockers(
    *,
    action: str,
    order_type: str,
    quantity: int,
    limit_price: float,
    estimated_premium: float,
    requested_by: str,
    manual_confirmed: bool,
    contract_detail: dict[str, Any],
    complete_journal: dict[str, Any] | None,
    risk: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    if action not in ALLOWED_ACTIONS:
        blockers.append("Only buy_to_open and sell_to_close are allowed in Alpaca Paper options v1.")
    if action in {"sell_to_open", "buy_to_close"}:
        blockers.append("Short options, spreads, and closing shorts are not supported in v1.")
    if order_type != "limit":
        blockers.append("Only limit orders are allowed for options paper orders.")
    if quantity < 1 or quantity > MAX_CONTRACTS_PER_ORDER:
        blockers.append(f"Quantity must be between 1 and {MAX_CONTRACTS_PER_ORDER} contract.")
    if limit_price <= 0:
        blockers.append("A positive limit_price is required.")
    if requested_by in {"agent", "llm", "auto", "automation"}:
        blockers.append("LLM/Agent/automation cannot create options order intents.")
    if not manual_confirmed:
        blockers.append("Manual confirmation is required before creating an executable intent.")
    if not contract_detail.get("contract"):
        blockers.append("Contract detail is required before creating an order intent.")
    if not complete_journal:
        blockers.append("A complete pilot journal checklist is required before paper ordering.")
    if action == "buy_to_open":
        if estimated_premium + risk["daily_premium_used_usd"] > MAX_DAILY_PREMIUM_USD:
            blockers.append("Daily options premium budget would be exceeded.")
        if estimated_premium + risk["open_premium_used_usd"] > MAX_OPEN_PREMIUM_USD:
            blockers.append("Open options premium budget would be exceeded.")
    return blockers


def _order_risk_snapshot(db_path: str | Path) -> dict[str, Any]:
    daily = _premium_used(Path(db_path), since_today=True)
    open_premium = _premium_used(Path(db_path), since_today=False)
    return {
        "daily_premium_used_usd": daily,
        "daily_premium_remaining_usd": max(MAX_DAILY_PREMIUM_USD - daily, 0.0),
        "open_premium_used_usd": open_premium,
        "open_premium_remaining_usd": max(MAX_OPEN_PREMIUM_USD - open_premium, 0.0),
        "max_contracts_per_order": MAX_CONTRACTS_PER_ORDER,
        "max_daily_premium_usd": MAX_DAILY_PREMIUM_USD,
        "max_open_premium_usd": MAX_OPEN_PREMIUM_USD,
    }


def _premium_used(db_path: Path, *, since_today: bool) -> float:
    with _connect(db_path) as connection:
        _ensure_schema(connection)
        where = "WHERE action = 'buy_to_open' AND status NOT IN ('rejected', 'cancelled', 'cancel_requested')"
        params: tuple[Any, ...] = ()
        if since_today:
            where += " AND submitted_at >= ?"
            params = (datetime.now(tz=UTC).date().isoformat(),)
        row = connection.execute(
            f"""
            SELECT COALESCE(SUM(quantity * limit_price * 100.0), 0)
            FROM {OPTIONS_PAPER_ORDERS_TABLE}
            {where}
            """,
            params,
        ).fetchone()
    return round(float(row[0] or 0.0), 2)


def _write_intent(db_path: Path, intent: OptionOrderIntent, payload: dict[str, Any], journal_entry: dict[str, Any] | None) -> None:
    with _connect(db_path) as connection:
        _ensure_schema(connection)
        connection.execute(
            f"""
            INSERT INTO {OPTIONS_ORDER_INTENTS_TABLE} (
                id, created_at, updated_at, symbol, option_symbol, action, side,
                order_type, quantity, limit_price, estimated_premium_usd, status,
                blockers_json, source_type, journal_entry_id, contract_json,
                journal_entry_json, risk_json, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intent.id,
                intent.created_at,
                intent.updated_at,
                intent.symbol,
                intent.option_symbol,
                intent.action,
                intent.side,
                intent.order_type,
                intent.quantity,
                intent.limit_price,
                intent.estimated_premium_usd,
                intent.status,
                json.dumps(intent.blockers, ensure_ascii=False),
                intent.source_type,
                intent.journal_entry_id,
                json.dumps(intent.contract, ensure_ascii=False, sort_keys=True),
                json.dumps(journal_entry or {}, ensure_ascii=False, sort_keys=True),
                json.dumps(intent.risk, ensure_ascii=False, sort_keys=True),
                json.dumps(_scrub_payload(payload), ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.commit()


def _get_intent(db_path: Path, intent_id: str) -> OptionOrderIntent | None:
    with _connect(db_path) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            f"""
            SELECT *
            FROM {OPTIONS_ORDER_INTENTS_TABLE}
            WHERE id = ?
            """,
            (intent_id,),
        ).fetchone()
    if row is None:
        return None
    return OptionOrderIntent(
        id=row["id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        symbol=row["symbol"],
        option_symbol=row["option_symbol"],
        action=row["action"],
        side=row["side"],
        order_type=row["order_type"],
        quantity=int(row["quantity"]),
        limit_price=float(row["limit_price"]),
        estimated_premium_usd=float(row["estimated_premium_usd"]),
        status=row["status"],
        blockers=_json(row["blockers_json"], []),
        source_type=row["source_type"],
        journal_entry_id=row["journal_entry_id"],
        contract=_json(row["contract_json"], {}),
        risk=_json(row["risk_json"], {}),
    )


def _record_paper_order(db_path: Path, intent: OptionOrderIntent, response: dict[str, Any]) -> OptionPaperOrder:
    now = _now()
    order = OptionPaperOrder(
        id="opt-paper-" + uuid4().hex[:16],
        intent_id=intent.id,
        broker_order_id=str(response.get("id") or "") or None,
        status=str(response.get("status") or "submitted"),
        symbol=intent.symbol,
        option_symbol=intent.option_symbol,
        action=intent.action,
        side=intent.side,
        quantity=intent.quantity,
        limit_price=intent.limit_price,
        submitted_at=now,
        updated_at=now,
        broker_response=_scrub_payload(response),
    )
    with _connect(db_path) as connection:
        _ensure_schema(connection)
        connection.execute(
            f"""
            INSERT INTO {OPTIONS_PAPER_ORDERS_TABLE} (
                id, intent_id, broker_order_id, status, symbol, option_symbol,
                action, side, quantity, limit_price, submitted_at, updated_at,
                broker_response_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order.id,
                order.intent_id,
                order.broker_order_id,
                order.status,
                order.symbol,
                order.option_symbol,
                order.action,
                order.side,
                order.quantity,
                order.limit_price,
                order.submitted_at,
                order.updated_at,
                json.dumps(order.broker_response, ensure_ascii=False, sort_keys=True),
            ),
        )
        connection.commit()
    return order


def _get_paper_order(db_path: Path, order_id: str) -> OptionPaperOrder | None:
    with _connect(db_path) as connection:
        _ensure_schema(connection)
        row = connection.execute(
            f"SELECT * FROM {OPTIONS_PAPER_ORDERS_TABLE} WHERE id = ?",
            (order_id,),
        ).fetchone()
    return _paper_order_from_row(row) if row else None


def _update_paper_order_status(db_path: Path, order_id: str, status: str, broker_response: dict[str, Any]) -> OptionPaperOrder:
    now = _now()
    with _connect(db_path) as connection:
        _ensure_schema(connection)
        connection.execute(
            f"""
            UPDATE {OPTIONS_PAPER_ORDERS_TABLE}
            SET status = ?, updated_at = ?, broker_response_json = ?
            WHERE id = ?
            """,
            (status, now, json.dumps(_scrub_payload(broker_response), ensure_ascii=False, sort_keys=True), order_id),
        )
        connection.commit()
    order = _get_paper_order(db_path, order_id)
    if order is None:
        raise ValueError(f"Options paper order was not found after update: {order_id}")
    return order


def _paper_order_from_row(row: sqlite3.Row) -> OptionPaperOrder:
    return OptionPaperOrder(
        id=row["id"],
        intent_id=row["intent_id"],
        broker_order_id=row["broker_order_id"],
        status=row["status"],
        symbol=row["symbol"],
        option_symbol=row["option_symbol"],
        action=row["action"],
        side=row["side"],
        quantity=int(row["quantity"]),
        limit_price=float(row["limit_price"]),
        submitted_at=row["submitted_at"],
        updated_at=row["updated_at"],
        broker_response=_json(row["broker_response_json"], {}),
    )


def _ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OPTIONS_ORDER_INTENTS_TABLE} (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            option_symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            limit_price REAL NOT NULL,
            estimated_premium_usd REAL NOT NULL,
            status TEXT NOT NULL,
            blockers_json TEXT NOT NULL,
            source_type TEXT NOT NULL,
            journal_entry_id TEXT,
            contract_json TEXT NOT NULL,
            journal_entry_json TEXT NOT NULL,
            risk_json TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OPTIONS_PAPER_ORDERS_TABLE} (
            id TEXT PRIMARY KEY,
            intent_id TEXT NOT NULL,
            broker_order_id TEXT,
            status TEXT NOT NULL,
            symbol TEXT NOT NULL,
            option_symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            side TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            limit_price REAL NOT NULL,
            submitted_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            broker_response_json TEXT NOT NULL
        )
        """
    )
    connection.execute(f"CREATE INDEX IF NOT EXISTS idx_{OPTIONS_ORDER_INTENTS_TABLE}_option_symbol ON {OPTIONS_ORDER_INTENTS_TABLE}(option_symbol)")
    connection.execute(f"CREATE INDEX IF NOT EXISTS idx_{OPTIONS_PAPER_ORDERS_TABLE}_intent_id ON {OPTIONS_PAPER_ORDERS_TABLE}(intent_id)")
    connection.commit()


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def _contract_detail(option_symbol: str, source_type: str) -> dict[str, Any]:
    source = "fixture" if source_type == "fixture_read_only" else source_type
    try:
        return options_contract(option_symbol, source=source)
    except Exception as exc:
        return {"option_symbol": option_symbol, "contract": {}, "provider_errors": [{"provider": "options_contract", "error": str(exc)}]}


def _position_from_alpaca(payload: dict[str, Any]) -> OptionPositionSnapshot:
    return OptionPositionSnapshot(
        broker_position_id=str(payload.get("asset_id") or "") or None,
        symbol=str(payload.get("underlying_symbol") or _underlying_from_option_symbol(str(payload.get("symbol") or ""))),
        option_symbol=str(payload.get("symbol") or ""),
        quantity=_float(payload.get("qty"), 0.0),
        market_value=_optional_float(payload.get("market_value")),
        average_entry_price=_optional_float(payload.get("avg_entry_price")),
        unrealized_pl=_optional_float(payload.get("unrealized_pl")),
        raw=_scrub_payload(payload),
    )


def _options_order_safety() -> dict[str, Any]:
    return {
        "broker": "alpaca_paper",
        "live_locked": True,
        "live_order_submission_enabled": False,
        "paper_order_submission_wired": True,
        "llm_order_submission_enabled": False,
        "allowed_actions": sorted(ALLOWED_ACTIONS),
        "blocked_actions": ["sell_to_open", "spreads", "market_live_order", "live_order"],
    }


def _underlying_from_option_symbol(option_symbol: str) -> str:
    match = re.match(r"^([A-Z.]+)\d{6}[CP]\d{8}$", option_symbol)
    return match.group(1) if match else option_symbol[:6]


def _looks_like_option_symbol(value: str) -> bool:
    return bool(re.match(r"^[A-Z.]+\d{6}[CP]\d{8}$", value))


def _clean_option_symbol(value: Any) -> str:
    text = re.sub(r"[^A-Z0-9._-]", "", str(value or "").upper())
    return text[:64]


def _clean_symbol(value: Any) -> str:
    text = re.sub(r"[^A-Z0-9._-]", "", str(value or "").upper())
    return text[:16]


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _json(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _scrub_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: ("<redacted>" if any(token in str(key).lower() for token in ("secret", "api_key", "token")) else _scrub_payload(value))
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_scrub_payload(item) for item in payload]
    return payload


def _redact(value: str) -> str:
    text = str(value)
    for secret in (os.getenv("ALPACA_PAPER_API_KEY", ""), os.getenv("ALPACA_PAPER_SECRET_KEY", "")):
        if secret:
            text = text.replace(secret, "<redacted>")
    return text


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()
