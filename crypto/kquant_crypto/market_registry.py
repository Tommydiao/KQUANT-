from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from .db.migrations import connect, migrate
from .market_models import NormalizedMarketEvent


_QUOTE_ASSETS = ("USDT", "USDC", "USD", "BTC", "ETH", "BNB")


def _base_symbol(asset_id: str, instrument_id: str) -> str:
    if asset_id.startswith("asset:"):
        value = asset_id.removeprefix("asset:").strip()
        if value:
            return value.upper()
    value = instrument_id.rsplit(":", 1)[-1].upper()
    value = re.sub(r"-(SWAP|SPOT)$", "", value)
    value = value.replace("/", "-")
    for quote in _QUOTE_ASSETS:
        if value.endswith(f"-{quote}"):
            return value[: -(len(quote) + 1)]
        if value.endswith(quote) and len(value) > len(quote):
            return value[: -len(quote)]
    return value


def _quote_asset(instrument_id: str) -> str:
    value = instrument_id.rsplit(":", 1)[-1].upper().replace("/", "-")
    value = re.sub(r"-(SWAP|SPOT)$", "", value)
    for quote in _QUOTE_ASSETS:
        if value.endswith(f"-{quote}") or value.endswith(quote):
            return quote
    return "UNKNOWN"


def register_market_identity(db_path: Path, event: NormalizedMarketEvent) -> None:
    """Persist first-seen CEX identity without writing every market tick."""

    if not event.asset_id or not event.instrument_id or not event.venue:
        return
    if ":" not in event.instrument_id:
        return
    now = datetime.now(UTC).isoformat()
    symbol = _base_symbol(event.asset_id, event.instrument_id)
    asset_kind = "native" if symbol in {"BTC", "ETH", "SOL"} else "unknown"
    provider_symbol = event.instrument_id.rsplit(":", 1)[-1]
    display_name = event.venue.upper()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO crypto_venues(venue_id,display_name,venue_type,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(venue_id) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (event.venue, display_name, "cex", "active", now, now),
        )
        conn.execute(
            """
            INSERT INTO crypto_assets(
              asset_id,symbol,name,asset_kind,canonical_chain_id,
              canonical_contract_address,status,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(asset_id) DO UPDATE SET updated_at=excluded.updated_at
            """,
            (event.asset_id, symbol, symbol, asset_kind, None, None, "active", now, now),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO crypto_instruments(
              instrument_id,asset_id,venue_id,market_type,provider_symbol,
              quote_asset,status,effective_from,effective_to,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event.instrument_id,
                event.asset_id,
                event.venue,
                event.market_type if event.market_type in {"spot", "perpetual", "future", "reference"} else "reference",
                provider_symbol,
                _quote_asset(event.instrument_id),
                "active",
                event.source_time or now,
                None,
                json.dumps({"source": "public_market_event"}, ensure_ascii=True, sort_keys=True),
            ),
        )
