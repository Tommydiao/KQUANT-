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

from .binance_history import parse_time_milliseconds
from .market_models import NormalizedMarketEvent, content_hash, timestamp_ms
from .parquet_store import ParquetMarketStore


BINANCE_FUNDING_RATE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_OPEN_INTEREST_URL = "https://fapi.binance.com/futures/data/openInterestHist"
OPEN_INTEREST_PERIOD_MS: dict[str, int] = {
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def _normalise_symbol(symbol: str) -> str:
    normalized = str(symbol).strip().upper().replace("/", "").replace("-", "")
    if not normalized or not normalized.isalnum():
        raise ValueError(f"Invalid Binance symbol: {symbol}")
    return normalized


def _asset_id(symbol: str) -> str:
    upper = _normalise_symbol(symbol)
    for quote in ("USDT", "USDC", "BUSD", "FDUSD", "BTC", "ETH", "BNB"):
        if upper.endswith(quote) and len(upper) > len(quote):
            return f"asset:{upper[:-len(quote)].lower()}"
    return f"asset:{upper.lower()}"


def _json_request(url: str, timeout: float) -> Any:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "KQUANT-CRYPTO/0.2"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - public Binance market endpoint only
        return json.loads(response.read().decode("utf-8"))


def _timestamp_from_row(row: dict[str, Any], key: str) -> int | None:
    value = row.get(key)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class BinancePublicDerivativeClient:
    """Public USD-M futures history client; it never accepts credentials."""

    def __init__(
        self,
        *,
        funding_url: str = BINANCE_FUNDING_RATE_URL,
        open_interest_url: str = BINANCE_OPEN_INTEREST_URL,
        timeout: float = 15.0,
        max_retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        request_json: Callable[[str, float], Any] | None = None,
    ):
        self.funding_url = funding_url
        self.open_interest_url = open_interest_url
        self.timeout = max(1.0, float(timeout))
        self.max_retries = max(0, int(max_retries))
        self.sleep = sleep
        self.request_json = request_json or _json_request

    def _request(self, base_url: str, params: dict[str, Any]) -> Any:
        url = f"{base_url}?{urlencode(params)}"
        for attempt in range(self.max_retries + 1):
            try:
                return self.request_json(url, self.timeout)
            except HTTPError as exc:
                retryable = exc.code in {418, 429} or exc.code >= 500
                if not retryable or attempt >= self.max_retries:
                    raise
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                self.sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2.0 ** attempt)
            except (URLError, TimeoutError, OSError):
                if attempt >= self.max_retries:
                    raise
                self.sleep(2.0 ** attempt)
        return []

    def fetch_funding_rates(self, symbol: str, *, start_time_ms: int, end_time_ms: int, limit: int = 1000) -> list[dict[str, Any]]:
        payload = self._request(self.funding_url, {
            "symbol": _normalise_symbol(symbol),
            "startTime": int(start_time_ms),
            "endTime": int(end_time_ms),
            "limit": max(1, min(int(limit), 1000)),
        })
        if not isinstance(payload, list):
            raise ValueError("Binance funding response is not a list")
        return [dict(row) for row in payload if isinstance(row, dict)]

    def fetch_open_interest(self, symbol: str, *, period: str, start_time_ms: int, end_time_ms: int, limit: int = 500) -> list[dict[str, Any]]:
        normalized_period = str(period).strip().lower()
        if normalized_period not in OPEN_INTEREST_PERIOD_MS:
            raise ValueError(f"Unsupported open-interest period: {period}")
        payload = self._request(self.open_interest_url, {
            "symbol": _normalise_symbol(symbol),
            "period": normalized_period,
            "startTime": int(start_time_ms),
            "endTime": int(end_time_ms),
            "limit": max(1, min(int(limit), 500)),
        })
        if not isinstance(payload, list):
            raise ValueError("Binance open-interest response is not a list")
        return [dict(row) for row in payload if isinstance(row, dict)]


def funding_event(
    symbol: str,
    row: dict[str, Any],
    *,
    fetched_at: datetime,
    source: str = "binance_public_rest_funding_rate",
) -> NormalizedMarketEvent | None:
    normalized = _normalise_symbol(symbol)
    source_ms = _timestamp_from_row(row, "fundingTime")
    if source_ms is None or source_ms >= int(fetched_at.astimezone(UTC).timestamp() * 1000):
        return None
    try:
        funding_rate = float(row["fundingRate"])
    except (KeyError, TypeError, ValueError):
        return None
    source_time = timestamp_ms(source_ms)
    payload = {
        "symbol": normalized,
        "funding_rate": funding_rate,
        "mark_price": row.get("markPrice"),
        "rate_type": row.get("rateType", "Regular"),
        "funding_time": source_time,
        "source": source,
        "available_at": source_time,
        "retrieved_at": fetched_at.astimezone(UTC).isoformat(),
        "provenance": "historical_rest_replay",
    }
    return NormalizedMarketEvent(
        asset_id=_asset_id(normalized),
        venue="binance",
        instrument_id=f"binance:perpetual:{normalized}",
        market_type="perpetual",
        event_type="funding_rate",
        source_time=source_time,
        received_at=fetched_at.astimezone(UTC).isoformat(),
        sequence=None,
        provider_status="historical",
        content_hash=content_hash(payload),
        payload=payload,
    )


