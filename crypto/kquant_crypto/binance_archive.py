from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Callable, Iterable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .binance_history import kline_event
from .binance_derivatives_history import funding_event
from .market_models import NormalizedMarketEvent
from .parquet_store import ParquetMarketStore


ARCHIVE_BASE_URL = "https://data.binance.vision/data"


def _download(url: str, timeout: float = 45.0) -> bytes:
    request = Request(url, headers={"User-Agent": "KQUANT-CRYPTO/0.4", "Accept": "*/*"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public archive host
        return response.read()


def _timestamp_milliseconds(value: str) -> int:
    number = int(value)
    return number // 1000 if number > 100_000_000_000_000 else number


def parse_archive_zip(
    payload: bytes,
    *,
    symbol: str,
    interval: str,
    market_type: str,
    fetched_at: datetime,
) -> list[NormalizedMarketEvent]:
    events: list[NormalizedMarketEvent] = []
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError("archive_must_contain_one_csv")
        with archive.open(csv_names[0]) as raw:
            rows = csv.reader(io.TextIOWrapper(raw, encoding="utf-8"))
            for row in rows:
                if not row or not str(row[0]).isdigit():
                    continue
                normalized = list(row)
                normalized[0] = _timestamp_milliseconds(normalized[0])
                normalized[6] = _timestamp_milliseconds(normalized[6])
                event = kline_event(
                    symbol,
                    normalized,
                    interval=interval,
                    fetched_at=fetched_at,
                    market_type=market_type,
                    source="binance_public_archive_klines",
                )
                if event is not None:
                    events.append(event)
    return events


def _months(start: date, end: date) -> list[str]:
    cursor = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    values: list[str] = []
    while cursor <= last:
        values.append(cursor.strftime("%Y-%m"))
        cursor = date(cursor.year + (1 if cursor.month == 12 else 0), 1 if cursor.month == 12 else cursor.month + 1, 1)
    return values


@dataclass(frozen=True)
class ArchiveResult:
    symbol: str
    market_type: str
    interval: str
    month: str
    status: str
    rows: int
    sha256: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


class BinanceArchiveBackfill:
    """Checksum-verified monthly K-line import from Binance's public archive."""

    def __init__(
        self,
        store: ParquetMarketStore,
        *,
        download: Callable[[str], bytes] = _download,
        workers: int = 6,
    ):
        self.store = store
        self.download = download
        self.workers = max(1, min(int(workers), 12))

    @staticmethod
    def archive_url(symbol: str, interval: str, month: str, market_type: str) -> str:
        prefix = "spot" if market_type == "spot" else "futures/um"
        name = f"{symbol}-{interval}-{month}.zip"
        return f"{ARCHIVE_BASE_URL}/{prefix}/monthly/klines/{symbol}/{interval}/{name}"

    def _fetch_month(self, symbol: str, interval: str, month: str, market_type: str) -> tuple[ArchiveResult, list[NormalizedMarketEvent]]:
        url = self.archive_url(symbol, interval, month, market_type)
        try:
            payload = self.download(url)
            checksum_text = self.download(f"{url}.CHECKSUM").decode("ascii", errors="replace").strip()
            expected = checksum_text.split()[0].lower() if checksum_text else ""
            actual = hashlib.sha256(payload).hexdigest()
            if not expected or actual != expected:
                return ArchiveResult(symbol, market_type, interval, month, "checksum_failed", 0, actual, "checksum_mismatch"), []
            fetched_at = datetime.now(UTC)
            events = parse_archive_zip(
                payload,
                symbol=symbol,
                interval=interval,
                market_type=market_type,
                fetched_at=fetched_at,
            )
            return ArchiveResult(symbol, market_type, interval, month, "complete", len(events), actual), events
        except HTTPError as exc:
            status = "not_available" if exc.code == 404 else "error"
            return ArchiveResult(symbol, market_type, interval, month, status, 0, error=f"HTTP_{exc.code}"), []
        except Exception as exc:
            return ArchiveResult(symbol, market_type, interval, month, "error", 0, error=type(exc).__name__), []

    def run(
        self,
        symbols: Iterable[str],
        *,
        interval: str,
        start: date,
        end: date,
        market_type: str,
    ) -> list[ArchiveResult]:
        if market_type not in {"spot", "perpetual"}:
            raise ValueError("market_type_must_be_spot_or_perpetual")
        jobs = [(str(symbol).upper(), interval, month, market_type) for symbol in symbols for month in _months(start, end)]
        results: list[ArchiveResult] = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self._fetch_month, *job): job for job in jobs}
            for future in as_completed(futures):
                result, events = future.result()
                if events:
                    self.store.write_events(events)
                results.append(result)
        return sorted(results, key=lambda item: (item.symbol, item.month))


class BinanceFundingArchiveBackfill:
    """Checksum-verified USD-M funding history import."""

    def __init__(self, store: ParquetMarketStore, *, download: Callable[[str], bytes] = _download, workers: int = 6):
        self.store = store
        self.download = download
        self.workers = max(1, min(int(workers), 12))

    @staticmethod
    def archive_url(symbol: str, month: str) -> str:
        name = f"{symbol}-fundingRate-{month}.zip"
        return f"{ARCHIVE_BASE_URL}/futures/um/monthly/fundingRate/{symbol}/{name}"

    def _fetch_month(self, symbol: str, month: str) -> tuple[ArchiveResult, list[NormalizedMarketEvent]]:
        url = self.archive_url(symbol, month)
        try:
            payload = self.download(url)
            checksum_text = self.download(f"{url}.CHECKSUM").decode("ascii", errors="replace").strip()
            expected = checksum_text.split()[0].lower() if checksum_text else ""
            actual = hashlib.sha256(payload).hexdigest()
            if not expected or actual != expected:
                return ArchiveResult(symbol, "perpetual", "funding", month, "checksum_failed", 0, actual, "checksum_mismatch"), []
            fetched_at = datetime.now(UTC)
            events: list[NormalizedMarketEvent] = []
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
                if len(csv_names) != 1:
                    raise ValueError("archive_must_contain_one_csv")
                with archive.open(csv_names[0]) as raw:
                    for row in csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8")):
                        event = funding_event(
                            symbol,
                            {
                                "fundingTime": _timestamp_milliseconds(str(row.get("calc_time") or "0")),
                                "fundingRate": row.get("last_funding_rate"),
                                "rateType": "Regular",
                            },
                            fetched_at=fetched_at,
                            source="binance_public_archive_funding_rate",
                        )
                        if event is not None:
                            events.append(event)
            return ArchiveResult(symbol, "perpetual", "funding", month, "complete", len(events), actual), events
        except HTTPError as exc:
            status = "not_available" if exc.code == 404 else "error"
            return ArchiveResult(symbol, "perpetual", "funding", month, status, 0, error=f"HTTP_{exc.code}"), []
        except Exception as exc:
            return ArchiveResult(symbol, "perpetual", "funding", month, "error", 0, error=type(exc).__name__), []

    def run(self, symbols: Iterable[str], *, start: date, end: date) -> list[ArchiveResult]:
        jobs = [(str(symbol).upper(), month) for symbol in symbols for month in _months(start, end)]
        results: list[ArchiveResult] = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(self._fetch_month, *job): job for job in jobs}
            for future in as_completed(futures):
                result, events = future.result()
                if events:
                    self.store.write_events(events)
                results.append(result)
        return sorted(results, key=lambda item: (item.symbol, item.month))
