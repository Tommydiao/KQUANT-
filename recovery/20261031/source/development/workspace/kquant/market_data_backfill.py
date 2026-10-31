from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .data_coverage import api_stock_data_coverage
from .local_env import load_market_data_env
from .market_data_quota import (
    DEFAULT_MONTHLY_SYMBOL_QUOTA,
    MAX_DOCUMENTED_MONTHLY_SYMBOL_QUOTA,
    backfill_quota_status,
)
from .stock_signals import LONG_BRIDGE_CANDLE_SOURCE, api_stock_candles, api_stock_universe
from .stock_store import connect
from .universe_registry import current_universe_members, ensure_current_universe_registry, ensure_stock_universe_catalog


BACKFILL_VERSION = "longbridge_backfill_v1.3.0"
BACKFILL_TIMEFRAMES = (
    ("daily", "5y", "1d", 900),
    ("hourly", "2y", "1h", 220),
)


def _is_provider_symbol_quota_error(payload: dict[str, Any]) -> bool:
    errors = [str(item).lower() for item in payload.get("provider_errors") or []]
    return any("301607" in item and ("symbol" in item or "candlestick" in item) for item in errors)


def create_backfill_job(
    *,
    db_path: Path,
    symbols: list[str] | None = None,
    pause_seconds: float = 0.5,
    max_attempts: int = 3,
    monthly_symbol_cap: int | None = None,
) -> dict[str, Any]:
    """Queue a resumable Longbridge-only backfill; no network call occurs here."""

    ensure_stock_universe_catalog(db_path)
    registry = ensure_current_universe_registry(db_path)
    requested = {item.strip().upper() for item in (symbols or []) if item.strip()}
    members = [item for item in current_universe_members(db_path) if not requested or item["symbol"] in requested]
    if requested - {item["symbol"] for item in members}:
        raise ValueError("One or more requested symbols are not in the active universe registry.")
    quota = backfill_quota_status(
        db_path=db_path,
        requested_symbols=[item["symbol"] for item in members],
        monthly_symbol_cap=monthly_symbol_cap,
    )
    if not bool(quota["allowed"]):
        raise ValueError(
            "Longbridge monthly new-symbol cap would be exceeded; resume only already-audited symbols "
            "or set KQUANT_LONGBRIDGE_MONTHLY_SYMBOL_CAP to your verified entitlement."
        )
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
            (
                job_id,
                registry["registry_id"],
                json.dumps(BACKFILL_TIMEFRAMES),
                pause_seconds,
                max_attempts,
                now,
                json.dumps({"backfill_version": BACKFILL_VERSION, "symbol_count": len(members), "quota_preflight": quota}, sort_keys=True),
            ),
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
    return {
        "job_id": job_id,
        "status": "queued",
        "symbol_count": len(members),
        "item_count": len(members) * len(BACKFILL_TIMEFRAMES),
        "registry": registry,
        "quota_preflight": quota,
    }


