from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


@dataclass(frozen=True)
class ClockCalibration:
    provider: str
    offset_seconds: float
    measured_at: str
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "offset_seconds": self.offset_seconds,
            "measured_at": self.measured_at,
            "source": self.source,
        }


def _server_ms(provider: str, payload: dict[str, Any]) -> int | None:
    if provider == "binance":
        value = payload.get("serverTime")
        return int(value) if value is not None else None
    if provider == "okx":
        values = payload.get("data") or []
        value = values[0].get("ts") if values and isinstance(values[0], dict) else None
        return int(value) if value is not None else None
    if provider == "kraken":
        value = (payload.get("result") or {}).get("unixtime")
        return int(value) * 1000 if value is not None else None
    return None


async def calibrate_provider_clock(provider: str, *, client: httpx.AsyncClient | None = None) -> ClockCalibration | None:
    urls = {
        "binance": "https://api.binance.com/api/v3/time",
        "okx": "https://www.okx.com/api/v5/public/time",
        "kraken": "https://api.kraken.com/0/public/Time",
    }
    url = urls.get(provider)
    if not url:
        return None
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=8)
    try:
        before = datetime.now(UTC)
        response = await client.get(url)
        response.raise_for_status()
        after = datetime.now(UTC)
        server_ms = _server_ms(provider, response.json())
        if server_ms is None:
            return None
        midpoint = before + (after - before) / 2
        server_time = datetime.fromtimestamp(server_ms / 1000, UTC)
        return ClockCalibration(provider, (server_time - midpoint).total_seconds(), after.isoformat(), url)
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return None
    finally:
        if own_client:
            await client.aclose()
