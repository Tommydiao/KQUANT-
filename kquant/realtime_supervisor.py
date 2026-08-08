from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .operations import record_operational_event
from .realtime_instructions import (
    AlertEventHub,
    evaluate_instruction_state,
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
        candidates = [
            signal for signal in list(run.get("signals") or [])
            if signal.get("level") in {"BUY SETUP", "WATCH"}
        ]
        candidates.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("symbol") or "")))
        candidates = candidates[: self.max_candidates]
        with self._lock:
            self._status["candidate_count"] = len(candidates)
            self._status["last_cycle_at"] = datetime.now(UTC).isoformat()
            self._status["cycles"] = int(self._status["cycles"]) + 1
        if not candidates:
            return {"status": "idle", "candidate_count": 0, "reason": "No eligible signals in the latest canonical scan."}
        candidate = candidates[self._candidate_index % len(candidates)]
        self._candidate_index += 1
        symbol = str(candidate.get("symbol") or "").upper()
        with self._lock:
            self._status["active_symbol"] = symbol
        previous = latest_instruction(self.db_path, symbol)
        snapshot = api_stock_realtime_snapshot(symbol, self.db_path)
        instruction = evaluate_instruction_state(
            candidate,
            snapshot,
            previous_state=(previous or {}).get("state"),
        )
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

