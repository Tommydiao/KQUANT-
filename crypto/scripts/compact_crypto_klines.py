from __future__ import annotations

import argparse
import json
from pathlib import Path

from kquant_crypto.config import load_settings
from kquant_crypto.parquet_store import ParquetMarketStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the read-optimized closed-K-line snapshot for validation.")
    parser.add_argument("--interval", default="1m")
    parser.add_argument("--venue", default="binance")
    parser.add_argument("--market-type", default="spot")
    parser.add_argument("--symbol", action="append", dest="symbols")
    args = parser.parse_args()
    settings = load_settings(Path(__file__).resolve().parents[1])
    result = ParquetMarketStore(settings.data_dir).compact_closed_klines(
        interval=args.interval,
        venue=args.venue or None,
        market_type=args.market_type or None,
        symbols=args.symbols,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "available" else 1


if __name__ == "__main__":
    raise SystemExit(main())
