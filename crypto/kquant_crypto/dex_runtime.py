from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .config import Settings
from .db.migrations import migrate
from .dex_models import DexMarketStore, DexSecurityStore, TokenSecurityInput, assess_token_security
from .providers.dexscreener import DexScreenerPublicAdapter, DexScreenerProviderError
from .providers.goplus import GoPlusPublicAdapter


@dataclass
class DexDiscoveryRuntime:
    settings: Settings
    queries: list[str] = field(default_factory=lambda: ["SOL", "WIF", "BONK", "PEPE", "DOGE"])
    interval_seconds: float = 300.0
    adapter: DexScreenerPublicAdapter | None = None
    security_adapter: GoPlusPublicAdapter | Any | None = None
    max_security_checks: int = 20
    _stop: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    last_run_at: str | None = None
    last_status: str = "not_started"
    last_error: str | None = None
    last_discovered: int = 0
    last_saved: int = 0
    last_security_checked: int = 0
    last_security_saved: int = 0

    def __post_init__(self) -> None:
        self.adapter = self.adapter or DexScreenerPublicAdapter()
        if self.security_adapter is None and self.settings.providers.goplus:
            self.security_adapter = GoPlusPublicAdapter(api_key=self.settings.goplus_api_key)
        self.interval_seconds = max(30.0, self.interval_seconds)
        self.max_security_checks = max(1, self.max_security_checks)

    async def run_once(self, *, max_pairs: int = 100) -> dict[str, Any]:
        assert self.adapter is not None
        self.last_run_at = datetime.now(UTC).isoformat()
        try:
            pairs = await asyncio.to_thread(self.adapter.discover, self.queries, max_pairs=max_pairs)
            # DEX discovery runs beside the FastAPI event loop.  SQLite
            # migration and pair upserts are synchronous, so keep them off the
            # loop even when the provider response itself is fast.
            saved = await asyncio.to_thread(self._save_pairs, pairs)
            security_saved = 0
            security_checked = 0
            if self.security_adapter is not None:
                security_store = DexSecurityStore(self.settings.db_path)
                await asyncio.to_thread(migrate, self.settings.db_path)
                unique_pairs = {pair.asset_id: pair for pair in pairs}
                for pair in list(unique_pairs.values())[: self.max_security_checks]:
                    try:
                        value = await asyncio.to_thread(self.security_adapter.inspect, pair.chain_id, pair.base_contract)
                    except Exception:
                        value = TokenSecurityInput(pair.asset_id, pair.chain_id, "goplus", "unavailable")
                    decision = assess_token_security(value)
                    saved_security = await asyncio.to_thread(
                        security_store.save_security,
                        value,
                        decision,
                        source_time=pair.fetched_at,
                        _migrate=False,
                    )
                    security_checked += 1
                    security_saved += int(not saved_security.get("deduplicated", False))
            self.last_status = "available" if pairs else "empty"
            self.last_error = None
            self.last_discovered = len(pairs)
            self.last_saved = sum(1 for item in saved if not item["deduplicated"])
            self.last_security_checked = security_checked
            self.last_security_saved = security_saved
            return {"status": self.last_status, "run_at": self.last_run_at, "discovered": len(pairs), "saved": self.last_saved, "deduplicated": len(saved) - self.last_saved, "security_checked": security_checked, "security_saved": security_saved}
        except DexScreenerProviderError as exc:
            self.last_status = "provider_unavailable"
            self.last_error = str(exc)
            self.last_discovered = 0
            self.last_saved = 0
            self.last_security_checked = 0
            self.last_security_saved = 0
            return {"status": self.last_status, "run_at": self.last_run_at, "discovered": 0, "saved": 0, "security_checked": 0, "security_saved": 0, "error": self.last_error}

        except Exception as exc:
            self.last_status = "error"
            self.last_error = type(exc).__name__
            self.last_discovered = 0
            self.last_saved = 0
            self.last_security_checked = 0
            self.last_security_saved = 0
            return {"status": self.last_status, "run_at": self.last_run_at, "discovered": 0, "saved": 0, "security_checked": 0, "security_saved": 0, "error": self.last_error}

    def _save_pairs(self, pairs: list[Any]) -> list[dict[str, Any]]:
        migrate(self.settings.db_path)
        store = DexMarketStore(self.settings.db_path)
        return store.save_pairs(pairs, _migrate=False)

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict[str, Any]:
        return {
            "provider": "dexscreener",
            "enabled": self.settings.providers.dexscreener,
            "status": self.last_status,
            "last_run_at": self.last_run_at,
            "last_error": self.last_error,
            "last_discovered": self.last_discovered,
            "last_saved": self.last_saved,
            "last_security_checked": self.last_security_checked,
            "last_security_saved": self.last_security_saved,
            "queries": list(self.queries),
            "interval_seconds": self.interval_seconds,
        }

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            await self.run_once()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue
