from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kquant_crypto.binance_archive import BinanceArchiveBackfill
from kquant_crypto.config import load_settings
from kquant_crypto.parquet_store import ParquetMarketStore


def _month(value: str) -> date:
    return datetime.strptime(value, "%Y-%m").date()


def main() -> int:
    parser = argparse.ArgumentParser(description="Import checksum-verified Binance monthly K-line archives.")
    parser.add_argument("--symbol", action="append", dest="symbols", required=True)
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--start-month", required=True, type=_month)
    parser.add_argument("--end-month", required=True, type=_month)
    parser.add_argument("--market-type", choices=["spot", "perpetual"], required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    settings = load_settings()
    results = BinanceArchiveBackfill(
        ParquetMarketStore(settings.data_dir), workers=args.workers,
    ).run(
        args.symbols,
        interval=args.interval,
        start=args.start_month,
        end=args.end_month,
        market_type=args.market_type,
    )
    complete = [item for item in results if item.status == "complete"]
    failed = [item for item in results if item.status not in {"complete", "not_available"}]
    print(json.dumps({
        "status": "ok" if not failed else "partial",
        "source": "binance_public_archive",
        "checksum_verified": True,
        "files_complete": len(complete),
        "rows_written": sum(item.rows for item in complete),
        "not_available": sum(item.status == "not_available" for item in results),
        "failed": [item.as_dict() for item in failed],
    }, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
