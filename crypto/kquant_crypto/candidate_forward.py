"""Public-only forward driver for the isolated candidate simulator.

The caller creates the run and a quotes-execution portfolio. Empty closed batches
with allow_entries=False must cancel pending entries without simulating fills.
State and drained ledger rows are committed together through CandidateStore.save.
No REST price is ever submitted to on_quote. The CLI owns run creation/stop reset.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import time
import uuid

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .strategy_dual_mode_v1 import Bar

REST_URL = "https://data-api.binance.vision"
WS_URL = "wss://data-stream.binance.vision/stream"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
FRESH_SECONDS = 30
HEARTBEAT_SECONDS = 5


class DataUnavailable(ValueError):
    """Incomplete or inconsistent public closed data; never fabricate a bar."""


def aggregate_hour(bars: list[Bar]) -> Bar:
    if len(bars) != 12 or bars[0].start % 3600 or any(
        bar.start != bars[0].start + i * 300 for i, bar in enumerate(bars)
    ):
        raise DataUnavailable("hour requires twelve contiguous closed 5m bars")
    return Bar(bars[0].start, bars[0].open, max(b.high for b in bars),
               min(b.low for b in bars), bars[-1].close, sum(b.volume for b in bars))


def _bar(start, values, interval):
    if type(start) is not int or start % (interval * 1000):
        raise DataUnavailable("unaligned kline start")
    try:
        return Bar(start // 1000, *(float(v) for v in values))
    except (TypeError, ValueError) as exc:
        raise DataUnavailable("invalid OHLCV") from exc


async def _fetch_bars(client, symbol, interval, start, end, max_pages=None):
    """Fetch exact [start,end) range, excluding the current open candle."""
    step = 300 if interval == "5m" else 3600
    result = []
    cursor = start
    pages = 0
    while cursor < end:
        if max_pages is not None and pages >= max_pages:
            raise DataUnavailable("REST page budget exhausted")
        response = await client.get(REST_URL + "/api/v3/klines", params={
            "symbol": symbol, "interval": interval, "startTime": cursor * 1000,
            "endTime": end * 1000 - 1, "limit": 1000,
        })
        response.raise_for_status()
        rows = response.json()
        pages += 1
        if not isinstance(rows, list) or not rows:
            raise DataUnavailable(f"missing {symbol} {interval} at {cursor}")
        for row in rows:
            bar = _bar(row[0], row[1:6], step)
            if bar.start != cursor or bar.start + step > end or row[6] != (bar.start + step) * 1000 - 1:
                raise DataUnavailable(f"noncontiguous/unclosed {symbol} {interval}")
            result.append(bar)
            cursor += step
    return result


async def bootstrap(client, symbols, now):
    hour_end = int(now) // 3600 * 3600
    end = int(now) // 300 * 300
    start = hour_end - 260 * 3600
    five, hourly = {}, {}
    for symbol in symbols:
        five[symbol] = await _fetch_bars(client, symbol, "5m", start, end, max_pages=4)
        native = await _fetch_bars(client, symbol, "1h", start, hour_end, max_pages=1)
        hourly[symbol] = {b.start: b for b in native}
        for i, bar in enumerate(native):
            derived = aggregate_hour(five[symbol][i * 12:(i + 1) * 12])
            if any(not math.isclose(getattr(bar, key), getattr(derived, key), rel_tol=1e-9, abs_tol=1e-8)
                   for key in ("open", "high", "low", "close", "volume")):
                raise DataUnavailable(f"native hour/subbar mismatch: {symbol} {bar.start}")
    return five, hourly


class ForwardFeed:
    """Deterministic common-watermark ingestion, independent of networking."""

    def __init__(self, portfolio, symbols=SYMBOLS, state=None):
        self.portfolio = portfolio
        self.symbols = tuple(s for s in SYMBOLS if s in symbols)
        if not self.symbols or set(symbols) != set(self.symbols):
            raise ValueError("forward supports only the fixed candidate spot symbols")
        state = state or {}
        self.last_close = state.get("last_close")
        self.sequence = dict(state.get("sequence", {}))
        self.parts = {s: [Bar(**b) for b in state.get("parts", {}).get(s, [])] for s in self.symbols}
        self.pending = {s: {} for s in self.symbols}
        self.connected = False
        self.reason = "bootstrap"
        self.last_quote = dict(state.get("last_quote", {}))
        self.records = []

    def event(self, kind, now, **fields):
        self.records.append({"event_id": "forward:" + uuid.uuid4().hex,
                             "kind": kind, "time": now, **fields})

    def snapshot(self):
        return {"last_close": self.last_close, "sequence": self.sequence,
                "parts": {s: [asdict(b) for b in bars] for s, bars in self.parts.items()},
                "last_quote": self.last_quote, "connected": self.connected, "reason": self.reason}

    def valuation_status(self, now):
        positions = self.portfolio.status().get("positions", {})
        stale_symbols = [s for s in positions if not self.connected
                         or not 0 <= now - self.last_quote.get(s, float("-inf")) <= FRESH_SECONDS]
        return {"unable_to_value": bool(stale_symbols), "stale_quote_symbols": stale_symbols,
                "valuation_status": "unable_to_value" if stale_symbols else "available"}

    def stale(self, now):
        expected = int(now) // 300 * 300
        return self.last_close is None or (self.last_close < expected and now - expected > FRESH_SECONDS)

    def pause(self, now, reason):
        if self.reason != reason:
            self.event("FORWARD_PAUSED", now, reason=reason)
        self.reason = reason
        self.portfolio.on_closed_batch({}, {}, int(now), allow_entries=False)
        # The portfolio contract exposes these for operational entry cancellation.
        pending = getattr(self.portfolio, "pending", {})
        for symbol in list(pending):
            self.event("ENTRY_CANCELED", now, symbol=symbol, reason=reason)
            del pending[symbol]

    def heartbeat(self, now):
        if not self.connected or self.stale(now):
            self.pause(now, "disconnected" if not self.connected else "closed_data_stale")

    def _batch(self, bars, now, allow_entries, native=None, scope=None):
        hourly = {}
        for symbol, bar in bars.items():
            parts = self.parts[symbol]
            if bar.start % 3600 == 0:
                parts = []
            parts = parts + [bar]
            if (bar.start + 300) % 3600 == 0:
                derived = aggregate_hour(parts)
                hourly[symbol] = native[symbol][derived.start] if native else derived
                parts = []
            self.parts[symbol] = parts
        self.portfolio.on_closed_batch(bars, hourly, int(now), allow_entries=allow_entries)
        if scope:
            rows = self.portfolio.drain()
            if rows.get("trades"):
                raise RuntimeError("quotes portfolio produced retrospective trades")
            self.records.extend({**row, "evidence_scope": scope} for row in rows.get("events", ()))
            # Historical warmup/backfill account values are not forward performance.
        self.last_close = next(iter(bars.values())).start + 300

    def warmup(self, five, hourly):
        for i in range(len(five[self.symbols[0]])):
            bars = {s: five[s][i] for s in self.symbols}
            self._batch(bars, next(iter(bars.values())).start + 300, False, hourly, "warmup")
        self.event("WARMUP_COMPLETE", self.last_close, evidence_scope="warmup",
                   closed_5m=len(five[self.symbols[0]]), native_1h=260)

    async def backfill(self, client, now):
        self.pause(now, "backfill")
        end = int(now) // 300 * 300
        data = {s: await _fetch_bars(client, s, "5m", self.last_close, end) for s in self.symbols}
        for i in range(len(data[self.symbols[0]])):
            bars = {s: data[s][i] for s in self.symbols}
            self._batch(bars, now, False, scope="recovery")
        if data[self.symbols[0]]:
            self.event("BACKFILL_COMPLETE", now, evidence_scope="recovery",
                       closed_5m=len(data[self.symbols[0]]), allow_entries=False)
        self.pending = {s: {} for s in self.symbols}

    def message(self, message, received_at):
        if not isinstance(message, dict) or not isinstance(message.get("data"), dict):
            raise DataUnavailable("malformed combined stream envelope")
        data = message.get("data", {})
        symbol = data.get("s")
        if symbol not in self.symbols:
            return False
        stream = message.get("stream", "")
        if stream == symbol.lower() + "@bookTicker":
            # Spot bookTicker has no required event-type or exchange timestamp.
            try:
                bid, ask = float(data["b"]), float(data["a"])
                sequence = data["u"]
            except KeyError as exc:
                raise DataUnavailable("missing bookTicker field") from exc
            except (TypeError, ValueError):
                return False
            if (type(sequence) is not int or sequence < 0 or sequence <= self.sequence.get(symbol, -1)
                    or not all(math.isfinite(v) and v > 0 for v in (bid, ask)) or bid > ask):
                return False
            try:
                if "E" in data and not 0 <= received_at - float(data["E"]) / 1000 <= FRESH_SECONDS:
                    return False
            except (TypeError, ValueError):
                return False
            if received_at <= self.last_quote.get(symbol, -1):
                return False
            self.heartbeat(received_at)
            self.sequence[symbol] = sequence
            self.last_quote[symbol] = received_at
            self.event("MARKET_QUOTE", received_at, symbol=symbol, bid=bid, ask=ask,
                       received_at=received_at, sequence=sequence, bbo_valid=True,
                       source=WS_URL, stream=stream)
            self.portfolio.on_quote(symbol, bid, ask, received_at, sequence)
            return True
        if stream != symbol.lower() + "@kline_5m":
            return False
        k = data.get("k", {})
        if not isinstance(k, dict):
            raise DataUnavailable("malformed kline payload")
        if k.get("x") is not True or k.get("i") != "5m" or k.get("s", symbol) != symbol:
            return False
        try:
            bar = _bar(k["t"], [k[key] for key in ("o", "h", "l", "c", "v")], 300)
        except KeyError as exc:
            raise DataUnavailable("missing closed kline field") from exc
        close = bar.start + 300
        if k.get("T") != close * 1000 - 1 or received_at < close:
            raise DataUnavailable("invalid closed kline timestamp")
        if self.last_close is None or close <= self.last_close:
            return False
        old = self.pending[symbol].get(bar.start)
        if old and old[0] != bar:
            raise DataUnavailable("conflicting duplicate closed bar")
        if old is None:
            self.pending[symbol][bar.start] = (bar, received_at)
        # Missing symbols block all new decisions. No later bar may skip the gap.
        while all(self.last_close in self.pending[s] for s in self.symbols):
            batch = {s: self.pending[s][self.last_close][0] for s in self.symbols}
            fresh = self.connected and 0 <= received_at - (self.last_close + 300) <= FRESH_SECONDS
            self._batch(batch, received_at, fresh)
            for s in self.symbols:
                self.pending[s].pop(self.last_close - 300)
            self.reason = "live" if fresh else "late_close_entries_suppressed"
        self.heartbeat(received_at)
        return True


@contextmanager
def _process_lock(path):
    """OS-owned lock released on process death; never a persistent PID lease."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = True
        yield
    finally:
        if locked:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


