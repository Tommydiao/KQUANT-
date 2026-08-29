from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from kquant_crypto.binance_derivatives_history import BinanceDerivativeBackfill, BinancePublicDerivativeClient
from kquant_crypto.config import load_settings
from kquant_crypto.parquet_store import ParquetMarketStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill public Binance Funding Rate and Open Interest history.")
    parser.add_argument("--symbol", action="append", dest="symbols", required=True)
    parser.add_argument("--start", required=True, help="UTC ISO timestamp or Unix milliseconds.")
    parser.add_argument("--end", help="UTC ISO timestamp or Unix milliseconds.")
    parser.add_argument("--period", default="1h", choices=["5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"])
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--state-path", help="Optional JSON checkpoint path for an isolated backfill job.")
    args = parser.parse_args()

    settings = load_settings()
    result = BinanceDerivativeBackfill(
        ParquetMarketStore(settings.data_dir),
        BinancePublicDerivativeClient(),
        state_path=Path(args.state_path) if args.state_path else None,
    ).run(
        args.symbols,
        start_at=args.start,
        end_at=args.end,
        period=args.period,
        limit=args.limit,
        max_pages=args.max_pages,
    )
    reports = [item.as_dict() for item in result]
    print(json.dumps({
        "status": "ok" if all(item["error"] is None for item in reports) else "partial",
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only_market_data": True,
        "account_access": False,
        "wallet_access": False,
        "order_submission": False,
        "reports": reports,
    }, ensure_ascii=True, indent=2))
    return 0 if all(item["error"] is None for item in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
