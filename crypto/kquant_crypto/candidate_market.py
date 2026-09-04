from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import httpx

from .binance_endpoints import FUTURES_MARKET_DATA_REST, SPOT_MARKET_DATA_REST
from .db.migrations import connect, migrate
from .universe_catalog import InstrumentDefinition


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class BinanceCandidateMarketVerifier:
    """Verify configured candidate contracts against public exchange metadata."""

    def __init__(self, db_path: Path, request_json: Callable[[str, str], dict[str, Any]] | None = None):
        self.db_path = db_path
        self.request_json = request_json or self._request_json

    @staticmethod
    def _request_json(market_type: str, path: str) -> dict[str, Any]:
        base_url = FUTURES_MARKET_DATA_REST if market_type == "perpetual" else SPOT_MARKET_DATA_REST
        with httpx.Client(base_url=base_url, timeout=15.0) as client:
            response = client.get(path)
            response.raise_for_status()
            return dict(response.json())

    @staticmethod
    def _rules(item: dict[str, Any]) -> dict[str, Any]:
        filters = {str(value.get("filterType") or ""): value for value in item.get("filters", ())}
        price = filters.get("PRICE_FILTER") or {}
        lot = filters.get("LOT_SIZE") or {}
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        return {
            "tick_size": _number(price.get("tickSize")),
            "step_size": _number(lot.get("stepSize")),
            "min_qty": _number(lot.get("minQty")),
            "min_notional": _number(notional.get("minNotional", notional.get("notional"))),
        }

    def verify(self, instruments: tuple[InstrumentDefinition, ...]) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        by_market = {"spot": [], "perpetual": []}
        for item in instruments:
            by_market.setdefault(item.market_type, []).append(item)
        results: list[dict[str, Any]] = []
        for market_type, values in by_market.items():
            if not values:
                continue
            path = "/fapi/v1/exchangeInfo" if market_type == "perpetual" else "/api/v3/exchangeInfo"
            try:
                payload = self.request_json(market_type, path)
                exchange_symbols = {str(item.get("symbol") or "").upper(): item for item in payload.get("symbols", ())}
                for definition in values:
                    exchange_item = exchange_symbols.get(definition.symbol)
                    status = str((exchange_item or {}).get("status") or "").upper()
                    rules = self._rules(exchange_item or {})
                    tradable = bool(exchange_item and status == "TRADING" and rules["tick_size"] and rules["step_size"])
                    results.append({
                        **definition.as_dict(),
                        "listing_status": "verified_trading" if tradable else "not_trading",
                        "tradable": tradable,
                        "exchange_status": status or "NOT_FOUND",
                        "rules": rules,
                        "verified_at": now,
                    })
            except Exception as exc:
                for definition in values:
                    results.append({
                        **definition.as_dict(),
                        "listing_status": "verification_unavailable",
                        "tradable": False,
                        "exchange_status": "UNKNOWN",
                        "rules": {},
                        "verified_at": now,
                        "error": type(exc).__name__,
                    })
        migrate(self.db_path)
        with connect(self.db_path) as conn:
            for result in results:
                metadata = {"exchange_status": result["exchange_status"], "rules": result["rules"], "verified_at": now}
                if result.get("error"):
                    metadata["verification_error"] = result["error"]
                conn.execute(
                    "UPDATE crypto_instruments SET status=?,metadata_json=? WHERE instrument_id=?",
                    (
                        "active" if result["tradable"] else "research_only",
                        json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                        result["instrument_id"],
                    ),
                )
                conn.execute(
                    "UPDATE crypto_universe_instrument_memberships SET listing_status=?,metadata_json=? WHERE instrument_id=? AND effective_to IS NULL",
                    (
                        result["listing_status"],
                        json.dumps(metadata, ensure_ascii=True, sort_keys=True),
                        result["instrument_id"],
                    ),
                )
        return {
            "status": "available" if results and all(item["listing_status"] != "verification_unavailable" for item in results) else "data_caution",
            "verified_at": now,
            "items": results,
            "execution_allowlist_unchanged": True,
        }


__all__ = ["BinanceCandidateMarketVerifier"]
