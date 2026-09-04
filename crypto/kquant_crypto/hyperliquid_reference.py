from __future__ import annotations

from typing import Any, Callable

import httpx


class HyperliquidPublicReference:
    """Read public HYPE market context without wallet or trading endpoints."""

    def __init__(self, request_json: Callable[[dict[str, Any]], Any] | None = None):
        self.request_json = request_json or self._request_json

    @staticmethod
    def _request_json(payload: dict[str, Any]) -> Any:
        with httpx.Client(base_url="https://api.hyperliquid.xyz", timeout=15.0) as client:
            response = client.post("/info", json=payload)
            response.raise_for_status()
            return response.json()

    def hype_snapshot(self) -> dict[str, Any]:
        try:
            payload = self.request_json({"type": "metaAndAssetCtxs"})
            metadata, contexts = payload
            universe = list(metadata.get("universe") or ())
            index = next((position for position, item in enumerate(universe) if str(item.get("name") or "").upper() == "HYPE"), None)
            if index is None or index >= len(contexts):
                return {"status": "not_listed", "source": "hyperliquid_public", "symbol": "HYPE"}
            context = dict(contexts[index])
            return {
                "status": "available",
                "source": "hyperliquid_public",
                "symbol": "HYPE",
                "mark_price": context.get("markPx"),
                "oracle_price": context.get("oraclePx"),
                "funding": context.get("funding"),
                "open_interest": context.get("openInterest"),
                "day_notional_volume": context.get("dayNtlVlm"),
                "research_only": True,
                "wallet_connected": False,
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "source": "hyperliquid_public",
                "symbol": "HYPE",
                "reason": type(exc).__name__,
                "research_only": True,
                "wallet_connected": False,
            }


__all__ = ["HyperliquidPublicReference"]
