from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kquant_crypto.binance_history import (
    BINANCE_FUTURES_KLINES_URL,
    BINANCE_SPOT_KLINES_URL,
    BinanceKlineBackfill,
    BinancePublicKlineClient,
)
from kquant_crypto.config import load_settings
from kquant_crypto.parquet_store import ParquetMarketStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill closed Binance Spot or USD-M perpetual klines using public REST.")
    parser.add_argument("--symbol", action="append", dest="symbols", required=True, help="Symbol such as BTCUSDT; repeat for multiple symbols.")
    parser.add_argument("--interval", default="1m", choices=["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"])
    parser.add_argument("--start", required=True, help="UTC ISO timestamp or Unix milliseconds.")
    parser.add_argument("--end", help="UTC ISO timestamp or Unix milliseconds; defaults to the last closed bar.")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--root", help="Data root; defaults to configured data directory.")
    parser.add_argument("--market-type", choices=["spot", "perpetual"], default="spot")
    args = parser.parse_args()

    settings = load_settings()
    root = settings.data_dir if not args.root else settings.root_dir / args.root
    base_url = BINANCE_SPOT_KLINES_URL if args.market_type == "spot" else BINANCE_FUTURES_KLINES_URL
    backfill = BinanceKlineBackfill(
        ParquetMarketStore(root),
        BinancePublicKlineClient(base_url=base_url),
        market_type=args.market_type,
    )
    reports = backfill.run(args.symbols, interval=args.interval, start_at=args.start, end_at=args.end, limit=args.limit, max_pages=args.max_pages)
    print(json.dumps({
        "status": "ok",
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only_market_data": True,
        "order_submission": False,
        "market_type": args.market_type,
        "reports": [report.as_dict() for report in reports],
    }, ensure_ascii=True, indent=2))
    return 0 if all(report.status in {"complete", "paused", "empty"} for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
