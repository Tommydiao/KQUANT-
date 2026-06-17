from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from requests import RequestException

from btc_eth_15m.config import AppConfig

BINANCE_FAPI_BASE = "https://fapi.binance.com"
KLINES_PATH = "/fapi/v1/klines"
UTC = timezone.utc


@dataclass(frozen=True)
class FetchResult:
    symbol: str
    rows: int
    start_time: str | None
    end_time: str | None


def interval_to_millis(interval: str) -> int:
    unit = interval[-1]
    value = int(interval[:-1])
    factors = {
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
    }
    if unit not in factors:
        raise ValueError(f"Unsupported interval: {interval}")
    return value * factors[unit]


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def utc_millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def iso_from_millis(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=5000")
    ensure_schema(connection)
    return connection


def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS klines (
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            open_time INTEGER NOT NULL,
            open_time_iso TEXT NOT NULL,
            close_time INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            quote_volume REAL NOT NULL,
            trades INTEGER NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (symbol, interval, open_time)
        )
        """
    )
    connection.commit()


def latest_open_time(connection: sqlite3.Connection, symbol: str, interval: str) -> int | None:
    row = connection.execute(
        "SELECT MAX(open_time) FROM klines WHERE symbol = ? AND interval = ?",
        (symbol, interval),
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def fetch_all(config: AppConfig) -> list[FetchResult]:
    results = []
    with connect(config.db_path) as connection:
        for symbol in config.symbols:
            results.append(fetch_symbol(connection, config, symbol))
    return results


def fetch_recent_all(config: AppConfig, lookback_bars: int = 600) -> list[FetchResult]:
    results = []
    with connect(config.db_path) as connection:
        for symbol in config.symbols:
            results.append(fetch_recent_symbol(connection, config, symbol, lookback_bars=lookback_bars))
    return results


def fetch_symbol(connection: sqlite3.Connection, config: AppConfig, symbol: str) -> FetchResult:
    interval_ms = interval_to_millis(config.interval)
    existing_latest = latest_open_time(connection, symbol, config.interval)
    start_ms = utc_millis(parse_utc(config.start))
    if existing_latest is not None:
        start_ms = max(start_ms, existing_latest + interval_ms)

    now_ms = utc_millis(datetime.now(tz=UTC))
    # Avoid caching the currently forming candle.
    end_ms = now_ms - interval_ms
    rows_inserted = 0
    first_open = None
    last_open = None

    while start_ms <= end_ms:
        payload = _request_klines(symbol, config.interval, start_ms=start_ms, end_ms=end_ms, limit=1500)
        if not payload:
            break
        rows = [_parse_kline(symbol, config.interval, item) for item in payload]
        insert_klines(connection, rows)
        rows_inserted += len(rows)
        first_open = rows[0][2] if first_open is None else first_open
        last_open = rows[-1][2]
        next_start = rows[-1][2] + interval_ms
        if next_start <= start_ms:
            break
        start_ms = next_start
        time.sleep(0.12)

    return FetchResult(
        symbol=symbol,
        rows=rows_inserted,
        start_time=iso_from_millis(first_open) if first_open is not None else None,
        end_time=iso_from_millis(last_open) if last_open is not None else None,
    )


def fetch_recent_symbol(
    connection: sqlite3.Connection,
    config: AppConfig,
    symbol: str,
    *,
    lookback_bars: int = 600,
) -> FetchResult:
    interval_ms = interval_to_millis(config.interval)
    existing_latest = latest_open_time(connection, symbol, config.interval)
    now_ms = utc_millis(datetime.now(tz=UTC))
    end_ms = now_ms - interval_ms
    lookback_start = end_ms - max(lookback_bars - 1, 0) * interval_ms
    start_ms = lookback_start if existing_latest is None else max(existing_latest + interval_ms, lookback_start)

    rows_inserted = 0
    first_open = None
    last_open = None
    while start_ms <= end_ms:
        payload = _request_klines(symbol, config.interval, start_ms=start_ms, end_ms=end_ms, limit=min(1500, lookback_bars))
        if not payload:
            break
        rows = [_parse_kline(symbol, config.interval, item) for item in payload]
        insert_klines(connection, rows)
        rows_inserted += len(rows)
        first_open = rows[0][2] if first_open is None else first_open
        last_open = rows[-1][2]
        next_start = rows[-1][2] + interval_ms
        if next_start <= start_ms:
            break
        start_ms = next_start
        time.sleep(0.12)

    return FetchResult(
        symbol=symbol,
        rows=rows_inserted,
        start_time=iso_from_millis(first_open) if first_open is not None else None,
        end_time=iso_from_millis(last_open) if last_open is not None else None,
    )


def _request_klines(symbol: str, interval: str, start_ms: int, end_ms: int, limit: int) -> list[list]:
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            response = requests.get(
                f"{BINANCE_FAPI_BASE}{KLINES_PATH}",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms,
                    "limit": limit,
                },
                timeout=20,
            )
            response.raise_for_status()
            return response.json()
        except RequestException as exc:
            last_error = exc
            time.sleep(min(2**attempt, 10))
    raise RuntimeError(f"Failed to fetch {symbol} {interval} klines after retries: {last_error}") from last_error


def _parse_kline(symbol: str, interval: str, item: list) -> tuple:
    open_time = int(item[0])
    close_time = int(item[6])
    return (
        symbol,
        interval,
        open_time,
        iso_from_millis(open_time),
        close_time,
        float(item[1]),
        float(item[2]),
        float(item[3]),
        float(item[4]),
        float(item[5]),
        float(item[7]),
        int(item[8]),
        datetime.now(tz=UTC).isoformat(),
    )


def insert_klines(connection: sqlite3.Connection, rows: list[tuple]) -> None:
    connection.executemany(
        """
        INSERT OR IGNORE INTO klines (
            symbol, interval, open_time, open_time_iso, close_time,
            open, high, low, close, volume, quote_volume, trades, fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    connection.commit()


def load_klines(db_path: Path, symbol: str, interval: str) -> pd.DataFrame:
    import pandas as pd

    with connect(db_path) as connection:
        frame = pd.read_sql_query(
            """
            SELECT symbol, interval, open_time, open_time_iso, close_time,
                   open, high, low, close, volume, quote_volume, trades
            FROM klines
            WHERE symbol = ? AND interval = ?
            ORDER BY open_time ASC
            """,
            connection,
            params=(symbol, interval),
        )
    if frame.empty:
        return frame
    frame["open_datetime"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    return frame


def load_recent_klines(db_path: Path, symbol: str, interval: str, limit: int) -> pd.DataFrame:
    import pandas as pd

    with connect(db_path) as connection:
        frame = pd.read_sql_query(
            """
            SELECT symbol, interval, open_time, open_time_iso, close_time,
                   open, high, low, close, volume, quote_volume, trades
            FROM (
                SELECT symbol, interval, open_time, open_time_iso, close_time,
                       open, high, low, close, volume, quote_volume, trades
                FROM klines
                WHERE symbol = ? AND interval = ?
                ORDER BY open_time DESC
                LIMIT ?
            )
            ORDER BY open_time ASC
            """,
            connection,
            params=(symbol, interval, limit),
        )
    if frame.empty:
        return frame
    frame["open_datetime"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    return frame


def market_freshness(config: AppConfig) -> list[dict]:
    rows = []
    now = datetime.now(tz=UTC)
    with connect(config.db_path) as connection:
        for symbol in config.symbols:
            row = connection.execute(
                """
                SELECT COUNT(*), MAX(open_time), MAX(open_time_iso), MAX(fetched_at)
                FROM klines
                WHERE symbol = ? AND interval = ?
                """,
                (symbol, config.interval),
            ).fetchone()
            count = int(row[0] or 0)
            latest_open = int(row[1]) if row and row[1] is not None else None
            latest_iso = str(row[2]) if row and row[2] is not None else None
            fetched_at = str(row[3]) if row and row[3] is not None else None
            age_seconds = None
            is_fresh = False
            if latest_open is not None:
                latest_dt = datetime.fromtimestamp(latest_open / 1000, tz=UTC)
                age_seconds = max((now - latest_dt).total_seconds(), 0)
                is_fresh = age_seconds <= interval_to_millis(config.interval) / 1000 * 3
            rows.append(
                {
                    "symbol": symbol,
                    "rows": count,
                    "latest_open_time": latest_open,
                    "latest_open_time_iso": latest_iso,
                    "latest_fetched_at": fetched_at,
                    "age_seconds": age_seconds,
                    "is_fresh": is_fresh,
                }
            )
    return rows


def missing_bars(frame: pd.DataFrame, interval: str) -> int:
    if frame.empty or len(frame) == 1:
        return 0
    interval_ms = interval_to_millis(interval)
    diffs = frame["open_time"].diff().dropna()
    return int((diffs != interval_ms).sum())
