"""Coalesced read-only history cache, separate from the trend calculation lane."""
from collections import OrderedDict
from datetime import timedelta
import threading

from .options_two_hour_data import sessions_before


class HistoryCache:
    def __init__(self, load, *, clock, on_ready, refresh_seconds=60):
        self.load, self.clock, self.on_ready = load, clock, on_ready
        self.refresh_seconds = refresh_seconds
        self.lock = threading.Condition()
        self.pending = OrderedDict()
        self.values = {}
        self.session_complete = set()
        self.retry_at = {}
        self.revisions = {}
        self.active = None
        self.day = None
        self.prior_sessions = []
        self.stopped = False
        self.completed = 0
        self.thread = threading.Thread(target=self._run, name="opening-trend-history", daemon=True)
        self.thread.start()

    def _session(self, day):
        if self.day is not None and day < self.day:
            return False
        if self.day != day:
            self.day = day
            self.prior_sessions = sessions_before(day, 20)
            self.pending.clear()
            self.values.clear()
            self.session_complete.clear()
            self.retry_at.clear()
            self.revisions.clear()
        return True

    def _fresh(self, key, cached, now):
        if not cached or cached[2] or cached[0] > now:
            return False
        if key in self.session_complete:
            from .options_one_minute import NY
            return now.astimezone(NY).date() == key[1]
        return now < cached[0] + timedelta(seconds=self.refresh_seconds)

    def request(self, symbol, day, *, urgent=False):
        now = self.clock()
        key = symbol, day
        with self.lock:
            if self.stopped or not self._session(day) or key == self.active:
                return
            if key in self.session_complete and self._fresh(key, self.values.get(key), now):
                return
            if now < self.retry_at.get(key, now):
                return
            self.pending.setdefault(key, None)
            if urgent:
                self.pending.move_to_end(key, last=False)
            self.lock.notify()

    def get(self, symbol, day, now):
        key = symbol, day
        with self.lock:
            cached = self.values.get(key)
            if self._fresh(key, cached, now):
                return cached[1], {"state": "READY", "loaded_at": cached[0].isoformat(),
                                   "session_complete": key in self.session_complete}
            state = "FAILED" if cached and cached[2] else "STALE" if cached else "PENDING"
            diagnostic = {"state": state, "loaded_at": cached[0].isoformat() if cached else None,
                          "error_type": cached[2] if cached else None}
        self.request(symbol, day, urgent=True)
        with self.lock:
            prior = list(self.prior_sessions) if self.day == day else []
        # An empty envelope is not a complete baseline and cannot qualify a signal.
        return {"symbol": symbol, "session": day.isoformat(),
                "prior_sessions": prior, "slots": {}}, diagnostic

    def snapshot(self):
        with self.lock:
            now = self.clock()
            fresh = [v for key, v in self.values.items() if self._fresh(key, v, now)]
            quality = [v[1].get("input_coverage", {}) for v in fresh]
            return {"cached_symbols": sum(not v[2] for v in self.values.values()),
                    "failed_symbols": sum(bool(v[2]) for v in self.values.values()),
                    "pending_symbols": len(self.pending), "active_symbol": self.active[0] if self.active else None,
                    "completed": self.completed, "session": self.day.isoformat() if self.day else None,
                    "fresh_symbols": len(fresh),
                    "session_complete_symbols": sum(key in self.session_complete and self._fresh(key, value, now)
                                                    for key, value in self.values.items()),
                    "coverage_as_of": min((v[0].isoformat() for v in fresh), default=None),
                    "input_coverage": {"checked_symbols": sum(bool(v) for v in quality),
                        "both_baselines_ready": sum(v.get("ready_baseline_groups") == 2 for v in quality),
                        "one_baseline_ready": sum(v.get("ready_baseline_groups") == 1 for v in quality),
                        "prior_close_ready": sum(v.get("prior_close", {}).get("state") == "READY" for v in quality),
                        "historical_inputs_ready": sum(bool(v.get("inputs_ready")) for v in quality),
                        "invalid_cached_evidence_symbols": sum(bool(v.get("invalid_minutes")) for v in quality),
                        "full_rule_calculation_ready": False}}

    def invalidate(self, symbol, day):
        key = symbol, day
        with self.lock:
            if self.day != day or self.stopped:
                return
            self.values.pop(key, None)
            self.session_complete.discard(key)
            self.retry_at.pop(key, None)
            self.revisions[key] = self.revisions.get(key, 0) + 1
        self.request(symbol, day, urgent=True)

    def _run(self):
        while True:
            with self.lock:
                self.lock.wait_for(lambda: self.pending or self.stopped)
                if self.stopped:
                    return
                key, _ = self.pending.popitem(last=False)
                self.active = key
                revision = self.revisions.get(key, 0)
            symbol, day = key
            try:
                value, error = self.load(symbol, day, self.clock()), None
                if not isinstance(value, dict) or value.get("symbol") != symbol or value.get("session") != day.isoformat():
                    raise ValueError("HISTORY_CACHE_IDENTITY_MISMATCH")
            except Exception as exc:
                value, error = None, type(exc).__name__
            loaded_at = self.clock()
            complete = False
            if error is None and value.get("input_coverage", {}).get("inputs_ready") is True:
                # Revalidate immutable historical evidence, not a caller's READY flag.
                from .options_opening_trend_prewarm import coverage
                try:
                    value["input_coverage"] = coverage(value, loaded_at)
                    complete = value["input_coverage"]["inputs_ready"]
                except (ValueError, TypeError, KeyError, AttributeError):
                    value["input_coverage"] = {"inputs_ready": False}
            with self.lock:
                self.active = None
                same_session = self.day == day and not self.stopped
                current = same_session and self.revisions.get(key, 0) == revision
                if current:
                    self.values[key] = loaded_at, value, error
                    self.session_complete.discard(key)
                    if complete:
                        self.session_complete.add(key)
                    self.retry_at[key] = loaded_at + timedelta(seconds=self.refresh_seconds)
                    self.completed += 1
            if same_session and not current:
                self.request(symbol, day, urgent=True)
            if current and error is None:
                try:
                    self.on_ready(symbol, day)
                except Exception:
                    # A failed retry callback must not terminate the shared history lane.
                    with self.lock:
                        self.values[key] = loaded_at, value, "RetryCallbackError"

    def close(self):
        with self.lock:
            self.stopped = True
            self.pending.clear()
            self.lock.notify_all()
        self.thread.join(timeout=2)
