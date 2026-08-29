from __future__ import annotations

import pytest

from kquant_crypto.dex_paper import DexPaperFillRequest, quote_dex_fill, realized_paper_r


def _request(**overrides):
    value = {
        "asset_id": "solana:token",
        "pool_id": "pool:solana:pool",
        "side": "buy",
        "pool_price_usd": 1.0,
        "liquidity_usd": 100_000.0,
        "notional_usd": 1_000.0,
        "source_snapshot_id": "dex-snapshot-1",
        "source_time": "2026-08-23T00:00:00+00:00",
        "security_status": "passed",
        "tax_rate": 0.02,
        "gas_usd": 4.0,
    }
    value.update(overrides)
    return DexPaperFillRequest(**value)


def test_dex_fill_uses_pool_depth_tax_fee_and_gas():
    quote = quote_dex_fill(_request())
    assert quote.status == "accepted"
    assert quote.price_impact_bps == pytest.approx(200.0)
    assert quote.fee_usd == pytest.approx(3.0)
    assert quote.tax_usd == pytest.approx(20.0)
    assert quote.total_debit_usd == pytest.approx(1027.0)
    assert quote.source_snapshot_id == "dex-snapshot-1"


def test_dex_fill_fails_closed_for_unknown_security_tax_or_shallow_pool():
    assert quote_dex_fill(_request(security_status="unknown")).reason == "security_not_passed"
    assert quote_dex_fill(_request(tax_rate=None)).reason == "tax_unknown"
    assert quote_dex_fill(_request(liquidity_usd=10_000.0)).reason == "price_impact_too_high"


def test_dex_sell_quote_and_realized_r_include_exit_costs():
    entry = quote_dex_fill(_request())
    assert entry.base_units is not None
    exit_quote = quote_dex_fill(_request(
        side="sell",
        pool_price_usd=1.2,
        notional_usd=entry.base_units * 1.2,
        gas_usd=4.0,
    ))
    assert exit_quote.status == "accepted"
    assert exit_quote.total_credit_usd is not None
    assert realized_paper_r(entry, exit_quote, risk_usd=100.0) > 0