async def run_forward(portfolio, store, run_id, output_dir: Path,
                      stop_after_seconds: float | None = None):
    """Run public quotes and closed bars; return final status after stop/deadline.

    The run must already exist. Snapshot is portfolio.snapshot() plus a reserved
    ``forward`` checkpoint. Restore, process lock, and stop polling are included.
    Fatal persistence/programming failures propagate; network/data faults retry
    with entries disabled. A successful locked startup clears the previous stop
    flag via store.clear_stop(run_id). Tests can replace AsyncClient and connect.
    """
    if stop_after_seconds is not None and (not math.isfinite(stop_after_seconds) or stop_after_seconds < 0):
        raise ValueError("stop_after_seconds must be nonnegative and finite")
    if getattr(portfolio, "execution", "quotes") != "quotes":
        raise ValueError("forward requires quotes execution")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    def stopped():
        return store.should_stop(run_id) or (stop_after_seconds is not None
                and time.monotonic() - started >= stop_after_seconds)

    with _process_lock(output_dir / "candidate_forward.lock"), store.process_lock(run_id, lease_seconds=60):
        saved = store.load(run_id)
        if saved.get("last_bars") and not saved.get("forward"):
            raise ValueError("nonempty portfolio requires its atomic forward checkpoint")
        if saved:
            driver_fields = {"forward", "status", "unable_to_value", "stale_quote_symbols", "valuation_status"}
            portfolio.restore({k: v for k, v in saved.items() if k not in driver_fields})
        feed = ForwardFeed(portfolio, getattr(portfolio, "policy", {}).get("symbols", SYMBOLS), saved.get("forward"))
        store.clear_stop(run_id)
        lifecycle = "running"

        def persist():
            rows = portfolio.drain()
            rows["events"] = [*feed.records, *rows.get("events", ())]
            state = dict(portfolio.snapshot())
            state["forward"] = feed.snapshot()
            state["status"] = lifecycle
            state.update(feed.valuation_status(time.time()))
            try:
                store.acquire_lock(run_id, lease_seconds=60)
                store.save(run_id, state, **{k: rows.get(k, ()) for k in ("events", "trades", "equity")})
            except Exception as exc:
                # Do not turn a failed atomic ledger write into a network retry.
                raise RuntimeError("forward checkpoint commit failed; stopping writer") from exc
            feed.records.clear()
            status = {**portfolio.status(), "forward": feed.snapshot(), "updated_at": time.time(),
                      "run_id": run_id, "research_only": True, "order_submission": False,
                      "status": lifecycle, **feed.valuation_status(time.time())}
            if status["unable_to_value"]:
                status["last_known_equity"] = status.get("equity")
                status["equity"] = None
            temp = output_dir / "forward_status.json.tmp"
            try:
                temp.write_text(json.dumps(status, sort_keys=True, allow_nan=False), encoding="utf-8")
                os.replace(temp, output_dir / "forward_status.json")
            except OSError as exc:
                raise RuntimeError("forward status publish failed; stopping writer") from exc

        streams = "/".join(s.lower() + suffix for s in feed.symbols for suffix in ("@bookTicker", "@kline_5m"))
        persist()
        async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
            while not stopped():
                try:
                    if feed.last_close is None:
                        five, hourly = await bootstrap(client, feed.symbols, time.time())
                        feed.warmup(five, hourly)
                    else:
                        await feed.backfill(client, time.time())
                    persist()
                    if stopped():
                        break
                    async with connect(WS_URL + "?streams=" + streams, open_timeout=15,
                                       ping_interval=20, ping_timeout=20, max_queue=1) as ws:
                        feed.connected = True
                        last_save = time.monotonic()
                        while not stopped():
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=1)
                                if raw == "" or raw == b"":
                                    raise EOFError("public websocket closed without a message")
                            except asyncio.TimeoutError:
                                raw = None
                            now = time.time()
                            before_count = getattr(portfolio, "count", 0)
                            before_close = feed.last_close
                            before_pending = len(getattr(portfolio, "pending", {}))
                            if raw is not None:
                                try:
                                    message = json.loads(raw)
                                except json.JSONDecodeError as exc:
                                    raise DataUnavailable("malformed websocket JSON") from exc
                                feed.message(message, now)
                            feed.heartbeat(now)
                            critical = (getattr(portfolio, "count", 0) != before_count
                                        or feed.last_close != before_close
                                        or len(getattr(portfolio, "pending", {})) != before_pending)
                            if critical or time.monotonic() - last_save >= HEARTBEAT_SECONDS:
                                persist()
                                last_save = time.monotonic()
                            if feed.stale(now):
                                raise DataUnavailable("missing expected closed bars; REST recovery required")
                except asyncio.CancelledError:
                    lifecycle = "stopped"
                    feed.connected = False
                    feed.pause(time.time(), "cancelled")
                    persist()
                    raise
                except (httpx.HTTPError, ConnectionClosed, EOFError, OSError, asyncio.TimeoutError, DataUnavailable) as exc:
                    feed.connected = False
                    feed.pause(time.time(), type(exc).__name__ + ": " + str(exc))
                    persist()
                    if not stopped():
                        await asyncio.sleep(1)
            lifecycle = "stopped"
            feed.connected = False
            feed.pause(time.time(), "stopped")
            persist()
        result = {**portfolio.status(), "forward": feed.snapshot(), "status": lifecycle,
                  **feed.valuation_status(time.time())}
        if result["unable_to_value"]:
            result["last_known_equity"] = result.get("equity")
            result["equity"] = None
        return result
