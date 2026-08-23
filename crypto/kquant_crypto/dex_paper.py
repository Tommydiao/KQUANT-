from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

from .evaluation_models import stable_hash


DEX_PAPER_POLICY_VERSION = "crypto_dex_paper_v1.0.0"


@dataclass(frozen=True)
class DexPaperFillRequest:
    """Point-in-time DEX fill inputs; no chart or wallet state is accepted."""

    asset_id: str
    pool_id: str
    side: Literal["buy", "sell"]
    pool_price_usd: float
    liquidity_usd: float
    notional_usd: float
    source_snapshot_id: str
    source_time: str
    security_status: str = "unknown"
    fee_bps: float = 30.0
    tax_rate: float | None = None
    gas_usd: float = 0.0
    max_price_impact_bps: float = 800.0
    max_tax_rate: float = 0.10


@dataclass(frozen=True)
class DexPaperFillQuote:
    quote_id: str
    asset_id: str
    pool_id: str
    side: str
    status: Literal["accepted", "rejected"]
    reason: str | None
    pool_price_usd: float | None
    effective_price_usd: float | None
    base_units: float | None
    notional_usd: float
    liquidity_usd: float | None
    price_impact_bps: float | None
    fee_usd: float | None
    tax_usd: float | None
    gas_usd: float | None
    total_debit_usd: float | None
    total_credit_usd: float | None
    source_snapshot_id: str
    source_time: str
    policy_version: str
    content_hash: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _quote_hash(payload: dict[str, Any]) -> str:
    return stable_hash(payload)


def _rejected(request: DexPaperFillRequest, reason: str, *, pool_price: float | None = None, liquidity: float | None = None) -> DexPaperFillQuote:
    payload = {
        "asset_id": request.asset_id,
        "pool_id": request.pool_id,
        "side": request.side,
        "status": "rejected",
        "reason": reason,
        "source_snapshot_id": request.source_snapshot_id,
        "source_time": request.source_time,
        "policy_version": DEX_PAPER_POLICY_VERSION,
    }
    return DexPaperFillQuote(
        quote_id=f"dex_quote_{uuid4().hex}",
        asset_id=request.asset_id,
        pool_id=request.pool_id,
        side=str(request.side),
        status="rejected",
        reason=reason,
        pool_price_usd=pool_price,
        effective_price_usd=None,
        base_units=None,
        notional_usd=float(request.notional_usd),
        liquidity_usd=liquidity,
        price_impact_bps=None,
        fee_usd=None,
        tax_usd=None,
        gas_usd=None,
        total_debit_usd=None,
        total_credit_usd=None,
        source_snapshot_id=request.source_snapshot_id,
        source_time=request.source_time,
        policy_version=DEX_PAPER_POLICY_VERSION,
        content_hash=_quote_hash(payload),
    )