def create_quota_recovery_job(
    *,
    db_path: Path,
    source_job_id: str,
    monthly_symbol_cap: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Clone only provider-quota-blocked work into a new manual queue.

    The source job remains immutable. This function never calls Longbridge;
    the operator must separately run a bounded batch after the fresh-month
    preflight reports that it is allowed.
    """

    source_id = str(source_job_id or "").strip()
    if not source_id:
        raise ValueError("A source backfill job id is required.")
    with connect(db_path) as conn:
        source = conn.execute("SELECT * FROM market_backfill_jobs WHERE job_id=?", (source_id,)).fetchone()
        if source is None:
            raise ValueError(f"Unknown backfill job: {source_id}")
        if str(source["provider"]) != "longbridge":
            raise ValueError("Only Longbridge market-data jobs can be recovered.")
        items = conn.execute(
            """
            SELECT symbol, interval, range_value, minimum_bars
            FROM market_backfill_job_items
            WHERE job_id=?
              AND (
                status='blocked_quota'
                OR last_error LIKE '%301607%'
                OR result_json LIKE '%301607%'
              )
            ORDER BY symbol, interval
            """,
            (source_id,),
        ).fetchall()
        active_recovery = conn.execute(
            """
            SELECT job_id FROM market_backfill_jobs
            WHERE status IN ('queued', 'running')
              AND details_json LIKE ?
            LIMIT 1
            """,
            (f'%"resumed_from_job_id": "{source_id}"%',),
        ).fetchone()
    if active_recovery is not None:
        raise ValueError(f"An active quota-recovery job already exists: {active_recovery['job_id']}")
    if not items:
        raise ValueError("The source job has no provider-quota-blocked items to recover.")
    symbols = sorted({str(item["symbol"]) for item in items})
    quota = backfill_quota_status(
        db_path=db_path,
        requested_symbols=symbols,
        monthly_symbol_cap=monthly_symbol_cap,
        now=now,
    )
    if not bool(quota["allowed"]):
        raise ValueError(
            "Longbridge quota preflight is not ready for recovery: "
            f"{quota['status']}. Recheck the provider entitlement before creating a new queue."
        )
    requested_at = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
    job_id = f"mbj_{uuid.uuid4().hex}"
    details = {
        "backfill_version": BACKFILL_VERSION,
        "resumed_from_job_id": source_id,
        "source_job_status": str(source["status"]),
        "recovery_reason": "provider_quota_301607",
        "symbol_count": len(symbols),
        "item_count": len(items),
        "quota_preflight": quota,
        "network_started": False,
        "manual_run_required": True,
    }
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO market_backfill_jobs(
              job_id, provider, registry_id, status, requested_intervals_json,
              pause_seconds, max_attempts, requested_at, details_json
            ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                source["provider"],
                source["registry_id"],
                source["requested_intervals_json"],
                source["pause_seconds"],
                source["max_attempts"],
                requested_at,
                json.dumps(details, sort_keys=True),
            ),
        )
        conn.executemany(
            """
            INSERT INTO market_backfill_job_items(
              job_id, symbol, interval, range_value, minimum_bars, status,
              attempts, next_attempt_at, last_error, result_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'queued', 0, NULL, '', ?, ?)
            """,
            [
                (
                    job_id,
                    item["symbol"],
                    item["interval"],
                    item["range_value"],
                    item["minimum_bars"],
                    json.dumps(
                        {
                            "resumed_from_job_id": source_id,
                            "recovery_reason": "provider_quota_301607",
                            "network_started": False,
                        },
                        sort_keys=True,
                    ),
                    requested_at,
                )
                for item in items
            ],
        )
        conn.commit()
    return {
        "job_id": job_id,
        "status": "queued",
        "resumed_from_job_id": source_id,
        "source_job_status": str(source["status"]),
        "symbol_count": len(symbols),
        "item_count": len(items),
        "quota_preflight": quota,
        "network_started": False,
        "manual_run_required": True,
        "read_only_market_data": True,
    }


def run_backfill_job(*, db_path: Path, job_id: str, batch_size: int = 10) -> dict[str, Any]:
    """Run one bounded, restart-safe batch. Reference fallback is a failed item."""

    environment = load_market_data_env()
    with connect(db_path) as conn:
        job = conn.execute("SELECT * FROM market_backfill_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if job is None:
            raise ValueError(f"Unknown backfill job: {job_id}")
        if job["status"] in {"completed", "cancelled", "blocked_quota"}:
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
    quota = backfill_quota_status(db_path=db_path, requested_symbols=[str(item["symbol"]) for item in items])
    if items and not bool(quota["allowed"]):
        now = datetime.now(UTC).isoformat()
        blocked_by_provider = bool(quota.get("provider_quota_lock"))
        blocked_status = "blocked_quota" if blocked_by_provider else "failed"
        reason = (
            "Longbridge historical symbol quota is exhausted for this calendar month."
            if blocked_by_provider
            else "Longbridge monthly new-symbol cap preflight blocked this item."
        )
        with connect(db_path) as conn:
            for item in items:
                conn.execute(
                    """
                    UPDATE market_backfill_job_items
                    SET status=?, attempts=attempts + 1, last_error=?, result_json=?, updated_at=?
                    WHERE job_id=? AND symbol=? AND interval=?
                    """,
                    (
                        blocked_status,
                        reason,
                        json.dumps({"source": "quota_preflight", "provider_status": "blocked", "coverage_status": blocked_status}, sort_keys=True),
                        now,
                        job_id,
                        item["symbol"],
                        item["interval"],
                    ),
                )
            if blocked_by_provider:
                conn.execute(
                    "UPDATE market_backfill_jobs SET status='blocked_quota', completed_at=? WHERE job_id=?",
                    (now, job_id),
                )
            conn.commit()
        report = backfill_job_status(db_path=db_path, job_id=job_id)
        report.update({"processed_in_batch": 0, "environment": environment, "quota_preflight": quota})
        return report
    completed = 0
    provider_quota_exhausted = False
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
            provider_available = bool(
                payload.get("provider_status") == "available"
                and payload.get("source_type") == LONG_BRIDGE_CANDLE_SOURCE
            )
            quota_error = _is_provider_symbol_quota_error(payload)
            full_coverage = provider_available and count >= int(item["minimum_bars"])
            partial_history = provider_available and 0 < count < int(item["minimum_bars"])
            success = provider_available and count > 0 and not quota_error
            result = {
                "source": payload.get("source_type"),
                "provider_status": payload.get("provider_status"),
                "candle_count": count,
                "minimum_bars": int(item["minimum_bars"]),
                "coverage_status": "provider_quota_exhausted" if quota_error else "full" if full_coverage else "limited_history" if partial_history else "unavailable",
                "errors": list(payload.get("provider_errors") or [])[:3],
            }
            error = (
                "Longbridge historical symbol quota is exhausted for this calendar month."
                if quota_error
                else ""
                if full_coverage
                else "Longbridge history is available but below target coverage."
                if partial_history
                else "longbridge coverage remains insufficient or unavailable"
            )
        except Exception as exc:  # provider failures must become auditable, resumable work
            success, partial_history, quota_error, result, error = False, False, False, {}, f"{type(exc).__name__}: {exc}"
        with connect(db_path) as conn:
            attempts = int(item["attempts"]) + 1
            retry = not success and attempts < int(job["max_attempts"])
            status = "blocked_quota" if quota_error else "completed" if success and not partial_history else "completed_limited" if success else ("retry" if retry else "failed")
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
        if quota_error:
            provider_quota_exhausted = True
            with connect(db_path) as conn:
                conn.execute(
                    """
                    UPDATE market_backfill_job_items
                    SET status='blocked_quota', last_error=?, result_json=?, updated_at=?
                    WHERE job_id=? AND status IN ('queued', 'retry')
                    """,
                    (
                        "Longbridge historical symbol quota is exhausted for this calendar month.",
                        json.dumps({"source": "provider_quota", "provider_status": "blocked", "coverage_status": "provider_quota_exhausted"}, sort_keys=True),
                        now,
                        job_id,
                    ),
                )
                conn.execute(
                    "UPDATE market_backfill_jobs SET status='blocked_quota', completed_at=? WHERE job_id=?",
                    (now, job_id),
                )
                conn.commit()
            break
        if float(job["pause_seconds"]) > 0:
            time.sleep(float(job["pause_seconds"]))
    with connect(db_path) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM market_backfill_job_items WHERE job_id=? AND status IN ('queued','retry')", (job_id,)).fetchone()[0]
        if provider_quota_exhausted:
            conn.execute(
                "UPDATE market_backfill_jobs SET status='blocked_quota', completed_at=? WHERE job_id=?",
                (datetime.now(UTC).isoformat(), job_id),
            )
            conn.commit()
        elif not remaining:
            conn.execute("UPDATE market_backfill_jobs SET status='completed', completed_at=? WHERE job_id=?", (datetime.now(UTC).isoformat(), job_id))
            conn.commit()
    report = backfill_job_status(db_path=db_path, job_id=job_id)
    report["processed_in_batch"] = completed
    report["environment"] = environment
    report["quota_preflight"] = quota
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
    pause_seconds: float = 0.5,
    monthly_symbol_cap: int | None = None,
) -> dict[str, Any]:
    """Fill canonical candle coverage without treating a reference fallback as eligible data."""

    ensure_stock_universe_catalog(db_path)
    environment = load_market_data_env()
    universe_payload = api_stock_universe(universe=universe, db_path=db_path)
    requested = {item.strip().upper() for item in (symbols or []) if item.strip()}
    stocks = [item for item in universe_payload.get("stocks", []) if not requested or item["symbol"] in requested]
    if limit:
        stocks = stocks[: max(1, int(limit))]
    quota = backfill_quota_status(
        db_path=db_path,
        requested_symbols=[str(stock["symbol"]) for stock in stocks],
        monthly_symbol_cap=monthly_symbol_cap,
    )
    if not bool(quota["allowed"]):
        raise ValueError(
            "Longbridge monthly new-symbol cap would be exceeded; use the resumable queue for already-audited symbols "
            "or configure a verified entitlement cap."
        )
    started_at = datetime.now(UTC).isoformat()
    results: list[dict[str, Any]] = []
    for stock in stocks:
        timeframe_results = []
        for name, range_value, interval, minimum_bars in BACKFILL_TIMEFRAMES:
            if not bool(environment["longbridge_credentials_configured"]):
                payload = {
                    "provider_status": "unavailable",
                    "source_type": "longbridge_credentials_missing",
                    "candles": [],
                    "provider_errors": ["Longbridge credentials are not configured for this backfill process."],
                }
            else:
                payload = api_stock_candles(
                    stock["symbol"],
                    range_value,
                    interval,
                    "live",
                    db_path,
                    allow_reference_fallback=False,
                )
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
            "coverage_status": "full" if eligible else "limited_history" if source == LONG_BRIDGE_CANDLE_SOURCE and candle_count > 0 else "unavailable",
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
        "environment": environment,
        "quota_preflight": quota,
        "reference_fallback_counts_as_eligible": False,
        "read_only_market_data": True,
    }
    outputs_dir.mkdir(parents=True, exist_ok=True)
    (outputs_dir / "longbridge-backfill-latest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report
