from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .operations import record_operational_event
from .early_trend_service import early_trend_snapshot
from .realtime_instructions import (
    AlertEventHub,
    evaluate_instruction_state,
    evaluate_early_trend_instruction,
    latest_instruction,
    persist_instruction,
)
from .stock_signals import api_stock_realtime_snapshot, api_stock_signals_latest


class RealtimeSupervisor:
    """Bounded local watcher for deterministic instruction state changes."""

    def __init__(self, db_path: Path, outputs_dir: Path, hub: AlertEventHub) -> None:
        self.db_path = db_path
        self.outputs_dir = outputs_dir
        self.hub = hub
        self.enabled = os.getenv("KQUANT_REALTIME_SUPERVISOR_ENABLED", "true").lower() == "true"
        self.interval_seconds = max(5, int(os.getenv("KQUANT_REALTIME_SUPERVISOR_INTERVAL_SECONDS", "15")))
        self.max_candidates = max(1, min(30, int(os.getenv("KQUANT_REALTIME_MAX_CANDIDATES", "30"))))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._candidate_index = 0
        self._early_pool_date = ""
        self._early_pool: list[dict[str, Any]] = []
        self._early_pool_source_symbols: set[str] = set()
        self._status: dict[str, Any] = {
            "enabled": self.enabled,
            "running": False,
            "state": "not_started",
            "last_cycle_at": None,
            "last_success_at": None,
            "last_error": None,
            "candidate_count": 0,
            "active_symbol": None,
            "cycles": 0,
            "instructions_created": 0,
        }

    def start(self) -> None:
        if not self.enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="kquant-realtime-supervisor", daemon=True)
        self._thread.start()
        with self._lock:
            self._status.update({"running": True, "state": "running"})

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        with self._lock:
            self._status.update({"running": False, "state": "stopped"})

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self._status,
                "interval_seconds": self.interval_seconds,
                "max_candidates": self.max_candidates,
                "read_only_research": True,
                "order_submission_enabled": False,
            }

    def cycle_once(self) -> dict[str, Any]:
        run = api_stock_signals_latest(
            db_path=self.db_path,
            outputs_dir=self.outputs_dir,
            source="live",
            universe="default",
            profile="swing_long_v1",
        )
        candidates = list(run.get("signals") or [])
        candidates.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("symbol") or "")))
        candidates = candidates[: self.max_candidates]
        pool_key = datetime.now(UTC).strftime("%Y-%m-%d")
        candidate_symbols = {str(item.get("symbol") or "").upper() for item in candidates}
        if self._early_pool_date != pool_key or candidate_symbols != self._early_pool_source_symbols:
            early_pool: list[dict[str, Any]] = []
            for candidate in candidates:
                symbol = str(candidate.get("symbol") or "").upper()
                try:
                    snapshot = early_trend_snapshot(symbol, self.db_path)
                except Exception as exc:  # noqa: BLE001 - one symbol cannot block the daily pool.
                    record_operational_event(
                        self.db_path,
                        event_type="early_trend_candidate_error",
                        severity="warning",
                        component="realtime_supervisor",
                        message=f"{symbol}: {type(exc).__name__}",
                    )
                    continue
                if snapshot.get("strategy_stage") != "NOT_READY":
                    early_pool.append(snapshot)
            stage_rank = {"BUY_REVIEW": 5, "ARMED": 4, "EARLY_WATCH": 3, "LATE_WAIT_PULLBACK": 2, "INVALIDATED": 1}
            early_pool.sort(key=lambda item: (-stage_rank.get(str(item.get("strategy_stage")), 0), -float(item.get("setup_score") or 0), str(item.get("symbol") or "")))
            self._early_pool = early_pool
            self._early_pool_date = pool_key
            self._early_pool_source_symbols = candidate_symbols
        with self._lock:
            self._status["candidate_count"] = len(self._early_pool)
            self._status["last_cycle_at"] = datetime.now(UTC).isoformat()
            self._status["cycles"] = int(self._status["cycles"]) + 1
        if not self._early_pool:
            return {"status": "idle", "candidate_count": 0, "reason": "No eligible signals in the latest canonical scan."}
        candidate = self._early_pool[self._candidate_index % len(self._early_pool)]
        self._candidate_index += 1
        symbol = str(candidate.get("symbol") or "").upper()
        with self._lock:
            self._status["active_symbol"] = symbol
        previous = latest_instruction(self.db_path, symbol)
        early_snapshot = early_trend_snapshot(symbol, self.db_path)
        instruction = evaluate_early_trend_instruction(early_snapshot, previous_state=(previous or {}).get("state"))
        if instruction is None:
            return {"status": "completed", "symbol": symbol, "instruction": None, "reason": "Early-trend setup is not ready."}
        stored = persist_instruction(self.db_path, instruction, self.hub)
        with self._lock:
            self._status["last_success_at"] = datetime.now(UTC).isoformat()
            self._status["last_error"] = None
            if not stored.get("duplicate"):
                self._status["instructions_created"] = int(self._status["instructions_created"]) + 1
        return {"status": "completed", "symbol": symbol, "instruction": stored}

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.cycle_once()
            except Exception as exc:  # noqa: BLE001 - failures remain visible and do not stop the watcher.
                message = f"{type(exc).__name__}: {str(exc)[:300]}"
                with self._lock:
                    self._status["last_error"] = message
                    self._status["state"] = "degraded"
                record_operational_event(
                    self.db_path,
                    event_type="realtime_supervisor_error",
                    severity="error",
                    component="realtime_supervisor",
                    message=message,
                )
            self._stop.wait(self.interval_seconds)
