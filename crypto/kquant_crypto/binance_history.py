from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .market_models import NormalizedMarketEvent, content_hash, timestamp_ms
from .parquet_store import ParquetMarketStore


BINANCE_SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"
INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}


def interval_milliseconds(interval: str) -> int:
    normalized = str(interval).strip().lower()
    try:
        return INTERVAL_MS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported Binance interval: {interval}") from exc


def parse_time_milliseconds(value: str | int | None, *, default: int | None = None) -> int | None:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return default
    if text.isdigit():
        return int(text)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def _normalise_symbol(symbol: str) -> str:
    normalized = str(symbol).strip().upper().replace("/", "").replace("-", "")
    if not normalized or not normalized.isalnum():
        raise ValueError(f"Invalid Binance symbol: {symbol}")
    return normalized


def _closed_bar_end(open_time_ms: int, interval_ms: int) -> int:
    return open_time_ms + interval_ms - 1


def _json_request(url: str, timeout: float) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "KQUANT-CRYPTO/0.2"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - public Binance market endpoint only
        return json.loads(response.read().decode("utf-8"))


class BinancePublicKlineClient:
    """Small public REST client for historical spot klines.

    The request callable is injectable so pagination, retry and malformed
    provider responses can be tested without network access.
    """

    def __init__(
        self,
        *,
        base_url: str = BINANCE_SPOT_KLINES_URL,
        timeout: float = 15.0,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        request_json: Callable[[str, float], Any] | None = None,
    ):
        self.base_url = base_url
        self.timeout = max(1.0, float(timeout))
        self.max_retries = max(0, int(max_retries))
        self.sleep = sleep
        self.request_json = request_json or _json_request

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        *,
        start_time_ms: int,
        end_time_ms: int,
        limit: int = 1000,
    ) -> list[list[Any]]:
        symbol = _normalise_symbol(symbol)
        interval_milliseconds(interval)
        if start_time_ms > end_time_ms:
            return []
        bounded_limit = max(1, min(int(limit), 1000))
        query = urlencode({
            "symbol": symbol,
            "interval": interval,
            "startTime": int(start_time_ms),
            "endTime": int(end_time_ms),
            "limit": bounded_limit,
        })
        url = f"{self.base_url}?{query}"
        for attempt in range(self.max_retries + 1):
            try:
                payload = self.request_json(url, self.timeout)
                if not isinstance(payload, list):
                    raise ValueError("Binance klines response is not a list")
                return [list(row) for row in payload if isinstance(row, (list, tuple))]
            except HTTPError as exc:
                retryable = exc.code == 429 or exc.code == 418 or exc.code >= 500
                if not retryable or attempt >= self.max_retries:
                    raise
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                self.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2.0 ** attempt)
            except (URLError, TimeoutError, OSError):
                if attempt >= self.max_retries:
                    raise
                self.sleep(2.0 ** attempt)
        return []


def kline_event(
    symbol: str,
    row: Iterable[Any],
    *,
    interval: str,
    fetched_at: datetime,
) -> NormalizedMarketEvent | None:
    """Convert one Binance REST row into the normalised closed-bar contract."""

    values = list(row)
    if len(values) < 7:
        return None
    try:
        open_time_ms = int(values[0])
        close_time_ms = int(values[6])
    except (TypeError, ValueError):
        return None
    duration = interval_milliseconds(interval)
    if close_time_ms < _closed_bar_end(open_time_ms, duration):
        return None
    if close_time_ms >= int(fetched_at.astimezone(UTC).timestamp() * 1000):
        return None
    trade_count: int | None = None
    if len(values) > 8 and values[8] is not None:
        try:
            trade_count = int(values[8])
        except (TypeError, ValueError):
            trade_count = None
    payload: dict[str, Any] = {
        "interval": interval,
        "open": str(values[1]),
        "high": str(values[2]),
        "low": str(values[3]),
        "close": str(values[4]),
        "volume": str(values[5]),
        "closed": True,
        "close_time": timestamp_ms(close_time_ms),
        "quote_volume": str(values[7]) if len(values) > 7 else None,
        "trade_count": trade_count,
        "taker_buy_volume": str(values[9]) if len(values) > 9 else None,
        "taker_buy_quote_volume": str(values[10]) if len(values) > 10 else None,
        "source": "binance_public_rest_klines",
        "available_at": fetched_at.astimezone(UTC).isoformat(),
    }
    payload = {key: value for key, value in payload.items() if value is not None}
    normalized_symbol = _normalise_symbol(symbol)
    return NormalizedMarketEvent(
        asset_id=f"cex:binance:spot:{normalized_symbol}",
        venue="binance",
        instrument_id=f"binance:spot:{normalized_symbol}",
        market_type="spot",
        event_type="kline",
        source_time=timestamp_ms(open_time_ms),
        received_at=fetched_at.astimezone(UTC).isoformat(),
        sequence=None,
        provider_status="historical",
        content_hash=content_hash(payload),
        payload=payload,
    )


@dataclass(frozen=True)
class BackfillReport:
    symbol: str
    interval: str
    status: str
    pages: int
    rows_written: int
    next_start_ms: int | None
    last_source_time: str | None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "interval": self.interval,
            "status": self.status,
            "pages": self.pages,
            "rows_written": self.rows_written,
            "next_start_ms": self.next_start_ms,
            "last_source_time": self.last_source_time,
            "error": self.error,
        }


