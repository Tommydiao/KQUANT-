from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .stock_store import connect


LONG_BRIDGE_SOURCE = "longbridge_candles"
LEGACY_SOURCES = {"live_yahoo_chart", "stale_yahoo_chart_cache", "yahoo_public_fallback", "yahoo_public"}
REQUIRED_INTERVALS = {"1d": 220, "1h": 20}


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = (value - result) * multiplier + result
    return result


def market_breadth_snapshot(db_path: Path) -> dict[str, Any]:
    """Calculate cached Longbridge breadth only; legacy candles never participate."""

    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT symbol, open_time, close
            FROM market_candles
            WHERE interval = '1d' AND primary_source = ? AND provider_status = 'available'
            ORDER BY symbol, open_time
            """,
            (LONG_BRIDGE_SOURCE,),
        ).fetchall()
    by_symbol: dict[str, list[float]] = {}
    for row in rows:
        by_symbol.setdefault(str(row["symbol"]), []).append(float(row["close"]))
    eligible = {symbol: closes for symbol, closes in by_symbol.items() if len(closes) >= 200}
    total = len(eligible)
    above = {20: 0, 50: 0, 200: 0}
    for closes in eligible.values():
        close = closes[-1]
        for period in above:
            average = _ema(closes, period)
            if average is not None and close > average:
                above[period] += 1
    participation = {f"above_ema{period}_pct": round(count / total * 100, 2) if total else 0.0 for period, count in above.items()}
    return {
        "status": "available" if total >= 100 else "limited",
        "source": LONG_BRIDGE_SOURCE,
        "eligible_symbols": total,
        "participation": participation,
        "participation_score": round(sum(participation.values()) / 3, 2) if total else None,
        "note": "Cached Longbridge daily candles only; this is not a complete 296-symbol breadth series until coverage is expanded.",
    }


def corporate_event_context(db_path: Path, symbol: str, as_of: str | None = None) -> dict[str, Any]:
    """Expose detected corporate actions while keeping missing earnings/dividends explicit."""

    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT effective_time, action_type, price_ratio, source, status, details_json
            FROM corporate_action_events
            WHERE symbol = ?
            ORDER BY effective_time DESC
            LIMIT 10
            """,
            (symbol,),
        ).fetchall()
    actions = [dict(row) for row in rows]
    return {
        "status": "detected_actions_only" if actions else "not_ingested",
        "as_of": as_of,
        "nearest_event": actions[0] if actions else None,
        "detected_actions": actions,
        "earnings_calendar_status": "not_ingested",
        "dividend_calendar_status": "not_ingested",
        "trade_eligible": False,
    }


def _age_seconds(value: str | None) -> int | None:
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
    return max(0, int((datetime.now(UTC) - stamp).total_seconds()))


def _coverage_rows(db_path: Path) -> list[dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT u.symbol, u.name, u.sector, u.layer, 'unclassified' AS liquidity_tier,
                   c.interval, c.primary_source AS source, c.adjustment_mode,
                   c.provider_status, COUNT(*) AS candle_count,
                   MIN(c.open_time) AS first_time, MAX(c.open_time) AS last_time,
                   MAX(c.fetched_at) AS fetched_at
            FROM stock_universe u
            LEFT JOIN market_candles c ON c.symbol = u.symbol
            WHERE u.active=1
            GROUP BY u.symbol, c.interval, c.primary_source, c.adjustment_mode, c.provider_status
            ORDER BY u.symbol, c.interval, c.primary_source
            """
        ).fetchall()
    return [dict(row) for row in rows]


def api_stock_data_coverage(db_path: Path) -> dict[str, Any]:
    """Return a source-aware, audit-friendly coverage matrix without fetching data."""

    rows = _coverage_rows(db_path)
    by_symbol: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row["symbol"])
        item = by_symbol.setdefault(
            symbol,
            {
                "symbol": symbol,
                "name": row["name"],
                "sector": row["sector"],
                "layer": row["layer"],
                "intervals": {},
                "event_data_status": "not_ingested",
            },
        )
        interval = row.get("interval")
        if not interval:
            continue
        current = item["intervals"].get(interval)
        candidate = {
            "source": row.get("source") or "missing",
            "adjustment_mode": row.get("adjustment_mode") or "unknown",
            "provider_status": row.get("provider_status") or "missing",
            "candle_count": int(row.get("candle_count") or 0),
            "first_time": row.get("first_time"),
            "last_time": row.get("last_time"),
            "fetched_at": row.get("fetched_at"),
            "age_seconds": _age_seconds(row.get("fetched_at")),
        }
        if current is None or (candidate["source"] == LONG_BRIDGE_SOURCE and current["source"] != LONG_BRIDGE_SOURCE):
            item["intervals"][interval] = candidate
    for item in by_symbol.values():
        for interval, minimum in REQUIRED_INTERVALS.items():
            observed = item["intervals"].get(interval)
            eligible = bool(
                observed
                and observed["source"] == LONG_BRIDGE_SOURCE
                and observed["provider_status"] == "available"
                and observed["candle_count"] >= minimum
            )
            item["intervals"].setdefault(interval, {
                "source": "missing", "adjustment_mode": "unknown", "provider_status": "missing",
                "candle_count": 0, "first_time": None, "last_time": None, "fetched_at": None, "age_seconds": None,
            })
            item["intervals"][interval]["eligible_for_canonical_validation"] = eligible
        item["eligible_for_canonical_validation"] = all(
            item["intervals"][interval]["eligible_for_canonical_validation"] for interval in REQUIRED_INTERVALS
        )
    total = len(by_symbol)
    interval_summary: dict[str, dict[str, Any]] = {}
    for interval, minimum in REQUIRED_INTERVALS.items():
        eligible = [item for item in by_symbol.values() if item["intervals"][interval]["eligible_for_canonical_validation"]]
        interval_summary[interval] = {
            "required_candles": minimum,
            "longbridge_eligible_symbols": len(eligible),
            "coverage_pct": round(len(eligible) / total * 100, 2) if total else 0.0,
            "target_pct": 90.0,
            "target_met": len(eligible) / total >= 0.9 if total else False,
        }
    legacy_rows = [row for row in rows if str(row.get("source") or "") in LEGACY_SOURCES]
    return {
        "product": "KQUANT US Stock Signal Terminal",
        "as_of": datetime.now(UTC).isoformat(),
        "primary_provider": "longbridge",
        "universe_symbols": total,
        "required_intervals": REQUIRED_INTERVALS,
        "interval_summary": interval_summary,
        "canonical_validation_eligible_symbols": sum(
            1 for item in by_symbol.values() if item["eligible_for_canonical_validation"]
        ),
        "legacy_reference_observations": len(legacy_rows),
        "event_calendar": {"status": "not_ingested", "trade_eligible": False},
        "market_breadth": market_breadth_snapshot(db_path),
        "symbols": sorted(by_symbol.values(), key=lambda item: item["symbol"]),
        "read_only_research": True,
    }
