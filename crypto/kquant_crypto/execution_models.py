from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class ExecutionIntent:
    intent_id: str
    evaluation_id: str
    strategy_version: str
    symbol: str
    market_type: str
    direction: str
    entry_limit: float
    stop_price: float
    target_price: float
    validation_gate_status: str
    material_state_hash: str
    created_at: str
    expires_at: str
    requested_risk_fraction: float = 0.01

    @classmethod
    def create(cls, **values: Any) -> "ExecutionIntent":
        return cls(
            intent_id=str(values.get("intent_id") or f"intent_{uuid4().hex}"),
            evaluation_id=str(values["evaluation_id"]),
            strategy_version=str(values["strategy_version"]),
            symbol=str(values["symbol"]).upper(),
            market_type=str(values["market_type"]).lower(),
            direction=str(values["direction"]).lower(),
            entry_limit=float(values["entry_limit"]),
            stop_price=float(values["stop_price"]),
            target_price=float(values["target_price"]),
            validation_gate_status=str(values.get("validation_gate_status") or "NO_GO").upper(),
            material_state_hash=str(values["material_state_hash"]),
            created_at=str(values.get("created_at") or utc_now()),
            expires_at=str(values["expires_at"]),
            requested_risk_fraction=float(values.get("requested_risk_fraction", 0.01)),
        )

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class SymbolTradingRules:
    symbol: str
    market_type: str
    min_qty: float
    step_size: float
    min_notional: float
    tick_size: float
    tradable: bool = True


@dataclass(frozen=True)
class ExchangePosition:
    symbol: str
    market_type: str
    direction: str
    quantity: float
    entry_price: float
    mark_price: float
    stop_price: float | None = None

    @property
    def open_risk_usdt(self) -> float:
        if self.stop_price is None or self.quantity <= 0:
            return 0.0
        return abs(self.entry_price - self.stop_price) * self.quantity


@dataclass(frozen=True)
class AccountRiskSnapshot:
    snapshot_id: str
    mode: str
    equity_usdt: float
    available_usdt: float
    daily_realized_pnl_usdt: float
    positions: tuple[ExchangePosition, ...] = ()
    open_order_count: int = 0
    captured_at: str = field(default_factory=utc_now)

    @property
    def open_risk_usdt(self) -> float:
        return sum(item.open_risk_usdt for item in self.positions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "mode": self.mode,
            "equity_usdt": self.equity_usdt,
            "available_usdt": self.available_usdt,
            "daily_realized_pnl_usdt": self.daily_realized_pnl_usdt,
            "positions": [item.__dict__ for item in self.positions],
            "open_order_count": self.open_order_count,
            "open_risk_usdt": self.open_risk_usdt,
            "captured_at": self.captured_at,
        }


@dataclass(frozen=True)
class ExecutionRiskDecision:
    decision_id: str
    intent_id: str
    allowed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    quantity: float
    estimated_notional: float
    estimated_risk_usdt: float
    capital_basis_usdt: float
    decided_at: str = field(default_factory=utc_now)

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.__dict__,
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
        }


def account_snapshot_from_mapping(value: Mapping[str, Any]) -> AccountRiskSnapshot:
    positions = tuple(
        ExchangePosition(
            symbol=str(item["symbol"]).upper(),
            market_type=str(item["market_type"]),
            direction=str(item["direction"]),
            quantity=abs(float(item["quantity"])),
            entry_price=float(item["entry_price"]),
            mark_price=float(item.get("mark_price") or item["entry_price"]),
            stop_price=float(item["stop_price"]) if item.get("stop_price") is not None else None,
        )
        for item in value.get("positions", ())
    )
    return AccountRiskSnapshot(
        snapshot_id=str(value.get("snapshot_id") or f"account_{uuid4().hex}"),
        mode=str(value.get("mode") or "disabled"),
        equity_usdt=float(value.get("equity_usdt") or 0.0),
        available_usdt=float(value.get("available_usdt") or 0.0),
        daily_realized_pnl_usdt=float(value.get("daily_realized_pnl_usdt") or 0.0),
        positions=positions,
        open_order_count=int(value.get("open_order_count") or 0),
        captured_at=str(value.get("captured_at") or utc_now()),
    )
