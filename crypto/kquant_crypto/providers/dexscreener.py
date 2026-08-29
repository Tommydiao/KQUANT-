from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote
from urllib.request import Request, urlopen
from typing import Any, Callable

from ..dex_models import DexPairSnapshot


class DexScreenerProviderError(RuntimeError):
    pass


@dataclass
class DexScreenerPublicAdapter:
    """Read-only adapter for DEX Screener discovery endpoints."""

    base_url: str = "https://api.dexscreener.com"
    timeout_seconds: float = 10.0
    opener: Callable[..., Any] | None = None

    def _get_json(self, path: str) -> dict[str, Any]:
        request = Request(
            f"{self.base_url.rstrip('/')}{path}",
            headers={"Accept": "application/json", "User-Agent": "KQUANT-CRYPTO/0.1"},
            method="GET",
        )
        try:
            response = (self.opener or urlopen)(request, timeout=self.timeout_seconds)
            with response as handle:
                value = json.loads(handle.read().decode("utf-8"))
        except Exception as exc:
            raise DexScreenerProviderError(type(exc).__name__) from exc
        if not isinstance(value, dict):
            raise DexScreenerProviderError("invalid_json_shape")
        return value

    def search(self, query: str) -> list[DexPairSnapshot]:
        normalized = query.strip()
        if not normalized:
            return []
        payload = self._get_json(f"/latest/dex/search?q={quote(normalized)}")
        return self._parse_pairs(payload)

    def pairs(self, chain_id: str, pair_address: str) -> list[DexPairSnapshot]:
        chain = quote(chain_id.strip().lower(), safe="")
        pair = quote(pair_address.strip(), safe="")
        return self._parse_pairs(self._get_json(f"/latest/dex/pairs/{chain}/{pair}"))

    def discover(self, queries: list[str], *, max_pairs: int = 100) -> list[DexPairSnapshot]:
        unique: dict[str, DexPairSnapshot] = {}
        for query in queries:
            for pair in self.search(query):
                unique[pair.pool_id] = pair
        return sorted(
            unique.values(),
            key=lambda item: (item.liquidity_usd or 0.0, item.volume_5m_usd or 0.0),
            reverse=True,
        )[:max(1, min(max_pairs, 500))]

    @staticmethod
    def _parse_pairs(payload: dict[str, Any]) -> list[DexPairSnapshot]:
        raw_pairs = payload.get("pairs")
        if raw_pairs is None:
            raw_pairs = []
        if not isinstance(raw_pairs, list):
            raise DexScreenerProviderError("invalid_pairs_shape")
        parsed: list[DexPairSnapshot] = []
        for raw in raw_pairs:
            if not isinstance(raw, dict):
                continue
            try:
                parsed.append(DexPairSnapshot.from_dexscreener(raw))
            except ValueError:
                # A malformed pair must not contaminate the canonical registry.
                continue
        return parsed
