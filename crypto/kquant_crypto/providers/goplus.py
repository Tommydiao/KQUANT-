from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote
from urllib.request import Request, urlopen
from typing import Any, Callable

from ..dex_models import TokenSecurityInput


class GoPlusProviderError(RuntimeError):
    pass


GOPLUS_CHAIN_IDS = {
    "ethereum": "1",
    "eth": "1",
    "bsc": "56",
    "binance-smart-chain": "56",
    "base": "8453",
    "polygon": "137",
    "arbitrum": "42161",
    "optimism": "10",
    "avalanche": "43114",
}


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip() == "1"


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _top10_concentration(holders: Any) -> float | None:
    if not isinstance(holders, list) or not holders:
        return None
    values: list[float] = []
    for holder in holders[:10]:
        if not isinstance(holder, dict):
            continue
        value = _optional_float(holder.get("percent"))
        if value is not None:
            values.append(value)
    return sum(values) if values else None


def _lp_locked(holders: Any) -> bool | None:
    if not isinstance(holders, list) or not holders:
        return None
    states = [_optional_bool(item.get("is_locked")) for item in holders if isinstance(item, dict)]
    if not states or any(item is None for item in states):
        return None
    return all(states)


@dataclass
class GoPlusPublicAdapter:
    """Read-only GoPlus token security adapter; no wallet or transaction methods."""

    base_url: str = "https://api.gopluslabs.io"
    api_key: str = ""
    timeout_seconds: float = 10.0
    opener: Callable[..., Any] | None = None

    def inspect(self, chain_id: str, contract_address: str) -> TokenSecurityInput:
        chain = chain_id.strip().lower()
        address = contract_address.strip()
        if not chain or not address:
            raise ValueError("chain_id and contract_address are required")
        endpoint_chain = GOPLUS_CHAIN_IDS.get(chain, chain)
        if chain == "solana":
            path = f"/api/v1/solana/token_security?contract_addresses={quote(address, safe='')}"
        else:
            path = f"/api/v1/token_security/{quote(endpoint_chain, safe='')}?contract_addresses={quote(address, safe='')}"
        try:
            payload = self._get_json(path)
        except GoPlusProviderError:
            return TokenSecurityInput(f"{chain}:{address.lower()}", chain, "goplus", "unavailable")
        result = payload.get("result")
        if not isinstance(result, dict):
            return TokenSecurityInput(f"{chain}:{address.lower()}", chain, "goplus", "unavailable")
        raw = result.get(address) or result.get(address.lower())
        if not isinstance(raw, dict):
            raw = next((item for item in result.values() if isinstance(item, dict)), None)
        if raw is None or payload.get("code") not in (1, "1"):
            return TokenSecurityInput(f"{chain}:{address.lower()}", chain, "goplus", "unavailable")
        return TokenSecurityInput(
            asset_id=f"{chain}:{address.lower()}",
            chain_id=chain,
            source="goplus",
            provider_status="live",
            honeypot=_optional_bool(raw.get("is_honeypot")),
            sell_enabled=None if raw.get("cannot_sell_all") is None and raw.get("sell_tax") is None else not bool(_optional_bool(raw.get("cannot_sell_all"))) and (_optional_float(raw.get("sell_tax")) is None or _optional_float(raw.get("sell_tax")) < 1.0),
            buy_tax=_optional_float(raw.get("buy_tax")),
            sell_tax=_optional_float(raw.get("sell_tax")),
            blacklist=_optional_bool(raw.get("is_blacklisted")),
            can_pause=_optional_bool(raw.get("transfer_pausable")),
            can_mint=_optional_bool(raw.get("is_mintable")),
            can_freeze=None,
            lp_locked=_lp_locked(raw.get("lp_holders")),
            top10_concentration=_top10_concentration(raw.get("holders")),
            liquidity_usd=_optional_float((raw.get("dex") or [{}])[0].get("liquidity")) if isinstance(raw.get("dex"), list) and raw.get("dex") else None,
            holder_count=_optional_int(raw.get("holder_count")),
            creator_share=_optional_float(raw.get("creator_percent")),
            lp_share=_top10_concentration(raw.get("lp_holders")),
        )

    def _get_json(self, path: str) -> dict[str, Any]:
        headers = {"Accept": "application/json", "User-Agent": "KQUANT-CRYPTO/0.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(f"{self.base_url.rstrip('/')}{path}", headers=headers, method="GET")
        try:
            response = (self.opener or urlopen)(request, timeout=self.timeout_seconds)
            with response as handle:
                value = json.loads(handle.read().decode("utf-8"))
        except Exception as exc:
            raise GoPlusProviderError(type(exc).__name__) from exc
        if not isinstance(value, dict):
            raise GoPlusProviderError("invalid_json_shape")
        return value
