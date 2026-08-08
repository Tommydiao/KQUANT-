from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .data_coverage import api_stock_data_coverage
from .stock_signals import LONG_BRIDGE_CANDLE_SOURCE, api_stock_candles, api_stock_universe


BACKFILL_VERSION = "longbridge_backfill_v1.0.0"
BACKFILL_TIMEFRAMES = (
    ("daily", "5y", "1d", 900),
    ("hourly", "2y", "1h", 220),
)


def run_longbridge_backfill(
    *,
    db_path: Path,
    outputs_dir: Path,
    universe: str = "all",
    symbols: list[str] | None = None,
    limit: int | None = None,
    pause_seconds: float = 0.2,
) -> dict[str, Any]:
    """Fill canonical candle coverage without treating a reference fallback as eligible data."""

    universe_payload = api_stock_universe(universe=universe, db_path=db_path)
    requested = {item.strip().upper() for item in (symbols or []) if item.strip()}
    stocks = [item for item in universe_payload.get("stocks", []) if not requested or item["symbol"] in requested]
    if limit:
        stocks = stocks[: max(1, int(limit))]
    started_at = datetime.now(UTC).isoformat()
    results: list[dict[str, Any]] = []
    for stock in stocks:
        timeframe_results = []
        for name, range_value, interval, minimum_bars in BACKFILL_TIMEFRAMES:
            payload = api_stock_candles(stock["symbol"], range_value, interval, "live", db_path)
            candle_count = len(payload.get("candles") or [])
            source = str(payload.get("source_type") or "unknown")
            eligible = bool(
                payload.get("provider_status") == "available"
                and source == LONG_BRIDGE_CANDLE_SOURCE
                and candle_count >= minimum_bars
            )
            timeframe_results.append({
                "name": name,
                "range": range_value,
                "interval": interval,
                "minimum_bars": minimum_bars,
                "candle_count": candle_count,
                "source": source,
                "provider_status": payload.get("provider_status"),
                "eligible": eligible,
                "errors": list(payload.get("provider_errors") or [])[:3],
            })
            if pause_seconds > 0:
                time.sleep(pause_seconds)
        results.append({
            "symbol": stock["symbol"],
            "eligible": all(item["eligible"] for item in timeframe_results),
            "timeframes": timeframe_results,
        })
    coverage = api_stock_data_coverage(db_path)
    report = {
        "version": BACKFILL_VERSION,
        "started_at": started_at,
        "completed_at": datetime.now(UTC).isoformat(),
        "universe": universe,
        "requested_symbol_count": len(stocks),
        "eligible_symbol_count": sum(1 for item in results if item["eligible"]),
        "results": results,
        "coverage": coverage,
        "reference_fallback_counts_as_eligible": False,
        "read_only_market_data": True,
    }
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "longbridge-backfill-latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report

