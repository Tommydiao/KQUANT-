"""Small persistent diagnostics independent of provider and database calls."""
from __future__ import annotations

import faulthandler
import json
import os
from datetime import UTC, datetime
from pathlib import Path


def worker_health(state, *, alive, now=None):
    now = now or datetime.now(UTC)
    result = dict(state)
    stamp = state.get("stage_started_at") or state.get("last_cycle_at")
    try:
        age = (now - datetime.fromisoformat(stamp)).total_seconds()
    except (TypeError, ValueError):
        age = None
    health = "STOPPED" if not alive else "STARTING" if age is None else (
        "TIME_CONFLICT" if age < 0 else "STALLED" if age > 45 else "RESPONSIVE")
    result.update(thread_alive=bool(alive), runtime_health=health,
                  stage_age_seconds=age, health_checked_at=now.isoformat())
    result["research_ready"] = bool(alive and state.get("first_loop_at")
                                    and health == "RESPONSIVE" and state.get("state") in {
                                        "WAIT_MARKET", "WAIT_PREWARM_WINDOW", "PREWARM", "PREMARKET_CHECK",
                                        "SHADOW_MONITORING", "EXIT_MONITORING", "MARKET_CLOSED"})
    progress = "NOT_EXPECTED_IN_CURRENT_PHASE"
    bar_age = None
    if state.get("state") == "SHADOW_MONITORING":
        try:
            expected = datetime.fromisoformat(state["first_bar_expected_at"])
            bar_stamp = state.get("last_persisted_bar")
            bar_age = (now - datetime.fromisoformat(bar_stamp)).total_seconds() if bar_stamp else None
            progress = ("WAIT_FIRST_BAR" if now < expected else "NO_COMPLETE_BAR" if bar_age is None else
                        "TIME_CONFLICT" if bar_age < 0 else "BAR_PROGRESS_STALE" if bar_age > 90 else "BAR_PROGRESSING")
        except (KeyError, TypeError, ValueError):
            progress = "UNKNOWN"
    result.update(research_progress=progress, last_bar_age_seconds=bar_age)
    if health in {"STOPPED", "STALLED", "TIME_CONFLICT"}:
        result["reported_state"] = result.get("state")
        result["state"] = state["state"] if state.get("state") in {"FAILED_INIT", "FAILED_RUNTIME", "CLEANUP_FAILED", "CLEANUP_PENDING"} else health
    return result


class RuntimeDiagnostics:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.dump_count = 0
        self.last_dump = None

    def write(self, status, *, now=None):
        now = now or datetime.now(UTC)
        target = self.root / "one-minute-worker.json"
        temporary = target.with_suffix(".tmp")
        payload = {"pid": os.getpid(), "observed_at": now.isoformat(), "worker": status}
        temporary.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")
        temporary.replace(target)
        if (status.get("runtime_health") == "STALLED" and self.dump_count < 3
                and (self.last_dump is None or (now - self.last_dump).total_seconds() >= 300)):
            # Python stacks contain code locations, not local values or credentials.
            with (self.root / f"worker-stall-{os.getpid()}-{self.dump_count}.log").open("w") as out:
                out.write(json.dumps({"observed_at": now.isoformat(), "pid": os.getpid(),
                    "stage": status.get("stage"), "runtime_health": status.get("runtime_health")}) + "\n")
                out.flush()
                faulthandler.dump_traceback(file=out, all_threads=True)
            self.dump_count += 1
            self.last_dump = now
