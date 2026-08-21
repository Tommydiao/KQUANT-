from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .data_coverage import api_stock_data_coverage
from .local_env import load_market_data_env
from .stock_signals import LONG_BRIDGE_CANDLE_SOURCE, api_stock_candles, api_stock_universe
from .stock_store import connect
from .universe_registry import current_universe_members, ensure_current_universe_registry


BACKFILL_VERSION = "longbridge_backfill_v1.1.0"
BACKFILL_TIMEFRAMES = (
    ("daily", "5y", "1d", 900),
    ("hourly", "2y", "1h", 220),
)


def create_backfill_job(
    *,
    db_path: Path,
    symbols: list[str] | None = None,
    pause_seconds: float = 0.2,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Queue a resumable Longbridge-only backfill; no network call occurs here."""

    registry = ensure_current_universe_registry(db_path)
    requested = {item.strip().upper() for item in (symbols or []) if item.strip()}
    members = [item for item in current_universe_members(db_path) if not requested or item["symbol"] in requested]
    if requested - {item["symbol"] for item in members}:
        raise ValueError("One or more requested symbols are not in the active universe registry.")
    job_id = f"mbj_{uuid.uuid4().hex}"
    now = datetime.now(UTC).isoformat()
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO market_backfill_jobs(
              job_id, provider, registry_id, status, requested_intervals_json,
              pause_seconds, max_attempts, requested_at, details_json
            ) VALUES (?, 'longbridge', ?, 'queued', ?, ?, ?, ?, ?)
            """,
            (job_id, registry["registry_id"], json.dumps(BACKFILL_TIMEFRAMES), pause_seconds, max_attempts, now, json.dumps({"symbol_count": len(members)}, sort_keys=True)),
        )
        conn.executemany(
            """
            INSERT INTO market_backfill_job_items(
              job_id, symbol, interval, range_value, minimum_bars, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'queued', ?)
            """,
            [
                (job_id, member["symbol"], interval, range_value, minimum_bars, now)
                for member in members
                for _, range_value, interval, minimum_bars in BACKFILL_TIMEFRAMES
            ],
        )
        conn.commit()
    return {"job_id": job_id, "status": "queued", "symbol_count": len(members), "item_count": len(members) * len(BACKFILL_TIMEFRAMES), "registry": registry}


def run_backfill_job(*, db_path: Path, job_id: str, batch_size: int = 10) -> dict[str, Any]:
    """Run one bounded, restart-safe batch. Reference fallback is a failed item."""

    environment = load_market_data_env()
    with connect(db_path) as conn:
        job = conn.execute("SELECT * FROM market_backfill_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if job is None:
            raise ValueError(f"Unknown backfill job: {job_id}")
        if job["status"] in {"completed", "cancelled"}:
            return backfill_job_status(db_path=db_path, job_id=job_id)
        conn.execute("UPDATE market_backfill_jobs SET status='running', started_at=COALESCE(started_at, ?) WHERE job_id=?", (datetime.now(UTC).isoformat(), job_id))
        items = conn.execute(
            """
            SELECT * FROM market_backfill_job_items
            WHERE job_id=? AND status IN ('queued', 'retry')
            ORDER BY symbol, interval LIMIT ?
            """,
            (job_id, max(1, batch_size)),
        ).fetchall()
        conn.commit()
    completed = 0
    for item in items:
        now = datetime.now(UTC).isoformat()
        try:
            if not bool(environment["longbridge_credentials_configured"]):
                raise RuntimeError("Longbridge credentials are not configured for this backfill process.")
            payload = api_stock_candles(
                str(item["symbol"]),
                str(item["range_value"]),
                str(item["interval"]),
                "live",
                db_path,
                allow_reference_fallback=False,
            )
            count = len(payload.get("candles") or [])
            success = bool(payload.get("provider_status") == "available" and payload.get("source_type") == LONG_BRIDGE_CANDLE_SOURCE and count >= int(item["minimum_bars"]))
            result = {"source": payload.get("source_type"), "provider_status": payload.get("provider_status"), "candle_count": count, "errors": list(payload.get("provider_errors") or [])[:3]}
            error = "" if success else "longbridge coverage remains insufficient or unavailable"
        except Exception as exc:  # provider failures must become auditable, resumable work
            success, result, error = False, {}, f"{type(exc).__name__}: {exc}"
        with connect(db_path) as conn:
            attempts = int(item["attempts"]) + 1
            retry = not success and attempts < int(job["max_attempts"])
            status = "completed" if success else ("retry" if retry else "failed")
            conn.execute(
                """
                UPDATE market_backfill_job_items
                SET status=?, attempts=?, next_attempt_at=?, last_error=?, result_json=?, updated_at=?
                WHERE job_id=? AND symbol=? AND interval=?
                """,
                (status, attempts, now if retry else None, error, json.dumps(result, sort_keys=True), now, job_id, item["symbol"], item["interval"]),
            )
            conn.commit()
        completed += 1
        if float(job["pause_seconds"]) > 0:
            time.sleep(float(job["pause_seconds"]))
    with connect(db_path) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM market_backfill_job_items WHERE job_id=? AND status IN ('queued','retry')", (job_id,)).fetchone()[0]
        if not remaining:
            conn.execute("UPDATE market_backfill_jobs SET status='completed', completed_at=? WHERE job_id=?", (datetime.now(UTC).isoformat(), job_id))
            conn.commit()
    report = backfill_job_status(db_path=db_path, job_id=job_id)
    report["processed_in_batch"] = completed
    report["environment"] = environment
    return report


def backfill_job_status(*, db_path: Path, job_id: str) -> dict[str, Any]:
    with connect(db_path) as conn:
        job = conn.execute("SELECT * FROM market_backfill_jobs WHERE job_id=?", (job_id,)).fetchone()
        if job is None:
            raise ValueError(f"Unknown backfill job: {job_id}")
        counts = conn.execute("SELECT status, COUNT(*) AS count FROM market_backfill_job_items WHERE job_id=? GROUP BY status", (job_id,)).fetchall()
    return {"job": dict(job), "item_counts": {str(row["status"]): int(row["count"]) for row in counts}, "read_only_market_data": True}


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
