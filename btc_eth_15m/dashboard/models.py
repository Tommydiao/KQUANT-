from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Literal


Side = Literal["long", "short", "flat"]
ExecutionMode = Literal["paper", "testnet", "live"]


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat()


@dataclass(frozen=True)
class LeverageDecision:
    leverage: int
    confidence: float
    max_allowed_leverage: int
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RiskGate:
    name: str
    passed: bool
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OrderDraft:
    id: str
    symbol: str
    side: Literal["long", "short"]
    mode: ExecutionMode
    bar_time: str
    entry_price: float
    stop_price: float
    target_price: float
    quantity: float
    margin_usdt: float
    notional_usdt: float
    leverage: int
    max_allowed_leverage: int
    confidence: float
    status: Literal["blocked", "ready"]
    blocked_reasons: list[str]
    explanation: dict
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SignalSnapshot:
    symbol: str
    status: str
    bar_time: str | None
    side: Side
    close: float | None
    atr: float | None
    rsi: float | None
    confidence: float
    leverage: int | None
    explanation: dict
    order_draft: OrderDraft | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["order_draft"] = self.order_draft.to_dict() if self.order_draft else None
        return payload
