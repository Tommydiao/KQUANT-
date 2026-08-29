from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .stock_store import connect
from .universe_registry import ensure_current_universe_registry
from .market_data_quota import backfill_quota_status


LONG_BRIDGE_SOURCE = "longbridge_candles"
LEGACY_SOURCES = {"live_yahoo_chart", "stale_yahoo_chart_cache", "yahoo_public_fallback", "yahoo_public"}
MODEL_REQUIRED_INTERVALS = {"1d": 220, "1h": 20}
TRACKED_INTERVALS = {**MODEL_REQUIRED_INTERVALS, "1m": 60}
# Compatibility name used by pre-v2 callers. It deliberately excludes 1m,
# which is observed for operational trust but is not a modelling prerequisite.
REQUIRED_INTERVALS = MODEL_REQUIRED_INTERVALS
DATA_COVERAGE_CONTRACT_VERSION = "data_coverage_v2"


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


def _coverage_rows(db_path: Path, *, include_open_times: bool = True) -> list[dict[str, Any]]:
    """Read coverage aggregations without changing stored evidence.

    Full audits need every timestamp to calculate observed gaps. Operational
    summary views do not, so avoid collecting all timestamps for them.
    """

    open_times_select = "GROUP_CONCAT(c.open_time, '|') AS open_times" if include_open_times else "NULL AS open_times"
    with connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT u.symbol, u.name, u.sector, u.layer, 'unclassified' AS liquidity_tier,
                   c.interval, c.primary_source AS source, c.adjustment_mode,
                   c.provider_status, COUNT(*) AS candle_count,
                   MIN(c.open_time) AS first_time, MAX(c.open_time) AS last_time,
                   MAX(c.fetched_at) AS fetched_at,
                   {open_times_select}
            FROM stock_universe u
            LEFT JOIN market_candles c ON c.symbol = u.symbol
            WHERE u.active=1
            GROUP BY u.symbol, c.interval, c.primary_source, c.adjustment_mode, c.provider_status
            ORDER BY u.symbol, c.interval, c.primary_source
            """
        ).fetchall()
    return [dict(row) for row in rows]


def _gap_summary(open_times: str | None, interval: str) -> tuple[int, int | None]:
    """Report observed gaps; exchange closures remain visible rather than guessed away."""

    values: list[datetime] = []
    for raw in (open_times or "").split("|"):
        try:
            values.append(datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC))
        except ValueError:
            continue
    values.sort()
    if len(values) < 2:
        return 0, None
    expected = {"1m": 60, "1h": 3600, "1d": 86400}.get(interval)
    if expected is None:
        return 0, None
    gaps = [int((right - left).total_seconds()) for left, right in zip(values, values[1:])]
    significant = [gap for gap in gaps if gap > expected * 2]
    return len(significant), max(significant, default=None)


def _latest_materialized_summary(db_path: Path, *, current_registry_id: str) -> dict[str, Any] | None:
    """Read a previously recorded coverage snapshot for an operational summary.

    Coverage runs are explicit, immutable audit artifacts. They are a better
    source for the lightweight UI summary than rescanning every historical bar
    on every page load. A changed universe invalidates the shortcut so callers
    safely fall back to a fresh aggregation instead.
    """

    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT r.coverage_run_id, r.registry_id, r.contract_version, r.as_of_time,
                   r.summary_json, r.created_at, u.symbol_count
            FROM data_coverage_runs AS r
            LEFT JOIN universe_registry_versions AS u ON u.registry_id = r.registry_id
            ORDER BY r.created_at DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None or str(row["registry_id"]) != current_registry_id:
            return None
        summary_rows = conn.execute(
            """
            SELECT
              COUNT(DISTINCT CASE
                WHEN source IN ('live_yahoo_chart', 'stale_yahoo_chart_cache', 'yahoo_public_fallback', 'yahoo_public')
                THEN symbol || '|' || interval
              END) AS legacy_reference_observations
            FROM data_coverage_items
            WHERE coverage_run_id = ?
            """,
            (str(row["coverage_run_id"]),),
        ).fetchone()
        canonical_rows = conn.execute(
            """
            SELECT COUNT(*) AS eligible_symbols
            FROM (
              SELECT symbol
              FROM data_coverage_items
              WHERE coverage_run_id = ?
                AND interval IN ('1d', '1h')
                AND eligibility_status = 'eligible'
              GROUP BY symbol
              HAVING COUNT(DISTINCT interval) = 2
            )
            """,
            (str(row["coverage_run_id"]),),
        ).fetchone()
    try:
        interval_summary = json.loads(str(row["summary_json"]))
    except json.JSONDecodeError:
        return None
    universe_symbols = int(row["symbol_count"] or 0)
    return {
        "product": "KQUANT US Stock Signal Terminal",
        "as_of": str(row["as_of_time"]),
        "contract_version": str(row["contract_version"]),
        "universe_registry": {
            "registry_id": str(row["registry_id"]),
            "symbol_count": universe_symbols,
            "source": "materialized_coverage_run",
        },
        "primary_provider": "longbridge",
        "universe_symbols": universe_symbols,
        "required_intervals": MODEL_REQUIRED_INTERVALS,
        "tracked_intervals": TRACKED_INTERVALS,
        "interval_summary": interval_summary,
        "canonical_validation_eligible_symbols": int(canonical_rows["eligible_symbols"] or 0),
        "legacy_reference_observations": int(summary_rows["legacy_reference_observations"] or 0),
        "event_calendar": {"status": "not_ingested", "trade_eligible": False},
        "coverage_snapshot": {
            "status": "materialized",
            "coverage_run_id": str(row["coverage_run_id"]),
            "as_of_time": str(row["as_of_time"]),
            "created_at": str(row["created_at"]),
            "source": "data_coverage_runs",
            "current_registry_matches": True,
        },
        "symbol_details_included": False,
        "symbols": [],
        "read_only_research": True,
    }


def api_stock_data_coverage(
    db_path: Path,
    *,
    include_symbols: bool = True,
    prefer_materialized_summary: bool = False,
) -> dict[str, Any]:
    """Return a source-aware, audit-friendly coverage matrix without fetching data."""

    registry = ensure_current_universe_registry(db_path)
    if not include_symbols and prefer_materialized_summary:
        materialized = _latest_materialized_summary(db_path, current_registry_id=str(registry["registry_id"]))
        if materialized is not None:
            # Breadth is a separate all-history calculation, not a coverage
            # fact. Keep it off the operational coverage hot path rather than
            # delaying the page or presenting a stale value as current.
            materialized["market_breadth"] = {
                "status": "not_loaded_in_coverage_summary",
                "source": LONG_BRIDGE_SOURCE,
                "note": "Load a dedicated breadth snapshot before using breadth as model evidence.",
            }
            materialized["backfill_quota"] = backfill_quota_status(db_path=db_path)
            return materialized
    rows = _coverage_rows(db_path, include_open_times=include_symbols)
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
        gap_count, max_gap_seconds = _gap_summary(row.get("open_times"), str(interval)) if include_symbols else (None, None)
        candidate = {
            "source": row.get("source") or "missing",
            "adjustment_mode": row.get("adjustment_mode") or "unknown",
            "provider_status": row.get("provider_status") or "missing",
            "candle_count": int(row.get("candle_count") or 0),
            "first_time": row.get("first_time"),
            "last_time": row.get("last_time"),
            "fetched_at": row.get("fetched_at"),
            "age_seconds": _age_seconds(row.get("fetched_at")),
            "gap_count": gap_count,
            "max_gap_seconds": max_gap_seconds,
        }
        if current is None or (candidate["source"] == LONG_BRIDGE_SOURCE and current["source"] != LONG_BRIDGE_SOURCE):
            item["intervals"][interval] = candidate
    for item in by_symbol.values():
        for interval, minimum in TRACKED_INTERVALS.items():
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
                "gap_count": 0, "max_gap_seconds": None,
            })
            item["intervals"][interval]["eligible_for_canonical_validation"] = eligible if interval in MODEL_REQUIRED_INTERVALS else False
        item["eligible_for_canonical_validation"] = all(
            item["intervals"][interval]["eligible_for_canonical_validation"] for interval in MODEL_REQUIRED_INTERVALS
        )
    total = len(by_symbol)
    interval_summary: dict[str, dict[str, Any]] = {}
    for interval, minimum in TRACKED_INTERVALS.items():
        eligible = [item for item in by_symbol.values() if item["intervals"][interval]["source"] == LONG_BRIDGE_SOURCE and item["intervals"][interval]["provider_status"] == "available" and item["intervals"][interval]["candle_count"] >= minimum]
        interval_summary[interval] = {
            "required_candles": minimum,
            "longbridge_eligible_symbols": len(eligible),
            "coverage_pct": round(len(eligible) / total * 100, 2) if total else 0.0,
            "target_pct": 90.0,
            "target_met": len(eligible) / total >= 0.9 if total else False,
            "required_for_model": interval in MODEL_REQUIRED_INTERVALS,
        }
    legacy_rows = [row for row in rows if str(row.get("source") or "") in LEGACY_SOURCES]
    return {
        "product": "KQUANT US Stock Signal Terminal",
        "as_of": datetime.now(UTC).isoformat(),
        "contract_version": DATA_COVERAGE_CONTRACT_VERSION,
        "universe_registry": registry,
        "primary_provider": "longbridge",
        "universe_symbols": total,
        "required_intervals": MODEL_REQUIRED_INTERVALS,
        "tracked_intervals": TRACKED_INTERVALS,
        "interval_summary": interval_summary,
        "canonical_validation_eligible_symbols": sum(
            1 for item in by_symbol.values() if item["eligible_for_canonical_validation"]
        ),
        "legacy_reference_observations": len(legacy_rows),
        "event_calendar": {"status": "not_ingested", "trade_eligible": False},
        "market_breadth": market_breadth_snapshot(db_path),
        "backfill_quota": backfill_quota_status(db_path=db_path),
        "coverage_snapshot": {"status": "live_aggregation", "current_registry_matches": True},
        "symbol_details_included": include_symbols,
        "symbols": sorted(by_symbol.values(), key=lambda item: item["symbol"]) if include_symbols else [],
        "read_only_research": True,
    }


def persist_data_coverage_run(db_path: Path) -> dict[str, Any]:
    """Persist an immutable coverage report through an explicit operator action."""

    payload = api_stock_data_coverage(db_path)
    symbols = payload["symbols"]
    canonical = {
        "registry_id": payload["universe_registry"]["registry_id"],
        "contract_version": DATA_COVERAGE_CONTRACT_VERSION,
        "symbols": symbols,
        "interval_summary": payload["interval_summary"],
    }
    content_hash = hashlib.sha256(json.dumps(canonical, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    run_id = f"dcr_{content_hash[:20]}"
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO data_coverage_runs(
              coverage_run_id, registry_id, contract_version, as_of_time, content_hash, summary_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, payload["universe_registry"]["registry_id"], DATA_COVERAGE_CONTRACT_VERSION, payload["as_of"], content_hash, json.dumps(payload["interval_summary"], sort_keys=True), payload["as_of"]),
        )
        for item in symbols:
            for interval, observation in item["intervals"].items():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO data_coverage_items(
                      coverage_run_id, symbol, interval, source, provider_status, adjustment_mode,
                      candle_count, first_time, last_time, fetched_at, gap_count, max_gap_seconds,
                      eligibility_status, details_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (run_id, item["symbol"], interval, observation["source"], observation["provider_status"], observation["adjustment_mode"], observation["candle_count"], observation["first_time"], observation["last_time"], observation["fetched_at"], observation["gap_count"], observation["max_gap_seconds"], "eligible" if observation.get("eligible_for_canonical_validation") else "not_eligible", json.dumps(observation, sort_keys=True)),
                )
        conn.commit()
    return {"coverage_run_id": run_id, "content_hash": content_hash, "created": True, "coverage": payload}