def open_interest_event(symbol: str, row: dict[str, Any], *, period: str, fetched_at: datetime) -> NormalizedMarketEvent | None:
    normalized = _normalise_symbol(symbol)
    source_ms = _timestamp_from_row(row, "timestamp")
    if source_ms is None or source_ms >= int(fetched_at.astimezone(UTC).timestamp() * 1000):
        return None
    try:
        open_interest = float(row["sumOpenInterest"])
    except (KeyError, TypeError, ValueError):
        return None
    source_time = timestamp_ms(source_ms)
    payload = {
        "symbol": normalized,
        "period": period,
        "open_interest": open_interest,
        "open_interest_value": row.get("sumOpenInterestValue"),
        "timestamp": source_time,
        "source": "binance_public_rest_open_interest",
        "available_at": source_time,
        "retrieved_at": fetched_at.astimezone(UTC).isoformat(),
        "provenance": "historical_rest_replay",
    }
    return NormalizedMarketEvent(
        asset_id=_asset_id(normalized),
        venue="binance",
        instrument_id=f"binance:perpetual:{normalized}",
        market_type="perpetual",
        event_type="open_interest",
        source_time=source_time,
        received_at=fetched_at.astimezone(UTC).isoformat(),
        sequence=None,
        provider_status="historical",
        content_hash=content_hash(payload),
        payload=payload,
    )


@dataclass(frozen=True)
class DerivativeBackfillReport:
    symbol: str
    period: str
    funding_status: str
    funding_rows: int
    open_interest_status: str
    open_interest_rows: int
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "period": self.period,
            "funding_status": self.funding_status,
            "funding_rows": self.funding_rows,
            "open_interest_status": self.open_interest_status,
            "open_interest_rows": self.open_interest_rows,
            "error": self.error,
        }