class BinanceKlineBackfill:
    """Resumable, public-data-only historical kline writer."""

    STATE_VERSION = 1

    def __init__(
        self,
        store: ParquetMarketStore,
        client: BinancePublicKlineClient,
        *,
        state_path: Path | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.client = client
        self.state_path = state_path or (store.root.parent / "backfill" / "binance_klines_state.json")
        self.now = now or (lambda: datetime.now(UTC))

    def run(
        self,
        symbols: Iterable[str],
        *,
        interval: str = "1m",
        start_at: str | int | None = None,
        end_at: str | int | None = None,
        limit: int = 1000,
        max_pages: int | None = None,
    ) -> list[BackfillReport]:
        duration = interval_milliseconds(interval)
        fetched_at = self.now().astimezone(UTC)
        fetched_ms = int(fetched_at.timestamp() * 1000)
        requested_start = parse_time_milliseconds(start_at)
        if requested_start is None:
            raise ValueError("start_at is required for a new backfill job")
        requested_end = parse_time_milliseconds(end_at, default=(fetched_ms // duration) * duration - 1)
        if requested_end is None or requested_start > requested_end:
            raise ValueError("start_at must be before end_at")
        state = self._load_state()
        reports: list[BackfillReport] = []
        for raw_symbol in symbols:
            symbol = _normalise_symbol(raw_symbol)
            reports.append(self._run_symbol(
                symbol,
                interval=interval,
                duration=duration,
                requested_start=requested_start,
                requested_end=requested_end,
                limit=limit,
                max_pages=max_pages,
                fetched_at=fetched_at,
                state=state,
            ))
        self._save_state(state)
        return reports

    def _run_symbol(
        self,
        symbol: str,
        *,
        interval: str,
        duration: int,
        requested_start: int,
        requested_end: int,
        limit: int,
        max_pages: int | None,
        fetched_at: datetime,
        state: dict[str, Any],
    ) -> BackfillReport:
        key = f"{symbol}:{interval}"
        previous = state.setdefault("jobs", {}).get(key, {})
        cursor = requested_start
        if previous.get("requested_start_ms") == requested_start:
            cursor = max(cursor, int(previous.get("next_start_ms") or cursor))
        pages = 0
        rows_written = 0
        last_source_time = previous.get("last_source_time")
        error: str | None = None
        status = "complete"
        while cursor <= requested_end:
            if max_pages is not None and pages >= max_pages:
                status = "paused"
                break
            try:
                rows = self.client.fetch_klines(
                    symbol,
                    interval,
                    start_time_ms=cursor,
                    end_time_ms=requested_end,
                    limit=limit,
                )
            except Exception as exc:  # persist the cursor before surfacing a provider failure
                status = "error"
                error = type(exc).__name__
                break
            pages += 1
            events: list[NormalizedMarketEvent] = []
            max_open_time: int | None = None
            for row in rows:
                try:
                    open_time = int(row[0])
                except (IndexError, TypeError, ValueError):
                    continue
                if open_time < cursor or open_time > requested_end:
                    continue
                max_open_time = max(open_time, max_open_time or open_time)
                event = kline_event(symbol, row, interval=interval, fetched_at=fetched_at)
                if event is not None and int(row[6]) <= requested_end:
                    events.append(event)
            if events:
                self.store.write_events(events)
                rows_written += len(events)
                last_source_time = events[-1].source_time
            if max_open_time is None or max_open_time < cursor:
                status = "empty" if not events else "error"
                error = None if status == "empty" else "no_cursor_progress"
                break
            cursor = max_open_time + duration
            state["jobs"][key] = {
                "symbol": symbol,
                "interval": interval,
                "requested_start_ms": requested_start,
                "requested_end_ms": requested_end,
                "next_start_ms": cursor,
                "pages": int(previous.get("pages") or 0) + pages,
                "rows_written": int(previous.get("rows_written") or 0) + rows_written,
                "last_source_time": last_source_time,
                "status": "running",
                "updated_at": fetched_at.isoformat(),
            }
            self._save_state(state)
            if len(rows) < max(1, min(int(limit), 1000)):
                # Binance returns a short page at the end of a requested range.
                status = "complete"
                break
        state["jobs"][key] = {
            "symbol": symbol,
            "interval": interval,
            "requested_start_ms": requested_start,
            "requested_end_ms": requested_end,
            "next_start_ms": cursor,
            "pages": int(previous.get("pages") or 0) + pages,
            "rows_written": int(previous.get("rows_written") or 0) + rows_written,
            "last_source_time": last_source_time,
            "status": status,
            "error": error,
            "updated_at": fetched_at.isoformat(),
        }
        return BackfillReport(symbol, interval, status, pages, rows_written, cursor, last_source_time, error)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"version": self.STATE_VERSION, "jobs": {}}
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {"version": self.STATE_VERSION, "jobs": {}}
        if not isinstance(value, dict) or not isinstance(value.get("jobs"), dict):
            return {"version": self.STATE_VERSION, "jobs": {}}
        return {"version": self.STATE_VERSION, "jobs": dict(value["jobs"])}

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.STATE_VERSION,
            "updated_at": self.now().astimezone(UTC).isoformat(),
            "jobs": state.get("jobs", {}),
        }
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)
