from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .data_trust import DataSnapshot
from .db.migrations import connect, migrate
from .evaluation_models import stable_hash
from .market_models import NormalizedMarketEvent
from .market_regime import MarketRegimeInput, classify_regime
from .market_runtime import MarketDataRuntime


CORE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
REGIME_INTERVAL = "1H"
REGIME_LOOKBACK_BARS = 24
REGIME_REFRESH_MINUTES = 5


def _dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _return(history: tuple[Any, ...], lookback: int = REGIME_LOOKBACK_BARS) -> float | None:
    if len(history) <= lookback:
        return None
    base = float(history[-1 - lookback].close)
    return None if base == 0 else float(history[-1].close) / base - 1.0


class MarketRegimeRuntime:
    """Build a point-in-time, deterministic market regime snapshot.

    The runtime consumes only closed candles and current provider health.  It
    never calls an LLM and never authorizes alerts or Paper observations.
    """

    def __init__(
        self,
        db_path: Path,
        market_runtime: MarketDataRuntime,
        *,
        symbols: tuple[str, ...] | list[str],
        universe_snapshot_id: str,
    ):
        self.db_path = db_path
        self.market_runtime = market_runtime
        self.symbols = tuple(dict.fromkeys(str(item).strip().upper() for item in symbols if str(item).strip()))
        self.universe_snapshot_id = universe_snapshot_id
        self.events_seen = 0
        self.closed_kline_events_seen = 0
        self.anchor_kline_events_seen = 0
        self.refresh_candidates_seen = 0
        self.snapshots_created = 0
        self.last_as_of: str | None = None
        self.last_error: str | None = None
        self._latest: dict[str, Any] | None = None
        self._persist_lock = asyncio.Lock()
        self._load_latest()

    def _load_latest(self) -> None:
        """Restore the last persisted regime without creating schema writes."""

        try:
            with connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM crypto_market_regime_snapshots ORDER BY as_of_time DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return
                value = dict(row)
                value["data_snapshot_ids"] = json.loads(value.pop("data_snapshot_ids_json"))
                value["evidence"] = json.loads(value.pop("evidence_json"))
                data_snapshot_id = value["data_snapshot_ids"][0] if value["data_snapshot_ids"] else None
                if data_snapshot_id:
                    data_row = conn.execute(
                        "SELECT trust_status,payload_json FROM crypto_data_snapshots WHERE snapshot_id=?",
                        (data_snapshot_id,),
                    ).fetchone()
                    if data_row is not None:
                        value["trust_status"] = str(data_row["trust_status"])
                        value["input"] = json.loads(data_row["payload_json"])
                self._latest = value
                self.last_as_of = value.get("as_of_time")
        except Exception:
            # A missing or pre-migration database must not prevent startup.
            self._latest = None

    def _find_instrument(self, market_type: str, symbol: str) -> str | None:
        suffix = f":{market_type}:{symbol.upper()}"
        return next((item for item in self.market_runtime.buffer.instruments() if item.endswith(suffix)), None)

    def _health(self, instrument_id: str | None) -> dict[str, Any]:
        if not instrument_id:
            return {"status": "unavailable", "age_seconds": None}
        snapshot = self.market_runtime.snapshot(instrument_id)
        return {
            "status": str(snapshot.get("provider_status") or "unknown"),
            "age_seconds": snapshot.get("age_seconds"),
            "last_source_time": snapshot.get("last_source_time"),
            "last_received_at": snapshot.get("last_received_at"),
        }

    def compute(self, *, as_of_time: str | None = None) -> dict[str, Any]:
        as_of = as_of_time or datetime.now(UTC).isoformat()
        histories: dict[str, tuple[Any, ...]] = {}
        health: dict[str, dict[str, Any]] = {}
        returns: dict[str, float | None] = {}
        for symbol in self.symbols:
            instrument = self._find_instrument("spot", symbol)
            history = self.market_runtime.buffer.closed_history(instrument or "", REGIME_INTERVAL)
            histories[symbol] = history
            health[symbol] = self._health(instrument)
            returns[symbol] = _return(history)

        core_symbols = tuple(symbol for symbol in CORE_SYMBOLS if symbol in self.symbols)
        core_returns = {symbol: returns.get(symbol) for symbol in core_symbols}
        alt_returns = [
            value for symbol, value in returns.items()
            if symbol not in set(core_symbols) and value is not None
        ]
        alt_breadth = (sum(value > 0 for value in alt_returns) / len(alt_returns)) if alt_returns else None
        core_ready = all(core_returns.get(symbol) is not None for symbol in core_symbols)
        core_live = all(
            health.get(symbol, {}).get("status") == "live"
            and (
                health.get(symbol, {}).get("age_seconds") is None
                or float(health.get(symbol, {}).get("age_seconds") or 0) <= 120
            )
            for symbol in core_symbols
        )
        data_ready = bool(core_ready and alt_breadth is not None and len(alt_returns) >= 5 and core_live)

        funding_values: list[float] = []
        derivative_health: dict[str, dict[str, Any]] = {}
        for symbol in core_symbols:
            instrument = self._find_instrument("perpetual", symbol)
            derivative_health[symbol] = self._health(instrument)
            if instrument:
                derivative = self.market_runtime.snapshot(instrument).get("derivative") or {}
                try:
                    if derivative.get("funding_rate") is not None:
                        funding_values.append(float(derivative["funding_rate"]))
                except (TypeError, ValueError):
                    continue

        regime_input = MarketRegimeInput(
            btc_return=core_returns.get("BTCUSDT"),
            eth_return=core_returns.get("ETHUSDT"),
            sol_return=core_returns.get("SOLUSDT"),
            alt_breadth=alt_breadth,
            funding_mean=sum(funding_values) / len(funding_values) if funding_values else None,
            oi_change=None,
            liquidation_pressure=None,
            stablecoin_deviation=None,
            data_ready=data_ready,
        )
        classification = classify_regime(regime_input)
        input_payload = {
            "interval": REGIME_INTERVAL,
            "lookback_bars": REGIME_LOOKBACK_BARS,
            "as_of_time": as_of,
            "core_returns": core_returns,
            "symbol_returns": returns,
            "alt_breadth": alt_breadth,
            "alt_sample_count": len(alt_returns),
            "funding_mean": regime_input.funding_mean,
            "oi_change": regime_input.oi_change,
            "liquidation_pressure": regime_input.liquidation_pressure,
            "stablecoin_deviation": regime_input.stablecoin_deviation,
            "data_ready": data_ready,
            "core_health": health,
            "derivative_health": derivative_health,
        }
        trust_status = "live" if data_ready else (
            "stale" if any(item.get("status") == "live" for item in health.values()) else "partial"
        )
        content_hash = stable_hash({
            "universe_snapshot_id": self.universe_snapshot_id,
            "classification": classification,
            "input": input_payload,
        })
        data_snapshot = DataSnapshot.create(
            snapshot_type="crypto_market_regime_inputs",
            source="binance_runtime",
            payload=input_payload,
            trust_status=trust_status,
            source_time=as_of,
            available_at=as_of,
        )
        return {
            "regime_snapshot_id": f"regime_{uuid4().hex}",
            "universe_snapshot_id": self.universe_snapshot_id,
            "data_snapshot": data_snapshot,
            "data_snapshot_ids": [data_snapshot.snapshot_id],
            "content_hash": content_hash,
            "as_of_time": as_of,
            "available_at": datetime.now(UTC).isoformat(),
            "trust_status": trust_status,
            "input": input_payload,
            **classification,
        }

    async def on_market_event(self, event: NormalizedMarketEvent) -> dict[str, Any] | None:
        self.events_seen += 1
        if event.event_type != "kline" or event.market_type != "spot":
            return None
        if str(event.payload.get("interval") or "") not in {"1m", "1", "1M"}:
            return None
        if not bool(event.payload.get("closed")):
            return None
        self.closed_kline_events_seen += 1
        if not event.instrument_id.endswith(":spot:BTCUSDT"):
            return None
        self.anchor_kline_events_seen += 1
        try:
            minute = _dt(event.source_time).minute
        except (TypeError, ValueError):
            return None
        if minute % REGIME_REFRESH_MINUTES != 0 or self.last_as_of == event.source_time:
            return None
        self.refresh_candidates_seen += 1
        result = self.compute(as_of_time=event.source_time)
        async with self._persist_lock:
            try:
                persisted = await asyncio.to_thread(self._persist, result)
            except Exception as exc:  # regime failure must not stop ingestion
                self.last_error = type(exc).__name__
                return {"status": "error", "error": self.last_error}
        self._latest = persisted
        self.last_as_of = event.source_time
        self.snapshots_created += 1
        return persisted

    def _persist(self, result: dict[str, Any]) -> dict[str, Any]:
        migrate(self.db_path)
        snapshot = result["data_snapshot"]
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO crypto_data_snapshots(
                  snapshot_id,snapshot_type,asset_id,instrument_id,venue,source,
                  source_time,available_at,fetched_at,trust_status,content_hash,
                  payload_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(snapshot_type, content_hash) DO NOTHING
                """,
                (
                    snapshot.snapshot_id, snapshot.snapshot_type, snapshot.asset_id,
                    snapshot.instrument_id, snapshot.venue, snapshot.source,
                    snapshot.source_time, snapshot.available_at, snapshot.fetched_at,
                    snapshot.trust_status, snapshot.content_hash,
                    json.dumps(snapshot.payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                    snapshot.fetched_at,
                ),
            )
            row = conn.execute(
                "SELECT snapshot_id FROM crypto_data_snapshots WHERE snapshot_type=? AND content_hash=?",
                (snapshot.snapshot_type, snapshot.content_hash),
            ).fetchone()
            data_snapshot_id = str(row["snapshot_id"] if row else snapshot.snapshot_id)
            conn.execute(
                """
                INSERT INTO crypto_market_regime_snapshots(
                  regime_snapshot_id,universe_snapshot_id,data_snapshot_ids_json,
                  regime,confidence,as_of_time,available_at,content_hash,
                  evidence_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(content_hash) DO NOTHING
                """,
                (
                    result["regime_snapshot_id"], result["universe_snapshot_id"],
                    json.dumps([data_snapshot_id]), result["regime"], result["confidence"],
                    result["as_of_time"], result["available_at"], result["content_hash"],
                    json.dumps(result["evidence"], ensure_ascii=True, sort_keys=True),
                    result["available_at"],
                ),
            )
            regime_row = conn.execute(
                "SELECT regime_snapshot_id FROM crypto_market_regime_snapshots WHERE content_hash=?",
                (result["content_hash"],),
            ).fetchone()
            result = {**result, "data_snapshot_ids": [data_snapshot_id]}
            result["regime_snapshot_id"] = str(regime_row["regime_snapshot_id"] if regime_row else result["regime_snapshot_id"])
        result.pop("data_snapshot", None)
        return result

    def latest(self) -> dict[str, Any] | None:
        return dict(self._latest) if self._latest is not None else None

    def status(self) -> dict[str, Any]:
        latest = self.latest()
        return {
            "status": "running",
            "regime": latest.get("regime") if latest else "DATA_CAUTION",
            "confidence": latest.get("confidence") if latest else "low",
            "trust_status": latest.get("trust_status") if latest else "not_collected",
            "last_as_of": self.last_as_of,
            "snapshots_created": self.snapshots_created,
            "events_seen": self.events_seen,
            "closed_kline_events_seen": self.closed_kline_events_seen,
            "anchor_kline_events_seen": self.anchor_kline_events_seen,
            "refresh_candidates_seen": self.refresh_candidates_seen,
            "last_error": self.last_error,
            "eval_authority": "EVAL only",
        }
