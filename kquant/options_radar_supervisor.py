from __future__ import annotations

import os
import json
import threading
import uuid
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .market_calendar import market_schedule
from .operations import record_operational_event
from .options_radar import latest_premarket_report, refresh_intraday_radar, run_premarket_radar, monitor_option_plans, dispatch_option_alerts
from .option_runtime import OptionProcessLock, checkpoint, record_task, write_heartbeat, runtime_status
from .stock_store import connect


NEW_YORK = ZoneInfo("America/New_York")


class OptionRadarSupervisor:
    """Schedule the read-only premarket radar and bounded intraday reviews."""

    def __init__(self, db_path: Path, hub: Any) -> None:
        self.db_path = db_path
        self.hub = hub
        self.enabled = os.getenv("KQUANT_OPTION_RADAR_ENABLED", "true").lower() == "true"
        self.interval_seconds = max(30, int(os.getenv("KQUANT_OPTION_RADAR_INTERVAL_SECONDS", "60")))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._risk_thread: threading.Thread | None = None
        self._delivery_thread: threading.Thread | None = None
        self._owner = uuid.uuid4().hex
        self._process_lock = OptionProcessLock(db_path, "supervisor")
        self._job_lock = OptionProcessLock(db_path, "scan")
        self._scan_thread: threading.Thread | None = None
        self._scan_guard = threading.Lock()
        self._lock = threading.RLock()
        self._last_intraday_bucket = ""
        self._status: dict[str, Any] = {
            "enabled": self.enabled,
            "running": False,
            "state": "not_started",
            "last_cycle_at": None,
            "last_premarket_run_at": None,
            "last_intraday_run_at": None,
            "last_error": None,
            "cycles": 0,
        }

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        if not self._process_lock.acquire():
            self._status.update({"state": "already_running_elsewhere", "running": False})
            return
        self._recover_scan_jobs()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="kquant-option-radar", daemon=True)
        self._thread.start()
        self._risk_thread = threading.Thread(target=self._run_risk, name="kquant-option-monitor", daemon=True)
        self._risk_thread.start()
        self._delivery_thread = threading.Thread(target=self._run_delivery, name="kquant-option-delivery", daemon=True)
        self._delivery_thread.start()
        with self._lock:
            self._status.update({"running": True, "state": "running"})

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        if self._risk_thread and self._risk_thread.is_alive():
            self._risk_thread.join(timeout=3)
        if self._delivery_thread and self._delivery_thread.is_alive():
            self._delivery_thread.join(timeout=3)
        alive = any(thread and thread.is_alive() for thread in (self._thread, self._risk_thread, self._scan_thread, self._delivery_thread))
        if not alive:
            self._process_lock.release()
        with self._lock:
            self._status.update({"running": bool(alive), "state": "stopping" if alive else "stopped"})

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._status,
                "interval_seconds": self.interval_seconds,
                "premarket_schedule": "08:30 America/New_York",
                "earliest_intraday_confirmation": "09:40 America/New_York",
                "manual_execution_only": True,
                "order_submission_enabled": False,
                "active_scan_job": self._active_scan_job(),
                "persistent_runtime": runtime_status(self.db_path),
                "next_premarket_at": self._next_premarket(),
            }

    def _next_premarket(self) -> str | None:
        current = datetime.now(UTC).astimezone(NEW_YORK)
        for offset in range(10):
            day = current.date() + timedelta(days=offset)
            scheduled = datetime.combine(day, time(8, 30), NEW_YORK)
            if scheduled > current and market_schedule(day, self.db_path).get("is_trading_day"):
                return scheduled.astimezone(UTC).isoformat()
        return None

    def _active_scan_job(self) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM option_scan_jobs WHERE status IN ('queued','running') ORDER BY requested_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            item["detail"] = {}
        return item

    def _recover_scan_jobs(self) -> None:
        # OS ownership, not an elapsed-time guess, establishes that no scan is active.
        if not self._job_lock.acquire():
            return
        try:
            with connect(self.db_path) as conn:
                now = datetime.now(UTC).isoformat()
                conn.execute("""UPDATE option_scan_jobs SET status='failed', finished_at=?,
                    updated_at=?, error_message='interrupted_before_completion'
                    WHERE status IN ('queued','running')""", (now, now))
                conn.commit()
        finally:
            self._job_lock.release()

    def request_scan(self) -> dict[str, Any]:
        active = self._active_scan_job()
        if active or (self._scan_thread and self._scan_thread.is_alive()):
            return active or {"status": "running"}
        now = datetime.now(UTC).isoformat()
        job_id = f"option-scan-{uuid.uuid4().hex[:20]}"
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO option_scan_jobs(
                  job_id, job_type, status, requested_at, started_at, finished_at,
                  run_id, detail_json, error_message, created_at, updated_at
                ) VALUES (?, 'premarket_manual', 'queued', ?, NULL, NULL, NULL, '{}', '', ?, ?)
                """,
                (job_id, now, now, now),
            )
            conn.commit()
        self._scan_thread = threading.Thread(
            target=self._run_scan_job,
            args=(job_id,),
            name=f"kquant-option-scan-{job_id[-6:]}",
            daemon=True,
        )
        self._scan_thread.start()
        return self.scan_job(job_id)

    def scan_job(self, job_id: str) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM option_scan_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError("Unknown option scan job.")
        item = dict(row)
        try:
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            item["detail"] = {}
        return item

    def _run_scan_job(self, job_id: str) -> None:
        started = datetime.now(UTC).isoformat()
        with connect(self.db_path) as conn:
            conn.execute(
                "UPDATE option_scan_jobs SET status='running', started_at=?, updated_at=? WHERE job_id=?",
                (started, started, job_id),
            )
            conn.commit()
        try:
            with self._scan_guard:
                if not self._job_lock.acquire():
                    raise RuntimeError("option_scan_busy")
                try:
                    current = datetime.now(UTC)
                    day = current.astimezone(NEW_YORK).date()
                    schedule = market_schedule(day, self.db_path)
                    if (not schedule.get('is_trading_day') or
                            current >= datetime.fromisoformat(schedule['regular_close_utc'])):
                        raise RuntimeError('market_closed_no_premarket_backfill')
                    result = run_premarket_radar(self.db_path, hub=self.hub)
                finally:
                    self._job_lock.release()
            finished = datetime.now(UTC).isoformat()
            detail = {
                "market_date": result.get("market_date"),
                "opportunity_count": len(result.get("opportunities") or []),
                "data_status": result.get("data_status"),
            }
            with connect(self.db_path) as conn:
                conn.execute(
                    """
                    UPDATE option_scan_jobs
                    SET status='completed', finished_at=?, run_id=?, detail_json=?, updated_at=?
                    WHERE job_id=?
                    """,
                    (finished, result.get("run_id"), json.dumps(detail, sort_keys=True), finished, job_id),
                )
                conn.commit()
            with self._lock:
                self._status["last_premarket_run_at"] = finished
        except Exception as exc:  # noqa: BLE001 - job failure is persisted for recovery.
            finished = datetime.now(UTC).isoformat()
            message = f"{type(exc).__name__}: {str(exc)[:500]}"
            with connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE option_scan_jobs SET status='failed', finished_at=?, error_message=?, updated_at=? WHERE job_id=?",
                    (finished, message, finished, job_id),
                )
                conn.commit()
            record_operational_event(
                self.db_path,
                event_type="option_radar_manual_scan_failed",
                severity="error",
                component="option_radar_supervisor",
                message=message,
            )

    def cycle_once(self, now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        local = current.astimezone(NEW_YORK)
        schedule = market_schedule(local.date(), self.db_path)
        with self._lock:
            self._status["last_cycle_at"] = current.isoformat()
            self._status["cycles"] = int(self._status["cycles"]) + 1
        if not schedule.get("is_trading_day"):
            return {"status": "idle", "reason": "not_a_us_trading_day"}
        if local.time() < time(8, 30):
            return {"status": "idle", "reason": "before_0830_et"}
        market_close = datetime.fromisoformat(str(schedule["regular_close_utc"]))
        if current >= market_close:
            return {"status": "idle", "reason": "market_closed_no_premarket_backfill"}
        latest = latest_premarket_report(self.db_path, local.date().isoformat())
        actions: list[dict[str, Any]] = []
        prior = checkpoint(self.db_path, f"premarket:{local.date()}")
        if latest.get("status") == "not_run" and not (prior and prior["status"] in {"completed", "failed"}):
            task_key = f"premarket:{local.date()}"
            prior = checkpoint(self.db_path, task_key)
            if prior and prior["status"] in {"completed", "failed"}:
                return {"status": "idle", "reason": "daily_attempt_recorded", "task_key": task_key}
            with self._scan_guard:
                if not self._job_lock.acquire():
                    return {"status": "idle", "reason": "scan_busy"}
                detail = {"scheduled_at": datetime.combine(local.date(), time(8, 30), NEW_YORK).isoformat(),
                          "actual_started_at": current.isoformat(), "catch_up": local.time() >= time(8, 31)}
                try:
                    record_task(self.db_path, task_key, "premarket", str(local.date()), "running", detail, current)
                    report = run_premarket_radar(self.db_path, now=current, hub=self.hub)
                    record_task(self.db_path, task_key, "premarket", str(local.date()), "completed",
                                {**detail, "run_id": report.get("run_id"), "opportunity_count": len(report.get("opportunities") or [])}, datetime.now(UTC))
                except Exception as exc:
                    record_task(self.db_path, task_key, "premarket", str(local.date()), "failed",
                                {**detail, "error_type": type(exc).__name__}, datetime.now(UTC))
                    raise
                finally:
                    self._job_lock.release()
            actions.append({"type": "premarket", "run_id": report.get("run_id"), "count": len(report.get("opportunities") or [])})
            with self._lock:
                self._status["last_premarket_run_at"] = current.isoformat()
        if time(9, 40) <= local.time() and current <= market_close + timedelta(minutes=5):
            bucket = current.replace(minute=(current.minute // 5) * 5, second=0, microsecond=0).isoformat()
            saved = checkpoint(self.db_path, f"intraday:{bucket}")
            if bucket != self._last_intraday_bucket and not (saved and saved["status"] == "completed"):
                if not self._job_lock.acquire():
                    return {"status": "idle", "reason": "scan_busy"}
                try:
                    record_task(self.db_path, f"intraday:{bucket}", "intraday", str(local.date()), "running", {}, current)
                    result = refresh_intraday_radar(self.db_path, now=current, hub=self.hub)
                    record_task(self.db_path, f"intraday:{bucket}", "intraday", str(local.date()), "completed",
                                {"updated": result.get("updated", 0)}, datetime.now(UTC))
                except Exception as exc:
                    record_task(self.db_path, f"intraday:{bucket}", "intraday", str(local.date()), "failed",
                                {"error_type": type(exc).__name__}, datetime.now(UTC))
                    raise
                finally:
                    self._job_lock.release()
                self._last_intraday_bucket = bucket
                actions.append({"type": "intraday", "status": result.get("status"), "updated": result.get("updated", 0)})
                with self._lock:
                    self._status["last_intraday_run_at"] = current.isoformat()
        with self._lock:
            self._status.update({"state": "running", "last_error": None})
        return {"status": "completed", "actions": actions}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.cycle_once()
                write_heartbeat(self.db_path, "scan", self._owner, "running", result, datetime.now(UTC))
            except Exception as exc:  # noqa: BLE001 - one cycle must not stop the research watcher.
                message = f"{type(exc).__name__}: {str(exc)[:300]}"
                with self._lock:
                    self._status.update({"state": "degraded", "last_error": message})
                try:
                    write_heartbeat(self.db_path, "scan", self._owner, "degraded", {"error_type": type(exc).__name__}, datetime.now(UTC))
                    record_operational_event(self.db_path, event_type="option_radar_supervisor_error",
                        severity="error", component="option_radar_supervisor", message=type(exc).__name__)
                except Exception:
                    pass
            self._stop.wait(self.interval_seconds)

    def _run_risk(self) -> None:
        while not self._stop.is_set():
            try:
                result = monitor_option_plans(self.db_path, hub=self.hub)
                write_heartbeat(self.db_path, "monitor", self._owner, "running", result, datetime.now(UTC))
            except Exception as exc:
                try:
                    write_heartbeat(self.db_path, "monitor", self._owner, "degraded", {"error_type": type(exc).__name__}, datetime.now(UTC))
                except Exception:
                    pass
            self._stop.wait(self.interval_seconds)

    def _run_delivery(self) -> None:
        while not self._stop.is_set():
            try:
                result = dispatch_option_alerts(self.db_path)
                write_heartbeat(self.db_path, "delivery", self._owner, "running", result, datetime.now(UTC))
            except Exception as exc:
                try:
                    write_heartbeat(self.db_path, "delivery", self._owner, "degraded", {"error_type": type(exc).__name__}, datetime.now(UTC))
                except Exception:
                    pass
            self._stop.wait(self.interval_seconds)
