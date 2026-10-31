from __future__ import annotations

from pathlib import Path
from typing import Any

from .data_coverage import corporate_event_context
from .early_trend import evaluate_early_trend
from .stock_signals import api_stock_candles, api_stock_realtime_snapshot
from .stock_universe import stock_universe_payload


def early_trend_snapshot(symbol: str, db_path: Path) -> dict[str, Any]:
    normalized = symbol.strip().upper()
    # Symbol classification is static application metadata. Keeping this lookup
    # read-only prevents the realtime supervisor and HTTP requests contending for
    # SQLite merely to decide whether an instrument is eligible.
    universe_rows = {str(item["symbol"]).upper(): item for item in stock_universe_payload("all").get("stocks", [])}
    metadata = universe_rows.get(normalized) or {}
    tags = {str(item).lower() for item in metadata.get("tags", [])}
    layer = str(metadata.get("layer") or metadata.get("primary_layer") or "")
    instrument_eligible = bool(metadata) and "leveraged" not in tags and "3x" not in tags and "2x" not in tags and "Leveraged" not in layer
    daily = api_stock_candles(normalized, "1y", "1d", "live", db_path)
    confirmation = api_stock_candles(normalized, "2y", "1h", "live", db_path)
    five_minute = api_stock_candles(normalized, "1d", "5m", "live", db_path)
    benchmarks = {
        benchmark: api_stock_candles(benchmark, "1y", "1d", "live", db_path).get("candles", [])
        for benchmark in ("SPY", "QQQ")
    }
    realtime = api_stock_realtime_snapshot(normalized, db_path)
    result = evaluate_early_trend(
        normalized,
        daily.get("candles", []),
        confirmation.get("candles", []),
        five_minute_candles=five_minute.get("candles", []),
        benchmark_candles=benchmarks,
        realtime_snapshot=realtime,
        event_context=corporate_event_context(db_path, normalized, daily.get("candle_time")),
        instrument_eligible=instrument_eligible,
        validation_ready=False,
    )
    result["data_status"] = {
        "daily": {"status": daily.get("provider_status"), "source": daily.get("source_type")},
        "confirmation": {"status": confirmation.get("provider_status"), "source": confirmation.get("source_type"), "timeframe": "1H"},
        "trigger_5m": {"status": five_minute.get("provider_status"), "source": five_minute.get("source_type")},
        "realtime_trust": realtime.get("trust"),
    }
    result["realtime_snapshot"] = realtime
    result["read_only_research"] = True
    result["order_submission_enabled"] = False
    return result