def quote_dex_fill(request: DexPaperFillRequest) -> DexPaperFillQuote:
    """Estimate a DEX paper fill from the contemporaneous pool snapshot.

    The pool is modeled as a symmetric constant-product reserve where the
    quoted USD liquidity is split equally between base and quote reserves.
    This is deliberately a conservative research approximation, not a wallet
    quote. Missing security, pool depth, tax or source timestamps fail closed.
    """

    if request.side not in {"buy", "sell"}:
        return _rejected(request, "invalid_side")
    if not request.asset_id or not request.pool_id or not request.source_snapshot_id or not request.source_time:
        return _rejected(request, "snapshot_identity_missing")
    if request.security_status.lower() not in {"passed", "pass", "safe"}:
        return _rejected(request, "security_not_passed")
    numeric = (
        request.pool_price_usd,
        request.liquidity_usd,
        request.notional_usd,
        request.fee_bps,
        request.gas_usd,
        request.max_price_impact_bps,
        request.max_tax_rate,
    )
    if any(value != value for value in numeric):
        return _rejected(request, "numeric_input_invalid")
    if request.pool_price_usd <= 0 or request.liquidity_usd <= 0 or request.notional_usd <= 0:
        return _rejected(request, "pool_depth_or_notional_invalid")
    if request.fee_bps < 0 or request.gas_usd < 0 or request.max_price_impact_bps < 0:
        return _rejected(request, "cost_input_invalid")
    if request.tax_rate is None:
        return _rejected(request, "tax_unknown")
    if request.tax_rate < 0 or request.tax_rate > request.max_tax_rate:
        return _rejected(request, "tax_too_high")

    quote_reserve = request.liquidity_usd / 2.0
    impact_ratio = request.notional_usd / quote_reserve
    if request.side == "buy":
        gross_price = request.pool_price_usd * (1.0 + impact_ratio)
    else:
        gross_price = request.pool_price_usd / (1.0 + impact_ratio)
    price_impact_bps = abs(gross_price / request.pool_price_usd - 1.0) * 10_000.0
    if price_impact_bps > request.max_price_impact_bps:
        return _rejected(request, "price_impact_too_high", pool_price=request.pool_price_usd, liquidity=request.liquidity_usd)

    fee_rate = request.fee_bps / 10_000.0
    fee_usd = request.notional_usd * fee_rate
    if request.side == "buy":
        base_units = request.notional_usd / gross_price
        tax_usd = request.notional_usd * request.tax_rate
        total_debit = request.notional_usd + fee_usd + tax_usd + request.gas_usd
        effective_price = total_debit / base_units
        total_credit = None
    else:
        base_units = request.notional_usd / request.pool_price_usd
        gross_credit = base_units * gross_price
        fee_usd = gross_credit * fee_rate
        tax_usd = gross_credit * request.tax_rate
        total_credit = max(0.0, gross_credit - fee_usd - tax_usd - request.gas_usd)
        effective_price = total_credit / base_units
        total_debit = None

    payload = {
        "asset_id": request.asset_id,
        "pool_id": request.pool_id,
        "side": request.side,
        "pool_price_usd": request.pool_price_usd,
        "effective_price_usd": effective_price,
        "base_units": base_units,
        "notional_usd": request.notional_usd,
        "liquidity_usd": request.liquidity_usd,
        "price_impact_bps": price_impact_bps,
        "fee_usd": fee_usd,
        "tax_usd": tax_usd,
        "gas_usd": request.gas_usd,
        "total_debit_usd": total_debit,
        "total_credit_usd": total_credit,
        "source_snapshot_id": request.source_snapshot_id,
        "source_time": request.source_time,
        "policy_version": DEX_PAPER_POLICY_VERSION,
    }
    return DexPaperFillQuote(
        quote_id=f"dex_quote_{uuid4().hex}",
        asset_id=request.asset_id,
        pool_id=request.pool_id,
        side=request.side,
        status="accepted",
        reason=None,
        pool_price_usd=request.pool_price_usd,
        effective_price_usd=effective_price,
        base_units=base_units,
        notional_usd=request.notional_usd,
        liquidity_usd=request.liquidity_usd,
        price_impact_bps=price_impact_bps,
        fee_usd=fee_usd,
        tax_usd=tax_usd,
        gas_usd=request.gas_usd,
        total_debit_usd=total_debit,
        total_credit_usd=total_credit,
        source_snapshot_id=request.source_snapshot_id,
        source_time=request.source_time,
        policy_version=DEX_PAPER_POLICY_VERSION,
        content_hash=_quote_hash(payload),
    )


def realized_paper_r(entry: DexPaperFillQuote, exit_quote: DexPaperFillQuote, risk_usd: float) -> float:
    """Calculate realized R from accepted buy-then-sell paper fills."""

    if entry.status != "accepted" or exit_quote.status != "accepted":
        raise ValueError("paper_fill_not_accepted")
    if entry.side != "buy" or exit_quote.side != "sell":
        raise ValueError("paper_fill_order_must_be_buy_then_sell")
    if entry.base_units is None or exit_quote.base_units is None or entry.total_debit_usd is None or exit_quote.total_credit_usd is None:
        raise ValueError("paper_fill_missing_cashflow")
    if abs(entry.base_units - exit_quote.base_units) > max(1e-12, entry.base_units * 1e-6):
        raise ValueError("paper_fill_units_mismatch")
    if risk_usd <= 0:
        raise ValueError("risk_usd_must_be_positive")
    return (exit_quote.total_credit_usd - entry.total_debit_usd) / risk_usd
