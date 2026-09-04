from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from kquant_crypto.binance_archive import BinanceArchiveBackfill, BinanceFundingArchiveBackfill
from kquant_crypto.binance_derivatives_history import BinanceDerivativeBackfill, BinancePublicDerivativeClient
from kquant_crypto.config import load_settings
from kquant_crypto.external_evidence import save_evidence_snapshot
from kquant_crypto.parquet_store import ParquetMarketStore
from kquant_crypto.public_evidence import fetch_binance_derivatives_evidence
from kquant_crypto.universe_catalog import configured_instruments


INTERVALS = ("1m", "5m", "1h", "4h", "1d")


def _month(value: str) -> date:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return date(parsed.year, parsed.month, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill versioned candidate assets from their actual Binance market start.")
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--through-month", default=datetime.now(UTC).strftime("%Y-%m"))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--execute", action="store_true", help="Download and persist archives; otherwise print the immutable job plan.")
    args = parser.parse_args()
    settings = load_settings()
    selected = [item for item in configured_instruments(settings.root_dir) if item.research_status == "candidate"]
    if args.symbols:
        wanted = {item.upper() for item in args.symbols}
        selected = [item for item in selected if item.symbol in wanted]
    end = datetime.strptime(args.through_month, "%Y-%m").date()
    jobs = [
        {
            "symbol": item.symbol,
            "market_type": item.market_type,
            "listed_since": item.listed_since,
            "start_month": _month(str(item.listed_since)).strftime("%Y-%m") if item.listed_since else None,
            "end_month": end.strftime("%Y-%m"),
            "intervals": list(INTERVALS),
            "funding": item.market_type == "perpetual",
            "derivative_evidence": ["funding_rate", "open_interest", "mark_price", "index_price", "basis"] if item.market_type == "perpetual" else [],
        }
        for item in selected
    ]
    if not args.execute:
        print(json.dumps({"status": "planned", "jobs": jobs, "pre_listing_data_forbidden": True}, indent=2))
        return 0

    store = ParquetMarketStore(settings.data_dir)
    backfill = BinanceArchiveBackfill(store, workers=args.workers)
    funding = BinanceFundingArchiveBackfill(store, workers=args.workers)
    results = []
    for item in selected:
        if not item.listed_since:
            results.append({"symbol": item.symbol, "status": "blocked", "reason": "listing_time_missing"})
            continue
        start = _month(item.listed_since)
        for interval in INTERVALS:
            values = backfill.run([item.symbol], interval=interval, start=start, end=end, market_type=item.market_type)
            results.extend(value.as_dict() for value in values)
        if item.market_type == "perpetual":
            results.extend(value.as_dict() for value in funding.run([item.symbol], start=start, end=end))
            derivative = BinanceDerivativeBackfill(store, BinancePublicDerivativeClient())
            results.extend(
                {"symbol": value.symbol, "market_type": "perpetual", "interval": value.period, "month": "rest_history", "status": "complete" if not value.error else "error", "rows": value.funding_rows + value.open_interest_rows, "error": value.error}
                for value in derivative.run([item.symbol], start_at=item.listed_since, period="1h")
            )
            current = fetch_binance_derivatives_evidence(asset_id=item.asset_id, symbol=item.symbol)
            saved = save_evidence_snapshot(settings.db_path, current.snapshot)
            required = {"funding_rate", "open_interest", "mark_price", "index_price", "basis"}
            missing = sorted(required - set(saved["values"]))
            results.append({
                "symbol": item.symbol,
                "market_type": "perpetual",
                "interval": "current_derivatives_snapshot",
                "month": end.strftime("%Y-%m"),
                "status": "complete" if not missing else "required_evidence_missing",
                "rows": 1,
                "missing_fields": missing,
                "evidence_id": saved["evidence_id"],
            })
    failed = [item for item in results if item.get("status") not in {"complete", "not_available"}]
    print(json.dumps({
        "status": "ok" if not failed else "partial",
        "source": "binance_public_archive",
        "pre_listing_data_forbidden": True,
        "rows_written": sum(int(item.get("rows") or 0) for item in results),
        "results": results,
    }, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
