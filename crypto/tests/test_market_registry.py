from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from kquant_crypto.db.migrations import migrate
from kquant_crypto.market_models import NormalizedMarketEvent, content_hash
from kquant_crypto.market_registry import register_market_identity


def _event() -> NormalizedMarketEvent:
    payload = {"last": "100"}
    return NormalizedMarketEvent(
        asset_id="asset:btc",
        venue="binance",
        instrument_id="binance:spot:BTCUSDT",
        market_type="spot",
        event_type="ticker",
        source_time=datetime(2026, 8, 23, tzinfo=UTC).isoformat(),
        received_at=datetime(2026, 8, 23, 0, 0, 1, tzinfo=UTC).isoformat(),
        sequence=None,
        provider_status="live",
        content_hash=content_hash(payload),
        payload=payload,
    )


def test_first_market_event_registers_canonical_cex_identity(settings):
    migrate(settings.db_path)
    register_market_identity(settings.db_path, _event())
    register_market_identity(settings.db_path, _event())
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM crypto_venues WHERE venue_id='binance'").fetchone()[0] == 1
        assert conn.execute("SELECT symbol FROM crypto_assets WHERE asset_id='asset:btc'").fetchone()[0] == "BTC"
        row = conn.execute("SELECT quote_asset,market_type FROM crypto_instruments WHERE instrument_id='binance:spot:BTCUSDT'").fetchone()
    assert row == ("USDT", "spot")
