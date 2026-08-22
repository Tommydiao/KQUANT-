from __future__ import annotations

from collections import Counter
from math import ceil
from pathlib import Path
from typing import Any

from .data_coverage import LONG_BRIDGE_SOURCE, MODEL_REQUIRED_INTERVALS
from .market_availability import MARKET_AVAILABILITY_CONTRACT_VERSION
from .quant_dataset import DatasetIntegrityError, read_quant_dataset
from .stock_quant_validation import latest_stock_quant_validation
from .stock_store import connect


STOCK_QUANT_READINESS_VERSION = "stock_quant_readiness_v1.1.0"


def _date_key(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else None


def _coverage_rows(db_path: Path, *, available_at: str | None = None) -> dict[str, dict[str, Any]]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT u.symbol, c.interval, COUNT(c.open_time) AS candle_count,
                   MIN(c.open_time) AS first_time, MAX(c.open_time) AS last_time,
                   SUM(
                     CASE WHEN
                       (c.interval = '1d' AND datetime(c.open_time, '+1 day') <= datetime(?))
                       OR (c.interval = '1h' AND datetime(c.open_time, '+1 hour') <= datetime(?))
                     THEN 1 ELSE 0 END
                   ) AS available_candle_count
            FROM stock_universe AS u
            LEFT JOIN market_candles AS c
              ON c.symbol = u.symbol
             AND c.primary_source = ?
             AND c.provider_status = 'available'
             AND c.bar_state = 'closed_candle'
             AND c.interval IN ('1d', '1h')
            WHERE u.active = 1
            GROUP BY u.symbol, c.interval
            ORDER BY u.symbol, c.interval
            """,
            (
                available_at or "0000-01-01T00:00:00+00:00",
                available_at or "0000-01-01T00:00:00+00:00",
                LONG_BRIDGE_SOURCE,
            ),
        ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        symbol = str(row["symbol"])
        item = result.setdefault(symbol, {"symbol": symbol, "intervals": {}})
        if row.get("interval"):
            item["intervals"][str(row["interval"])] = {
                "candle_count": int(row.get("candle_count") or 0),
                "available_candle_count": int(row.get("available_candle_count") or 0),
                "first_time": row.get("first_time"),
                "last_time": row.get("last_time"),
            }
    return result


def _active_universe_count(db_path: Path) -> int:
    with connect(db_path) as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM stock_universe WHERE active = 1").fetchone()
    return int(row["count"] or 0)


def _interval_reasons(
    observation: dict[str, Any] | None,
    *,
    interval: str,
    start_date: str,
    end_date: str,
) -> list[str]:
    minimum = int(MODEL_REQUIRED_INTERVALS[interval])
    prefix = "daily" if interval == "1d" else "confirmation"
    if not observation:
        return [f"{prefix}_missing"]
    reasons: list[str] = []
    if int(observation.get("candle_count") or 0) < minimum:
        reasons.append(f"{prefix}_history_below_minimum")
    if int(observation.get("available_candle_count") or 0) < minimum:
        reasons.append(f"{prefix}_history_below_window_start")
    first = _date_key(observation.get("first_time"))
    last = _date_key(observation.get("last_time"))
    if first is None or first > start_date:
        reasons.append(f"{prefix}_starts_after_window")
    if last is None or last < end_date:
        reasons.append(f"{prefix}_ends_before_window")
    return reasons


def stock_quant_window_coverage(
    db_path: Path,
    *,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Measure historical Longbridge coverage for one explicit validation window.

    This differs from the operational quote/K-line coverage metric. A symbol is
    eligible here only when closed daily and confirmation bars span the full
    immutable validation window, not merely when it has a recent minimum bar
    count.
    """

    normalized_start = _date_key(start_date)
    normalized_end = _date_key(end_date)
    if not normalized_start or not normalized_end or normalized_start > normalized_end:
        raise ValueError("A valid inclusive validation start/end date is required.")
    by_symbol = _coverage_rows(db_path, available_at=f"{normalized_start}T23:59:59+00:00")
    symbols: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    current_eligible = 0
    window_eligible = 0
    for symbol in sorted(by_symbol):
        item = by_symbol[symbol]
        intervals = item["intervals"]
        current_ok = all(
            int((intervals.get(interval) or {}).get("candle_count") or 0) >= int(minimum)
            for interval, minimum in MODEL_REQUIRED_INTERVALS.items()
        )
        reasons = [
            reason
            for interval in MODEL_REQUIRED_INTERVALS
            for reason in _interval_reasons(
                intervals.get(interval),
                interval=interval,
                start_date=normalized_start,
                end_date=normalized_end,
            )
        ]
        if current_ok:
            current_eligible += 1
        if not reasons:
            window_eligible += 1
        reason_counts.update(reasons)
        symbols.append(
            {
                "symbol": symbol,
                "current_signal_eligible": current_ok,
                "validation_window_eligible": not reasons,
                "reasons": reasons,
                "intervals": intervals,
            }
        )
    universe_symbols = len(symbols)
    required_symbols = ceil(universe_symbols * 0.90)
    return {
        "contract_version": STOCK_QUANT_READINESS_VERSION,
        "window": {"start_date": normalized_start, "end_date": normalized_end},
        "universe_symbols": universe_symbols,
        "current_signal_eligible_symbols": current_eligible,
        "validation_window_eligible_symbols": window_eligible,
        "validation_window_coverage_pct": round(window_eligible / universe_symbols * 100, 2) if universe_symbols else 0.0,
        "target_pct": 90.0,
        "target_symbols": required_symbols,
        "target_met": window_eligible >= required_symbols if universe_symbols else False,
        "additional_symbols_required": max(0, required_symbols - window_eligible),
        "reason_counts": dict(sorted(reason_counts.items())),
        "symbols": symbols,
        "market_availability_contract": MARKET_AVAILABILITY_CONTRACT_VERSION,
        "read_only_research": True,
    }


def stock_quant_validation_readiness(db_path: Path, dataset_id: str | None = None) -> dict[str, Any]:
    """Explain whether real historical coverage can support the latest validation.

    The endpoint never fetches or writes market data. It exists to keep a high
    current-coverage percentage from being confused with point-in-time coverage
    over the whole sealed validation range.
    """

    requested_dataset = str(dataset_id or "").strip()
    latest = latest_stock_quant_validation(db_path) if not requested_dataset else {}
    validation_run = dict(latest.get("run") or {})
    resolved_dataset = requested_dataset or str(validation_run.get("dataset_id") or "")
    if not resolved_dataset:
        return {
            "status": "not_materialized",
            "contract_version": STOCK_QUANT_READINESS_VERSION,
            "dataset": None,
            "universe_symbols": _active_universe_count(db_path),
            "reason": "Materialize an immutable Stock Quant dataset before measuring its historical validation window.",
            "read_only_research": True,
        }
    try:
        dataset = read_quant_dataset(db_path, resolved_dataset)
    except (ValueError, DatasetIntegrityError) as exc:
        return {
            "status": "dataset_unavailable",
            "contract_version": STOCK_QUANT_READINESS_VERSION,
            "dataset": {"dataset_id": resolved_dataset},
            "reason": str(exc),
            "read_only_research": True,
        }
    coverage = stock_quant_window_coverage(
        db_path,
        start_date=str(dataset["start_date"]),
        end_date=str(dataset["end_date"]),
    )
    signal_dates = {_date_key(item.get("signal_time")) for item in dataset.get("items") or []}
    dataset_symbols = {str(item.get("symbol") or "") for item in dataset.get("items") or []}
    coverage.update(
        {
            "status": "ready" if coverage["target_met"] else "limited",
            "dataset": {
                "dataset_id": resolved_dataset,
                "integrity_status": dataset.get("integrity_status"),
                "item_count": len(dataset.get("items") or []),
                "symbol_count": len(dataset_symbols - {""}),
                "signal_date_count": len(signal_dates - {None}),
                "validation_run_id": validation_run.get("run_id"),
            },
            "reason": (
                "Historical Longbridge coverage was already available at every validation-window start point."
                if coverage["target_met"]
                else "Backfill verified Longbridge daily and confirmation history that was available before the validation window begins before widening model evidence."
            ),
        }
    )
    if latest.get("status") == "stale_registry":
        coverage["status"] = "stale_registry"
        coverage["registry_alignment"] = (validation_run.get("registry_alignment") or {})
        coverage["reason"] = (
            "The validation dataset belongs to an older universe Registry and is blocked until a new aligned dataset is sealed."
        )
    return coverage


__all__ = [
    "STOCK_QUANT_READINESS_VERSION",
    "stock_quant_validation_readiness",
    "stock_quant_window_coverage",
]
