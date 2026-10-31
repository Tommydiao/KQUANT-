from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import threading
import uuid
import traceback
from time import monotonic
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .market_calendar import market_schedule
from .operations import record_operational_event
from .options_radar import latest_premarket_report, refresh_intraday_radar, run_premarket_radar, monitor_option_plans, monitor_option_event_risk, dispatch_option_alerts
from .options_profiles import capability_evidence, load_options_profiles
from .stock_watchlist import daily_option_scope_report
from .options_forward_paper import (
    DEFAULT_DB_PATH as FORWARD_PAPER_DB,
    DEFAULT_RUN_ID as FORWARD_PAPER_RUN_ID,
    cycle_forward_run,
    forward_status,
    start_or_resume_forward_run,
)
from .options_full_watch import full_watch_status, run_full_watch_scan, scheduled_probe_symbols
from .option_runtime import OptionProcessLock, checkpoint, record_task, write_heartbeat, runtime_status
from .stock_store import connect


NEW_YORK = ZoneInfo("America/New_York")


class OptionRadarSupervisor:
    """Schedule the read-only premarket radar and bounded intraday reviews."""

    def __init__(self, db_path: Path, hub: Any) -> None:
        self.db_path = db_path
        self.hub = hub
        self.enabled = os.getenv("KQUANT_OPTION_RADAR_ENABLED", "false").lower() == "true"
        self.mode = os.getenv("KQUANT_OPTION_RADAR_MODE", "legacy_radar").strip().lower()
        if self.mode not in {"legacy_radar", "foundation"}:
            self.mode = "invalid"
        self.interval_seconds = max(30, int(os.getenv("KQUANT_OPTION_RADAR_INTERVAL_SECONDS", "60")))
        self.foundation_auto_probe = os.getenv("KQUANT_OPTION_FOUNDATION_AUTO_PROBE", "false").lower() == "true"
        self.forward_paper_enabled = os.getenv("KQUANT_OPTION_FORWARD_PAPER_ENABLED", "false").lower() == "true"
        self.forward_paper_db = Path(os.getenv("KQUANT_OPTION_FORWARD_PAPER_DB", str(FORWARD_PAPER_DB))).resolve()
        self.forward_paper_run_id = os.getenv("KQUANT_OPTION_FORWARD_PAPER_RUN_ID", FORWARD_PAPER_RUN_ID).strip()
        self.full_watch_enabled = os.getenv("KQUANT_OPTION_FULL_WATCH_ENABLED", "false").lower() == "true"
        self.two_hour_enabled = os.getenv("KQUANT_OPTION_TWO_HOUR_RESEARCH_ENABLED", "false").lower() == "true"
        self.one_minute_shadow_enabled = os.getenv("KQUANT_OPTION_ONE_MINUTE_SHADOW_ENABLED", "false").lower() == "true"
        self._two_hour_thread: threading.Thread | None = None
        self._two_hour_worker = None
        self._one_minute_thread: threading.Thread | None = None
        self._one_minute_worker = None
        self._startup_error = None
        self._diagnostics_thread = None
        self._calendar_thread: threading.Thread | None = None
        self._calendar_runner = None
        self._clock_monitor = None
        self.full_watch_probe_count = max(0, min(int(os.getenv("KQUANT_OPTION_FULL_WATCH_PROBE_COUNT", "8")), 8))
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
            "mode": self.mode,
            "running": False,
            "state": "not_started",
            "last_cycle_at": None,
            "last_premarket_run_at": None,
            "last_intraday_run_at": None,
            "last_error": None,
            "cycles": 0,
        }

    def start(self) -> None:
        try:
            self._start()
        except Exception as exc:
            self._startup_error = {"state": "FAILED_INIT", "failed_stage": "SUPERVISOR_START",
                "error_id": uuid.uuid4().hex, "error_type": type(exc).__name__,
                "failed_at": datetime.now(UTC).isoformat(), "pid": os.getpid(),
                "candidate": os.getenv("KQUANT_BACKEND_RELEASE_ID"),
                "error_frames": [{"file": frame.filename, "line": frame.lineno, "function": frame.name}
                                 for frame in traceback.extract_tb(exc.__traceback__)[-12:]]}
            try:
                self.stop()
            except Exception as cleanup_error:
                self._startup_error["cleanup_error_type"] = type(cleanup_error).__name__
            self._status.update(state="FAILED_INIT", last_error=self._startup_error)
            try:
                from .research_runtime_health import RuntimeDiagnostics
                RuntimeDiagnostics(self.db_path.parent / "option_foundation/runtime").write(self.one_minute_worker_status())
            except Exception as diagnostic_error:
                self._startup_error["diagnostic_error_type"] = type(diagnostic_error).__name__
            raise

    def _start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        gate = getattr(self._calendar_runner, 'source_call_gate', None)
        if gate is not None and gate.snapshot()['in_flight']:
            with self._lock:
                self._status.update(state='stopping', running=True,
                                    restart_blocked_reason='SOURCE_CALL_STILL_IN_FLIGHT')
            return
        if not self._process_lock.acquire():
            self._status.update({"state": "already_running_elsewhere", "running": False})
            return
        from .options_signal_copilot import audit_paper_reservations, recover_paper_intents
        copilot_store = self.db_path.parent / "options_signal_copilot/signal_copilot.sqlite3"
        if copilot_store.exists():
            try:
                recovered = recover_paper_intents(store_path=copilot_store)
                self._status["paper_recovery"] = {"recovered": recovered["count"],
                    "quote_requests_replayed": 0, "reservations": audit_paper_reservations(store_path=copilot_store)}
            except Exception as exc:
                self._status["paper_recovery"] = {"status": "DEGRADED", "error_type": type(exc).__name__}
        self._recover_scan_jobs()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="kquant-option-radar", daemon=True)
        self._thread.start()
        self._risk_thread = threading.Thread(target=self._run_risk, name="kquant-option-monitor", daemon=True)
        self._risk_thread.start()
        self._delivery_thread = threading.Thread(target=self._run_delivery, name="kquant-option-delivery", daemon=True)
        self._delivery_thread.start()
        if self.two_hour_enabled and self.mode == "foundation":
            from .options_two_hour_runtime import TwoHourResearchWorker
            self._two_hour_worker = TwoHourResearchWorker(self.db_path, self.hub)
            self._two_hour_thread = threading.Thread(target=self._two_hour_worker.run, args=(self._stop,), name="kquant-two-hour-research", daemon=True)
            self._two_hour_thread.start()
        if self.mode == "foundation" and (self.two_hour_enabled or self.one_minute_shadow_enabled):
            from .option_calendar_source import CalendarSourceRunner
            from .options_clock_measurement import ClockAttachmentMonitor
            code_root = Path(__file__).resolve().parent.parent
            self._clock_monitor = ClockAttachmentMonitor(code_root=code_root,
                data_root=self.db_path.parent.parent,
                method_config_path=code_root/'config/review_acceptances/clock_measurement_method.json',
                acceptance_root=code_root)
            self._calendar_runner = CalendarSourceRunner(self.db_path)
            self._calendar_thread = threading.Thread(target=self._run_calendar_sources,
                name="kquant-option-calendar-sources", daemon=True)
            self._calendar_thread.start()
        if self.one_minute_shadow_enabled and self.mode == "foundation":
            from .options_one_minute_runtime import OneMinuteResearchWorker
            self._one_minute_worker = OneMinuteResearchWorker(self.db_path, self.hub)
            self._one_minute_thread = threading.Thread(target=self._one_minute_worker.run,
                args=(self._stop,), name="kquant-one-minute-shadow", daemon=True)
            self._one_minute_thread.start()
        if self._clock_monitor is not None:
            self._diagnostics_thread = threading.Thread(target=self._run_worker_diagnostics,
                name="kquant-research-diagnostics", daemon=True)
            self._diagnostics_thread.start()
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
        if self._two_hour_thread and self._two_hour_thread.is_alive():
            self._two_hour_thread.join(timeout=3)
        if self._one_minute_thread and self._one_minute_thread.is_alive():
            self._one_minute_thread.join(timeout=3)
        if self._calendar_thread and self._calendar_thread.is_alive():
            self._calendar_thread.join(timeout=3)
        if self._diagnostics_thread and self._diagnostics_thread.is_alive():
            self._diagnostics_thread.join(timeout=3)
        if self._clock_monitor is not None and not (self._diagnostics_thread and self._diagnostics_thread.is_alive()):
            self._clock_monitor.close()
        source_gate = getattr(self._calendar_runner, 'source_call_gate', None)
        source_in_flight = source_gate.close()['in_flight'] if source_gate is not None else False
        alive = any(thread and thread.is_alive() for thread in (self._thread, self._risk_thread, self._scan_thread,
                                                               self._delivery_thread, self._two_hour_thread,
                                                               self._one_minute_thread, self._calendar_thread,
                                                               self._diagnostics_thread))
        alive = alive or source_in_flight
        if not alive:
            self._process_lock.release()
        with self._lock:
            self._status.update({"running": bool(alive), "state": "stopping" if alive else "stopped"})

    def one_minute_worker_status(self, *, nonblocking=False):
        from .research_runtime_health import worker_health
        result = worker_health(self._one_minute_worker.state if self._one_minute_worker else
            (self._startup_error or {"state": "NOT_STARTED"}), alive=self._one_minute_thread is not None and self._one_minute_thread.is_alive())
        acquired = self._lock.acquire(blocking=not nonblocking)
        if not acquired:
            result["event_sources"] = {"status": "STATUS_LOCK_BUSY", "trade_eligible": False}
            return result
        try:
            result["event_sources"] = {**self._status.get("event_sources", {"status": "NOT_STARTED", "trade_eligible": False}),
                "collector_alive": self._calendar_thread is not None and self._calendar_thread.is_alive()}
            for key in ('price_action_sources', 'source_request_budget', 'source_call', 'clock_measurement'):
                result[key] = dict(self._status.get(key, {'status': 'NOT_STARTED'}))
        finally:
            self._lock.release()
        return result

    def _run_worker_diagnostics(self):
        from .research_runtime_health import RuntimeDiagnostics
        diagnostics = RuntimeDiagnostics(self.db_path.parent / "option_foundation/runtime")
        while not self._stop.is_set():
            self._tick_clock_measurement(datetime.now(UTC))
            try:
                diagnostics.write(self.one_minute_worker_status())
            except OSError as exc:
                self._status["diagnostics_error"] = type(exc).__name__
            self._stop.wait(5)
        try:
            diagnostics.write(self.one_minute_worker_status())
        except OSError:
            pass

    def _tick_clock_measurement(self, current):
        gate = getattr(self._calendar_runner, 'source_call_gate', None)
        if gate is not None:
            source_state = gate.snapshot()
            with self._lock:
                self._status['source_call'] = source_state
        if self._clock_monitor is None:
            return
        try:
            state = self._clock_monitor.tick(current)
        except Exception as exc:
            state = {"state": "MEASUREMENT_UNAVAILABLE", "precision_verified": False,
                     "error_type": type(exc).__name__, "checked_at": current.isoformat()}
        with self._lock:
            self._status["clock_measurement"] = state

    def status(self) -> dict[str, Any]:
        with self._lock:
            payload = {
                **self._status,
                "mode": self.mode,
                "interval_seconds": self.interval_seconds,
                "premarket_schedule": "disabled_in_foundation_mode" if self.mode == "foundation" else "08:30 America/New_York",
                "earliest_intraday_confirmation": "disabled_in_foundation_mode" if self.mode == "foundation" else "09:40 America/New_York",
                "manual_execution_only": True,
                "order_submission_enabled": False,
                "foundation_auto_probe": self.foundation_auto_probe,
                "forward_paper_enabled": self.forward_paper_enabled,
                "forward_paper_run_id": self.forward_paper_run_id if self.forward_paper_enabled else None,
                "full_watch_enabled": self.full_watch_enabled,
                "two_hour_research": {"enabled": self.two_hour_enabled, "paper_enabled": False,
                    "worker": dict(self._two_hour_worker.state) if self._two_hour_worker else {"state": "NOT_STARTED"}},
                "one_minute_shadow": {"enabled": self.one_minute_shadow_enabled,
                    "worker": self.one_minute_worker_status(),
                    "paper_enabled": False, "real_orders_enabled": False},
            }
        # Database latency must not hold the supervisor's shared state lock.
        payload["active_scan_job"] = self._active_scan_job()
        payload["next_premarket_at"] = self._next_premarket()
        payload["next_foundation_market_check_at"] = self._next_foundation_market_check()
        payload["next_full_watch_check_at"] = self._next_full_watch_check()
        payload["persistent_runtime"] = runtime_status(self.db_path)
        if self.full_watch_enabled:
            try:
                full_watch = full_watch_status()
                payload["full_watch"] = {
                    "status": full_watch.get("status"),
                    "scope_id": full_watch.get("scope_id"),
                    "run_id": (full_watch.get("run") or {}).get("run_id"),
                    "counts": (full_watch.get("run") or {}).get("counts"),
                }
            except Exception as exc:
                payload["full_watch"] = {"status": "DEGRADED", "error_type": type(exc).__name__}
        if self.forward_paper_enabled:
            try:
                payload["forward_paper"] = forward_status(store_path=self.forward_paper_db, run_id=self.forward_paper_run_id)
            except Exception as exc:
                payload["forward_paper"] = {"status": "DEGRADED", "error_type": type(exc).__name__, "orders_enabled": False}
        return payload

    def _calendar_collection_open(self, current: datetime, schedule: dict) -> bool:
        local = current.astimezone(NEW_YORK)
        start = datetime.combine(local.date(), time(8, 30), NEW_YORK)
        if not schedule.get("is_trading_day"):
            return False
        if self.one_minute_shadow_enabled:
            # Afternoon entries and reported positions still need current sources.
            try:
                end = datetime.fromisoformat(str(schedule["regular_close_utc"]))
                if end.tzinfo is None:
                    return False
            except (KeyError, TypeError, ValueError):
                return False
        else:
            end = datetime.combine(local.date(), time(11, 30), NEW_YORK)
        return start <= current < end

    def _run_calendar_sources(self) -> None:
        next_calendar_check = 0.0
        action_sources = {"status": "NOT_RUN", "requests": 0, "trade_eligible": False}
        while not self._stop.is_set():
            current = datetime.now(UTC)
            local = current.astimezone(NEW_YORK)
            try:
                schedule = market_schedule(local.date(), self.db_path)
                action_requests = 0
                request_cap = getattr(self._calendar_runner, "shared_source_window_cap", 12)
                from .options_price_action_source import SourceRequestBudget
                budget = SourceRequestBudget(self._calendar_runner.store / "shared-source-budget.json",
                                             cap=request_cap, now=current)
                calendar_open = self._calendar_collection_open(current, schedule)
                calendar_due = calendar_open and monotonic() >= next_calendar_check
                reserved_actions = budget.grant(getattr(self._calendar_runner, "action_batch_size", 3),
                    event_reserve=getattr(self._calendar_runner, "calendar_reserved_requests", 6) if calendar_due else 0)
                if reserved_actions:
                    try:
                        from .options_price_action_source import refresh as refresh_price_actions
                        action_sources = refresh_price_actions(self._calendar_runner, now=current,
                            cancelled=self._stop.is_set, batch_size=reserved_actions)
                        action_requests = action_sources.get("requests", 0)
                        budget.settle(reserved_actions, action_requests)
                    except Exception as exc:
                        action_sources = {"status": "SOURCE_REQUEST_FAILED", "error_type": type(exc).__name__,
                            "checked_at": current.isoformat(), "trade_eligible": False}
                budget_state = budget.snapshot()
                with self._lock:
                    self._status["price_action_sources"] = action_sources
                    self._status["source_request_budget"] = budget_state
                if not calendar_open:
                    with self._lock:
                        self._status["event_sources"] = {"status": "WAIT_COLLECTION_WINDOW",
                            "checked_at": current.isoformat(), "session": local.date().isoformat(), "trade_eligible": False}
                    self._stop.wait(30)
                    continue
                if monotonic() < next_calendar_check:
                    self._stop.wait(5)
                    continue
                next_calendar_check = monotonic() + 840
                started = monotonic()
                # Company actions consume the existing per-run request budget,
                # rather than adding three requests to the calendar allowance.
                from .options_price_action_source import refresh_calendar_in_budget
                result = refresh_calendar_in_budget(self._calendar_runner, budget=budget,
                                                    now=current, cancelled=self._stop.is_set)
                try:
                    from .option_official_source import refresh_active_reviews
                    result["official_reviews"] = refresh_active_reviews(self.db_path, now=datetime.now(UTC))
                except Exception as exc:
                    result["official_reviews"] = {"status": "SOURCE_CHECK_FAILED",
                                                   "error_type": type(exc).__name__}
                try:
                    from .options_opening_trend_event_auto import refresh_bound_sources
                    result["automatic_sources"] = refresh_bound_sources(self.db_path, now=datetime.now(UTC),
                                                                        cancelled=self._stop.is_set)
                except Exception as exc:
                    result["automatic_sources"] = {"status": "SOURCE_CHECK_FAILED",
                                                    "error_type": type(exc).__name__, "trade_eligible": False}
                budget_state = budget.snapshot()
                with self._lock:
                    self._status["event_sources"] = {**result, "checked_at": datetime.now(UTC).isoformat()}
                    self._status["source_request_budget"] = budget_state
                # Refresh before the 900-second evidence limit; request time counts.
                # Continue initial company-action coverage without rerunning the
                # full calendar or creating another source/SDK worker.
                self._stop.wait(5)
            except Exception as exc:
                with self._lock:
                    self._status["event_sources"] = {"status": "SOURCE_FAILED", "error_type": type(exc).__name__,
                        "checked_at": datetime.now(UTC).isoformat(), "trade_eligible": False}
                # Per-source cadence/claims and the persistent shared cap prevent
                # request storms. A local failure must not park clock/action work.
                self._stop.wait(5)

    def _next_premarket(self) -> str | None:
        current = datetime.now(UTC).astimezone(NEW_YORK)
        for offset in range(10):
            day = current.date() + timedelta(days=offset)
            scheduled = datetime.combine(day, time(8, 30), NEW_YORK)
            if scheduled > current and market_schedule(day, self.db_path).get("is_trading_day"):
                return scheduled.astimezone(UTC).isoformat()
        return None

    def _next_foundation_market_check(self) -> str | None:
        current = datetime.now(UTC)
        local = current.astimezone(NEW_YORK)
        for offset in range(10):
            day = local.date() + timedelta(days=offset)
            schedule = market_schedule(day, self.db_path)
            if not schedule.get("is_trading_day"):
                continue
            market_open = datetime.fromisoformat(str(schedule["regular_open_utc"])) + timedelta(minutes=5)
            market_close = datetime.fromisoformat(str(schedule["regular_close_utc"])) - timedelta(minutes=5)
            if current < market_open:
                return market_open.isoformat()
            if current < market_close:
                return current.isoformat()
        return None

    def _next_full_watch_check(self, current: datetime | None = None) -> str | None:
        if not self.full_watch_enabled:
            return None
        now = current or datetime.now(UTC)
        local = now.astimezone(NEW_YORK)
        for offset in range(10):
            day = local.date() + timedelta(days=offset)
            schedule = market_schedule(day, self.db_path)
            if not schedule.get("is_trading_day"):
                continue
            task_key = f"full-watch-rule-scan:{day}:v1"
            prior = checkpoint(self.db_path, task_key)
            if prior and prior.get("status") == "completed":
                continue
            scheduled = datetime.combine(day, time(9, 40), NEW_YORK).astimezone(UTC)
            if now < scheduled:
                return scheduled.isoformat()
            market_close = datetime.fromisoformat(str(schedule["regular_close_utc"]))
            if day == local.date() and now < market_close:
                return now.isoformat()
        return None

    def _run_foundation_probe(self, current: datetime) -> dict[str, Any]:
        root = Path(os.getenv(
            "KQUANT_OPTION_FOUNDATION_ROOT",
            str(self.db_path.resolve().parent / "option_foundation" / "runtime"),
        )).resolve()
        root.mkdir(parents=True, exist_ok=True)
        output = root / f"market_observation_{current.strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"
        script = Path(__file__).resolve().parents[1] / "scripts" / "probe_option_foundation.py"
        push_seconds = max(1, min(int(os.getenv("KQUANT_OPTION_FOUNDATION_PUSH_SECONDS", "15")), 30))
        completed = subprocess.run(
            [sys.executable, str(script), "--output", str(output), "--push-seconds", str(push_seconds)],
            cwd=str(script.parent.parent),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"foundation_capability_probe_failed:{completed.returncode}")
        evidence = output / "entitlement_and_capability.json"
        if not evidence.exists():
            raise RuntimeError("foundation_capability_evidence_missing")
        latest = Path(os.getenv("KQUANT_OPTION_CAPABILITY_EVIDENCE", str(root / "latest_capability.json"))).resolve()
        latest.parent.mkdir(parents=True, exist_ok=True)
        temporary = latest.with_suffix(latest.suffix + f".{uuid.uuid4().hex}.tmp")
        shutil.copy2(evidence, temporary)
        os.replace(temporary, latest)
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        return {
            "evidence_path": str(evidence),
            "latest_pointer": str(latest),
            "entitlement_status": payload.get("entitlement_status"),
            "quote_capability_status": payload.get("quote_capability_status"),
            "market_day_validation_status": payload.get("market_day_validation_status"),
            "push_status": (payload.get("push_observation") or {}).get("status"),
            "sample_count": len(payload.get("samples") or []),
        }

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
        if self.mode == "foundation":
            return {
                "status": "disabled",
                "reason": "PENDING_STRATEGY_DEFINITION",
                "signal_generation_enabled": False,
                "trade_simulation_enabled": False,
                "order_submission_enabled": False,
            }
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
        if self.mode == "foundation":
            task_key = f"profile-health:{local.date()}:options_research_profiles_draft_v1"
            prior = checkpoint(self.db_path, task_key)
            actions: list[dict[str, Any]] = []
            if not prior or prior["status"] != "completed":
                profiles = load_options_profiles()
                evidence = capability_evidence()
                detail = {
                    "mode": "foundation",
                    "profile_ids": [item["profile_id"] for item in profiles["profiles"]],
                    "config_sha256": profiles["config_sha256"],
                    "strategy_status": "PENDING_STRATEGY_DEFINITION",
                    "performance_status": "NOT_EVALUATED",
                    "capability_evidence": evidence,
                    "signal_generation_enabled": False,
                    "trade_simulation_enabled": False,
                    "order_submission_enabled": False,
                }
                record_task(self.db_path, task_key, "profile_health", str(local.date()), "completed", detail, current)
                actions.append({"type": "profile_health", **detail})

            if self.forward_paper_enabled:
                try:
                    start_or_resume_forward_run(
                        main_db_path=self.db_path,
                        store_path=self.forward_paper_db,
                        run_id=self.forward_paper_run_id,
                        now=current,
                    )
                    forward = cycle_forward_run(
                        main_db_path=self.db_path,
                        store_path=self.forward_paper_db,
                        run_id=self.forward_paper_run_id,
                        now=current,
                    )
                    if forward.get("status") != "IDEMPOTENT_REPLAY":
                        actions.append({"type": "forward_paper", **forward})
                except Exception as exc:
                    actions.append({
                        "type": "forward_paper_failed",
                        "status": "DEGRADED",
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:240],
                        "orders_enabled": False,
                    })

            schedule = market_schedule(local.date(), self.db_path)
            daily_bucket = "premarket" if local.time() < time(9, 40) else f"intraday-{local.strftime('%H')}{(local.minute // 5) * 5:02d}"
            daily_task = f"watchlist-daily-scope:{local.date()}:v2:{daily_bucket}"
            daily_prior = checkpoint(self.db_path, daily_task)
            if schedule.get("is_trading_day") and local.time() >= time(8, 30) and not (daily_prior and daily_prior["status"] == "completed"):
                record_task(self.db_path, daily_task, "watchlist_daily_scope", str(local.date()), "running", {}, current)
                try:
                    daily_report = daily_option_scope_report(
                        self.db_path,
                        now=current,
                        persist=True,
                        forward_store_path=self.forward_paper_db if self.forward_paper_enabled else None,
                        forward_run_id=self.forward_paper_run_id if self.forward_paper_enabled else None,
                    )
                    record_task(self.db_path, daily_task, "watchlist_daily_scope", str(local.date()), "completed", daily_report, datetime.now(UTC))
                    actions.append({"type": "watchlist_daily_scope", "status": daily_report.get("status"), "counts": daily_report.get("counts")})
                except Exception as exc:
                    detail = {"error_type": type(exc).__name__, "message": str(exc)[:240]}
                    record_task(self.db_path, daily_task, "watchlist_daily_scope", str(local.date()), "failed", detail, datetime.now(UTC))
                    actions.append({"type": "watchlist_daily_scope_failed", **detail})
            full_watch_task = f"full-watch-rule-scan:{local.date()}:v1.3"
            full_watch_prior = checkpoint(self.db_path, full_watch_task)
            if (
                self.full_watch_enabled
                and schedule.get("is_trading_day")
                and local.time() >= time(9, 40)
                and schedule.get("regular_close_utc")
                and current < datetime.fromisoformat(str(schedule["regular_close_utc"]))
                and not (full_watch_prior and full_watch_prior["status"] == "completed")
            ):
                record_task(self.db_path, full_watch_task, "full_watch_rule_scan", str(local.date()), "running", {}, current)
                try:
                    probes = scheduled_probe_symbols(self.db_path, local.date(), maximum=self.full_watch_probe_count)
                    full_watch = run_full_watch_scan(self.db_path, now=current, live_probe_symbols=probes)
                    remaining = scheduled_probe_symbols(self.db_path, local.date(), maximum=1)
                    detail = {
                        "scope_id": full_watch.get("scope_id"),
                        "run_id": (full_watch.get("run") or {}).get("run_id"),
                        "counts": (full_watch.get("run") or {}).get("counts"),
                        "probe_symbols": probes,
                        "signals_generated": False,
                        "paper_created": False,
                        "collection_round_exhausted": not bool(remaining),
                        "collection_is_not_complete_rule_coverage": True,
                    }
                    record_task(self.db_path, full_watch_task, "full_watch_rule_scan", str(local.date()), "pending" if remaining else "completed", detail, datetime.now(UTC))
                    actions.append({"type": "full_watch_rule_scan", "status": full_watch.get("status"), **detail})
                except Exception as exc:
                    detail = {"error_type": type(exc).__name__, "message": str(exc)[:240]}
                    record_task(self.db_path, full_watch_task, "full_watch_rule_scan", str(local.date()), "failed", detail, datetime.now(UTC))
                    actions.append({"type": "full_watch_rule_scan_failed", **detail})
            market_task = f"foundation-market-observation:{local.date()}:v1"
            market_prior = checkpoint(self.db_path, market_task)
            market_open = datetime.fromisoformat(str(schedule["regular_open_utc"])) + timedelta(minutes=5) if schedule.get("regular_open_utc") else None
            market_close = datetime.fromisoformat(str(schedule["regular_close_utc"])) - timedelta(minutes=5) if schedule.get("regular_close_utc") else None
            in_observation_window = bool(
                schedule.get("is_trading_day") and market_open and market_close and market_open <= current <= market_close
            )
            retry_ready = True
            if market_prior and market_prior["status"] == "failed":
                attempts = int(market_prior.get("attempts") or 0)
                finished_at = datetime.fromisoformat(str(market_prior["finished_at"])) if market_prior.get("finished_at") else current
                retry_ready = attempts < 3 and current >= finished_at + timedelta(minutes=15)
            if self.foundation_auto_probe and in_observation_window and retry_ready and not (market_prior and market_prior["status"] == "completed"):
                record_task(self.db_path, market_task, "foundation_market_observation", str(local.date()), "running", {}, current)
                try:
                    observation = self._run_foundation_probe(current)
                    record_task(self.db_path, market_task, "foundation_market_observation", str(local.date()), "completed", observation, datetime.now(UTC))
                    actions.append({"type": "foundation_market_observation", **observation})
                except Exception as exc:
                    detail = {"error_type": type(exc).__name__, "message": str(exc)[:240]}
                    record_task(self.db_path, market_task, "foundation_market_observation", str(local.date()), "failed", detail, datetime.now(UTC))
                    actions.append({"type": "foundation_market_observation_failed", **detail})
            with self._lock:
                self._status.update({"last_cycle_at": current.isoformat(), "state": "running", "last_error": None,
                                     "cycles": int(self._status["cycles"]) + 1})
            if actions:
                return {"status": "completed", "actions": actions}
            return {
                "status": "idle",
                "reason": "WAIT_MARKET" if not in_observation_window else "foundation_market_observation_recorded",
                "next_check_at": self._next_foundation_market_check(),
            }
        if self.mode == "invalid":
            raise RuntimeError("invalid_option_radar_mode")
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

    def monitor_once(self, now: datetime | None = None) -> dict[str, Any]:
        results = {}
        for name, monitor in (("deadlines", monitor_option_plans), ("event_risk", monitor_option_event_risk)):
            try:
                results[name] = monitor(self.db_path, now=now, hub=self.hub)
            except Exception as exc:
                results[name] = {"error_type": type(exc).__name__}
        degraded = any(result.get('error_type') or result.get('errors') for result in results.values())
        return {'status': 'degraded' if degraded else 'running', **results}

    def _run_risk(self) -> None:
        while not self._stop.is_set():
            try:
                result = self.monitor_once()
                write_heartbeat(self.db_path, "monitor", self._owner, result['status'], result, datetime.now(UTC))
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
            self._stop.wait(min(self.interval_seconds, 2) if (self.two_hour_enabled or self.one_minute_shadow_enabled) else self.interval_seconds)
