from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from kquant_crypto.binance_history import BinanceKlineBackfill, BinancePublicKlineClient
from kquant_crypto.config import load_settings
from kquant_crypto.parquet_store import ParquetMarketStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill closed Binance spot klines using the public REST API.")
    parser.add_argument("--symbol", action="append", dest="symbols", required=True, help="Symbol such as BTCUSDT; repeat for multiple symbols.")
    parser.add_argument("--interval", default="1m", choices=["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"])
    parser.add_argument("--start", required=True, help="UTC ISO timestamp or Unix milliseconds.")
    parser.add_argument("--end", help="UTC ISO timestamp or Unix milliseconds; defaults to the last closed bar.")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--root", help="Data root; defaults to configured data directory.")
    args = parser.parse_args()

    settings = load_settings()
    root = settings.data_dir if not args.root else settings.root_dir / args.root
    backfill = BinanceKlineBackfill(ParquetMarketStore(root), BinancePublicKlineClient())
    reports = backfill.run(args.symbols, interval=args.interval, start_at=args.start, end_at=args.end, limit=args.limit, max_pages=args.max_pages)
    print(json.dumps({
        "status": "ok",
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only_market_data": True,
        "order_submission": False,
        "reports": [report.as_dict() for report in reports],
    }, ensure_ascii=True, indent=2))
    return 0 if all(report.status in {"complete", "paused", "empty"} for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
