from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from uuid import uuid4

import httpx

from .binance_endpoints import SPOT_MARKET_DATA_REST
from .db.migrations import connect, migrate


UNIVERSE_VERSION = "binance_usdt_scan_v1.1.0"
EXECUTION_ALLOWLIST = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})
STABLE_BASE_ASSETS = frozenset({
    "USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "PYUSD", "USDE",
    "USDS", "USD1", "USTC", "EUR", "AEUR", "TRY", "BRL",
})
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class OpportunityCandidate:
    symbol: str
    rank: int
    tier: str
    quote_volume_24h: float
    price_change_pct_24h: float
    spread_bps: float | None
    opportunity_score: float
    tradable: bool
    execution_allowlisted: bool
    material_state_hash: str
    source_time: str
    payload: dict[str, Any]


class BinanceMarketScanner:
    """Build a fail-closed, liquidity-ranked Binance USDT spot universe."""

    def __init__(
        self,
        db_path: Path,
        *,
        request_json: Callable[[str], Any] | None = None,
        watch_limit: int = 150,
        deep_limit: int = 50,
        minimum_quote_volume: float = 10_000_000.0,
        maximum_spread_bps: float = 80.0,
        base_url: str = SPOT_MARKET_DATA_REST,
    ):
        self.db_path = db_path
        self.request_json = request_json or self._request_json
        self.watch_limit = max(1, min(int(watch_limit), 150))
        self.deep_limit = max(1, min(int(deep_limit), self.watch_limit))
        self.minimum_quote_volume = max(0.0, float(minimum_quote_volume))
        self.maximum_spread_bps = max(0.0, float(maximum_spread_bps))
        self.base_url = base_url.rstrip("/")
        self.endpoint_family = "binance_public_market_data"
        self.last_error: str | None = None
        self.last_scan_at: str | None = None
        self.last_scan_id: str | None = None

    def _request_json(self, path: str) -> Any:
        with httpx.Client(base_url=self.base_url, timeout=15.0) as client:
            response = client.get(path)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def _symbol_allowed(item: dict[str, Any]) -> bool:
        symbol = str(item.get("symbol") or "").upper()
        base = str(item.get("baseAsset") or "").upper()
        quote = str(item.get("quoteAsset") or "").upper()
        if not symbol or quote != "USDT" or str(item.get("status") or "").upper() != "TRADING":
            return False
        if item.get("isSpotTradingAllowed") is False or base in STABLE_BASE_ASSETS:
            return False
        if any(base.endswith(suffix) for suffix in LEVERAGED_SUFFIXES):
            return False
        filters = {str(value.get("filterType")): value for value in item.get("filters", ())}
        lot = filters.get("LOT_SIZE") or {}
        price = filters.get("PRICE_FILTER") or {}
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL") or {}
        return _number(lot.get("stepSize")) > 0 and _number(price.get("tickSize")) > 0 and _number(notional.get("minNotional", notional.get("notional"))) > 0

    def build_candidates(
        self,
        exchange_info: dict[str, Any],
        tickers: Iterable[dict[str, Any]],
        books: Iterable[dict[str, Any]],
        *,
        source_time: str,
    ) -> list[OpportunityCandidate]:
        allowed = {str(item["symbol"]).upper(): item for item in exchange_info.get("symbols", ()) if self._symbol_allowed(item)}
        ticker_map = {str(item.get("symbol") or "").upper(): item for item in tickers}
        book_map = {str(item.get("symbol") or "").upper(): item for item in books}
        scored: list[dict[str, Any]] = []
        for symbol, instrument in allowed.items():
            ticker = ticker_map.get(symbol)
            book = book_map.get(symbol)
            if not ticker or not book:
                continue
            quote_volume = _number(ticker.get("quoteVolume"))
            bid = _number(book.get("bidPrice"))
            ask = _number(book.get("askPrice"))
            mid = (bid + ask) / 2 if bid > 0 and ask >= bid else 0.0
            spread_bps = ((ask - bid) / mid * 10_000.0) if mid > 0 else None
            if quote_volume < self.minimum_quote_volume or spread_bps is None or spread_bps > self.maximum_spread_bps:
                continue
            change = _number(ticker.get("priceChangePercent"))
            score = max(0.0, min(100.0, 20.0 * (quote_volume / self.minimum_quote_volume) ** 0.25 + min(abs(change), 20.0) * 2.0 + max(0.0, 30.0 - spread_bps)))
            scored.append({
                "symbol": symbol,
                "quote_volume_24h": quote_volume,
                "price_change_pct_24h": change,
                "spread_bps": spread_bps,
                "opportunity_score": score,
                "instrument": instrument,
                "ticker": ticker,
                "book": book,
            })
        scored.sort(key=lambda item: (item["opportunity_score"], item["quote_volume_24h"]), reverse=True)
        result: list[OpportunityCandidate] = []
        for index, item in enumerate(scored[: self.watch_limit], start=1):
            tier = "deep" if index <= self.deep_limit else "watch"
            material = {
                "symbol": item["symbol"],
                "tier": tier,
                "quote_volume_bucket": int(item["quote_volume_24h"] // 1_000_000),
                "spread_bucket": round(item["spread_bps"], 1),
                "change_bucket": round(item["price_change_pct_24h"], 1),
                "source_time": source_time,
            }
            result.append(OpportunityCandidate(
                symbol=item["symbol"], rank=index, tier=tier,
                quote_volume_24h=item["quote_volume_24h"],
                price_change_pct_24h=item["price_change_pct_24h"],
                spread_bps=item["spread_bps"], opportunity_score=item["opportunity_score"],
                tradable=True, execution_allowlisted=item["symbol"] in EXECUTION_ALLOWLIST,
                material_state_hash=_stable_hash(material), source_time=source_time,
                payload={"instrument": item["instrument"], "ticker": item["ticker"], "book": item["book"]},
            ))
        return result

    def run_once(self) -> dict[str, Any]:
        received_at = _now()
        try:
            exchange_info = dict(self.request_json("/api/v3/exchangeInfo"))
            tickers = list(self.request_json("/api/v3/ticker/24hr"))
            books = list(self.request_json("/api/v3/ticker/bookTicker"))
            source_ms = max((_number(item.get("closeTime")) for item in tickers), default=0.0)
            source_time = datetime.fromtimestamp(source_ms / 1000.0, UTC).isoformat() if source_ms > 0 else received_at
            candidates = self.build_candidates(exchange_info, tickers, books, source_time=source_time)
            content_hash = _stable_hash([asdict(item) for item in candidates])
            scan_id = f"scan_{uuid4().hex}"
            migrate(self.db_path)
            with connect(self.db_path) as conn:
                existing = conn.execute("SELECT scan_id FROM crypto_market_scan_runs WHERE content_hash=?", (content_hash,)).fetchone()
                if existing:
                    scan_id = str(existing["scan_id"])
                else:
                    conn.execute(
                        "INSERT INTO crypto_market_scan_runs(scan_id,universe_version,provider,status,source_time,received_at,eligible_count,watch_count,deep_count,content_hash,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (scan_id, UNIVERSE_VERSION, "binance", "available", source_time, received_at, len(candidates), len(candidates), sum(item.tier == "deep" for item in candidates), content_hash, json.dumps({"watch_limit": self.watch_limit, "deep_limit": self.deep_limit, "endpoint_family": self.endpoint_family, "endpoint": self.base_url, "market_data_only": True, "last_success_at": received_at, "ingestion_lag_seconds": max(0.0, (datetime.fromisoformat(received_at) - datetime.fromisoformat(source_time)).total_seconds())}, sort_keys=True)),
                    )
                    for item in candidates:
                        conn.execute(
                            "INSERT INTO crypto_opportunity_candidates(candidate_id,scan_id,symbol,rank,tier,quote_volume_24h,price_change_pct_24h,spread_bps,opportunity_score,tradable,execution_allowlisted,material_state_hash,source_time,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (f"candidate_{uuid4().hex}", scan_id, item.symbol, item.rank, item.tier, item.quote_volume_24h, item.price_change_pct_24h, item.spread_bps, item.opportunity_score, int(item.tradable), int(item.execution_allowlisted), item.material_state_hash, item.source_time, json.dumps(item.payload, ensure_ascii=True, sort_keys=True)),
                        )
            self.last_error = None
            self.last_scan_at = received_at
            self.last_scan_id = scan_id
            return {"scan_id": scan_id, "status": "available", "source_time": source_time, "received_at": received_at, "endpoint_family": self.endpoint_family, "endpoint": self.base_url, "market_data_only": True, "watch_symbols": [item.symbol for item in candidates], "deep_symbols": [item.symbol for item in candidates if item.tier == "deep"], "candidates": [asdict(item) for item in candidates]}
        except Exception as exc:
            status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            self.last_error = "restricted_location" if status_code == 451 else type(exc).__name__
            self.last_scan_at = received_at
            scan_id = f"scan_{uuid4().hex}"
            details = {"error": self.last_error, "error_type": type(exc).__name__, "http_status": status_code, "endpoint_family": self.endpoint_family, "endpoint": self.base_url, "market_data_only": True}
            migrate(self.db_path)
            with connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO crypto_market_scan_runs(scan_id,universe_version,provider,status,source_time,received_at,eligible_count,watch_count,deep_count,content_hash,details_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (scan_id, UNIVERSE_VERSION, "binance", "unavailable", received_at, received_at, 0, 0, 0, _stable_hash({"scan_id": scan_id, **details}), json.dumps(details, sort_keys=True)),
                )
            self.last_scan_id = scan_id
            return {"scan_id": scan_id, "status": "unavailable", "received_at": received_at, **details, "watch_symbols": [], "deep_symbols": [], "candidates": []}

    async def run_forever(self, on_scan: Callable[[dict[str, Any]], Any] | None = None, *, interval_seconds: float = 900.0) -> None:
        while True:
            result = await asyncio.to_thread(self.run_once)
            if on_scan is not None:
                value = on_scan(result)
                if asyncio.iscoroutine(value):
                    await value
            await asyncio.sleep(max(30.0, float(interval_seconds)))


def scanner_status(db_path: Path) -> dict[str, Any]:
    migrate(db_path)
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM crypto_market_scan_runs ORDER BY received_at DESC LIMIT 1").fetchone()
    if row is None:
        return {"status": "not_collected", "latest": None}
    latest = dict(row)
    try:
        latest["details"] = json.loads(latest.pop("details_json"))
    except (TypeError, ValueError, json.JSONDecodeError):
        latest["details"] = {"error": "invalid_scanner_details"}
    return {"status": str(row["status"]), "latest": latest}


def list_opportunities(db_path: Path, *, current: bool = True, limit: int = 150) -> list[dict[str, Any]]:
    migrate(db_path)
    with connect(db_path) as conn:
        if current:
            latest = conn.execute("SELECT scan_id FROM crypto_market_scan_runs ORDER BY received_at DESC LIMIT 1").fetchone()
            if latest is None:
                return []
            rows = conn.execute("SELECT * FROM crypto_opportunity_candidates WHERE scan_id=? ORDER BY rank LIMIT ?", (latest["scan_id"], max(1, min(limit, 500)))).fetchall()
        else:
            rows = conn.execute("SELECT * FROM crypto_opportunity_candidates ORDER BY source_time DESC, rank LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
    return [dict(row) for row in rows]
