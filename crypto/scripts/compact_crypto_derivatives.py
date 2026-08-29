from __future__ import annotations

import argparse
import json

from kquant_crypto.config import load_settings
from kquant_crypto.parquet_store import ParquetMarketStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Compact public Funding/OI events for historical replay.")
    parser.add_argument("--venue", default="binance")
    parser.add_argument("--market-type", default="perpetual")
    parser.add_argument("--symbol", action="append", dest="symbols")
    args = parser.parse_args()

    settings = load_settings()
    result = ParquetMarketStore(settings.data_dir).compact_derivative_snapshots(
        venue=args.venue,
        market_type=args.market_type,
        symbols=args.symbols,
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result.get("status") == "available" else 1


if __name__ == "__main__":
    raise SystemExit(main())
