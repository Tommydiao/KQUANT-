from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, datetime

from kquant_crypto.binance_archive import BinanceArchiveBackfill, parse_archive_zip


def archive_bytes(row: list[object]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        text = io.StringIO()
        csv.writer(text).writerow(row)
        archive.writestr("BTCUSDT-1h-2026-01.csv", text.getvalue())
    return output.getvalue()


def test_archive_parser_normalizes_microsecond_timestamps():
    payload = archive_bytes([
        1767225600000000, "100", "110", "90", "105", "12",
        1767229199999000, "1260", 20, "7", "735", "0",
    ])
    events = parse_archive_zip(
        payload,
        symbol="BTCUSDT",
        interval="1h",
        market_type="spot",
        fetched_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert len(events) == 1
    assert events[0].source_time == "2026-01-01T00:00:00+00:00"
    assert events[0].payload["source"] == "binance_public_archive_klines"
    assert events[0].payload["closed"] is True


def test_archive_urls_keep_spot_and_usdm_separate():
    spot = BinanceArchiveBackfill.archive_url("BTCUSDT", "1h", "2026-01", "spot")
    perpetual = BinanceArchiveBackfill.archive_url("BTCUSDT", "1h", "2026-01", "perpetual")
    assert "/data/spot/monthly/" in spot
    assert "/data/futures/um/monthly/" in perpetual