class BinanceDerivativeBackfill:
    """Resumable public Funding/OI history writer."""

    STATE_VERSION = 1

    def __init__(
        self,
        store: ParquetMarketStore,
        client: BinancePublicDerivativeClient,
        *,
        state_path: Path | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.store = store
        self.client = client
        self.state_path = state_path or (store.root.parent / "backfill" / "binance_derivatives_state.json")
        self.now = now or (lambda: datetime.now(UTC))

    def run(
        self,
        symbols: Iterable[str],
        *,
        start_at: str | int,
        end_at: str | int | None = None,
        period: str = "1h",
        limit: int = 500,
        max_pages: int | None = None,
    ) -> list[DerivativeBackfillReport]:
        if period not in OPEN_INTEREST_PERIOD_MS:
            raise ValueError(f"Unsupported open-interest period: {period}")
        fetched_at = self.now().astimezone(UTC)
        fetched_ms = int(fetched_at.timestamp() * 1000)
        requested_start = parse_time_milliseconds(start_at)
        requested_end = parse_time_milliseconds(end_at, default=fetched_ms - 1)
        if requested_start is None or requested_end is None or requested_start > requested_end:
            raise ValueError("start_at must be before end_at")
        state = self._load_state()
        reports: list[DerivativeBackfillReport] = []
        for raw_symbol in symbols:
            symbol = _normalise_symbol(raw_symbol)
            funding_status, funding_rows, funding_error = self._run_series(
                symbol,
                endpoint="funding",
                period=period,
                requested_start=requested_start,
                requested_end=requested_end,
                limit=min(limit, 1000),
                max_pages=max_pages,
                fetched_at=fetched_at,
                state=state,
            )
            oi_status, oi_rows, oi_error = self._run_series(
                symbol,
                endpoint="open_interest",
                period=period,
                requested_start=requested_start,
                requested_end=requested_end,
                limit=min(limit, 500),
                max_pages=max_pages,
                fetched_at=fetched_at,
                state=state,
            )
            reports.append(DerivativeBackfillReport(
                symbol=symbol,
                period=period,
                funding_status=funding_status,
                funding_rows=funding_rows,
                open_interest_status=oi_status,
                open_interest_rows=oi_rows,
                error=funding_error or oi_error,
            ))
        self._save_state(state)
        return reports

    def _run_series(
        self,
        symbol: str,
        *,
        endpoint: str,
        period: str,
        requested_start: int,
        requested_end: int,
        limit: int,
        max_pages: int | None,
        fetched_at: datetime,
        state: dict[str, Any],
    ) -> tuple[str, int, str | None]:
        key = f"{endpoint}:{symbol}:{period}"
        previous = state.setdefault("jobs", {}).get(key, {})
        cursor = requested_start
        if previous.get("requested_start_ms") == requested_start:
            cursor = max(cursor, int(previous.get("next_start_ms") or cursor))
        pages = 0
        rows_written = 0
        status = "complete"
        error: str | None = None
        step = OPEN_INTEREST_PERIOD_MS[period] if endpoint == "open_interest" else 1
        pending_end = None
        if previous.get("requested_start_ms") == requested_start and previous.get("pending_end_ms") is not None:
            try:
                pending_end = min(requested_end, int(previous["pending_end_ms"]))
            except (TypeError, ValueError):
                pending_end = None
        page_end = pending_end or requested_end
        while cursor <= page_end:
            if max_pages is not None and pages >= max_pages:
                status = "paused"
                break
            try:
                rows = (
                    self.client.fetch_funding_rates(symbol, start_time_ms=cursor, end_time_ms=page_end, limit=limit)
                    if endpoint == "funding"
                    else self.client.fetch_open_interest(symbol, period=period, start_time_ms=cursor, end_time_ms=page_end, limit=limit)
                )
            except Exception as exc:
                status = "error"
                error = type(exc).__name__
                break
            pages += 1
            events: list[NormalizedMarketEvent] = []
            min_source_ms: int | None = None
            max_source_ms: int | None = None
            for row in rows:
                source_ms = _timestamp_from_row(row, "fundingTime" if endpoint == "funding" else "timestamp")
                if source_ms is None or source_ms < cursor or source_ms > requested_end:
                    continue
                min_source_ms = source_ms if min_source_ms is None else min(source_ms, min_source_ms)
                max_source_ms = source_ms if max_source_ms is None else max(source_ms, max_source_ms)
                event = funding_event(symbol, row, fetched_at=fetched_at) if endpoint == "funding" else open_interest_event(symbol, row, period=period, fetched_at=fetched_at)
                if event is not None:
                    events.append(event)
            if events:
                self.store.write_events(events)
                rows_written += len(events)
            if max_source_ms is None or max_source_ms < cursor:
                status = "empty" if not events else "error"
                error = None if status == "empty" else "no_cursor_progress"
                break

            # Some historical OI responses are capped from the end of the
            # requested interval. If a full page reaches the requested end
            # but starts after the cursor, preserve the tail and backfill the
            # missing prefix with a narrowed endTime. Without this branch the
            # run would incorrectly mark a partial series as complete.
            if (
                endpoint == "open_interest"
                and pending_end is None
                and len(rows) >= limit
                and min_source_ms is not None
                and min_source_ms > cursor
                and max_source_ms >= requested_end
            ):
                pending_end = min_source_ms - step
                if pending_end < cursor:
                    status = "complete"
                    cursor = requested_end + step
                    break
                page_end = pending_end
                state["jobs"][key] = {
                    "endpoint": endpoint,
                    "symbol": symbol,
                    "period": period,
                    "requested_start_ms": requested_start,
                    "requested_end_ms": requested_end,
                    "next_start_ms": cursor,
                    "pending_end_ms": pending_end,
                    "pages": int(previous.get("pages") or 0) + pages,
                    "rows_written": int(previous.get("rows_written") or 0) + rows_written,
                    "status": "running",
                    "updated_at": fetched_at.isoformat(),
                }
                self._save_state(state)
                continue

            cursor = max_source_ms + step
            if pending_end is not None and cursor > pending_end:
                status = "complete"
                break
            state["jobs"][key] = {
                "endpoint": endpoint,
                "symbol": symbol,
                "period": period,
                "requested_start_ms": requested_start,
                "requested_end_ms": requested_end,
                "next_start_ms": cursor,
                "pending_end_ms": pending_end,
                "pages": int(previous.get("pages") or 0) + pages,
                "rows_written": int(previous.get("rows_written") or 0) + rows_written,
                "status": "running",
                "updated_at": fetched_at.isoformat(),
            }
            self._save_state(state)
            if pending_end is not None or len(rows) < max(1, min(limit, 1000 if endpoint == "funding" else 500)):
                status = "complete"
                break
        state["jobs"][key] = {
            "endpoint": endpoint,
            "symbol": symbol,
            "period": period,
            "requested_start_ms": requested_start,
            "requested_end_ms": requested_end,
            "next_start_ms": cursor,
            "pending_end_ms": None,
            "pages": int(previous.get("pages") or 0) + pages,
            "rows_written": int(previous.get("rows_written") or 0) + rows_written,
            "status": status,
            "error": error,
            "updated_at": fetched_at.isoformat(),
        }
        return status, rows_written, error

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
