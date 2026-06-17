from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


BASE_URL = "https://data.binance.vision/data/futures/um/daily/klines"
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT")
DEFAULT_INTERVAL = "15m"


def refresh_archives(
    *,
    db_path: Path,
    symbols: Iterable[str],
    interval: str,
    date: str,
    timeout: float = 30.0,
) -> dict[str, Any]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with sqlite3.connect(db_path, timeout=10) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        ensure_schema(connection)
        for symbol in symbols:
            rows = fetch_archive(symbol=symbol, interval=interval, date=date, timeout=timeout)
            inserted = insert_klines(connection, rows)
            first_open = rows[0][2] if rows else None
            last_open = rows[-1][2] if rows else None
            results.append(
                {
                    "symbol": symbol,
                    "date": date,
                    "rows": len(rows),
                    "inserted": inserted,
                    "start_time": iso_from_millis(first_open) if first_open is not None else None,
                    "end_time": iso_from_millis(last_open) if last_open is not None else None,
                    "source": archive_url(symbol=symbol, interval=interval, date=date),
                }
            )
    return {"date": date, "interval": interval, "db_path": str(db_path), "results": results}


def fetch_archive(*, symbol: str, interval: str, date: str, timeout: float) -> list[tuple[Any, ...]]:
    url = archive_url(symbol=symbol, interval=interval, date=date)
    request = urllib.request.Request(url, headers={"User-Agent": "kquant-archive-refresh/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise RuntimeError(f"Failed to fetch archive {url}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to fetch archive {url}: {exc}") from exc
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        csv_names = [name for name in archive.namelist() if name.endswith(".csv")]
        if not csv_names:
            return []
        with archive.open(csv_names[0]) as handle:
            text = io.TextIOWrapper(handle, encoding="utf-8", newline="")
            reader = csv.DictReader(text)
            return [parse_row(symbol, interval, row) for row in reader]


def archive_url(*, symbol: str, interval: str, date: str) -> str:
    return f"{BASE_URL}/{symbol}/{interval}/{symbol}-{interval}-{date}.zip"


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


def parse_row(symbol: str, interval: str, row: dict[str, str]) -> tuple[Any, ...]:
    open_time = int(row["open_time"])
    return (
        symbol,
        interval,
        open_time,
        iso_from_millis(open_time),
        int(row["close_time"]),
        float(row["open"]),
        float(row["high"]),
        float(row["low"]),
        float(row["close"]),
        float(row["volume"]),
        float(row["quote_volume"]),
        int(row["count"]),
        datetime.now(timezone.utc).isoformat(),
    )


def insert_klines(connection: sqlite3.Connection, rows: list[tuple[Any, ...]]) -> int:
    before = connection.total_changes
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
    return connection.total_changes - before


def iso_from_millis(value: Optional[int]) -> Optional[str]:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def default_archive_date() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m btc_eth_15m.data_vision_refresh")
    parser.add_argument("--db-path", default="work/market.sqlite3")
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--interval", default=DEFAULT_INTERVAL)
    parser.add_argument("--date", default=default_archive_date())
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    payload = refresh_archives(
        db_path=Path(args.db_path),
        symbols=args.symbols or list(DEFAULT_SYMBOLS),
        interval=args.interval,
        date=args.date,
        timeout=args.timeout,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
