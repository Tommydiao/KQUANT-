"""Bounded single-flight reads for expensive, read-only status payloads."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from copy import deepcopy
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
import logging


class SnapshotUnavailable(RuntimeError):
    pass


class StatusSnapshot:
    def __init__(self, *, ttl=5, wait_seconds=0.25, retain_invalidated=False, on_complete=None, executor=None):
        self.ttl, self.wait_seconds = ttl, wait_seconds
        self.retain_invalidated = retain_invalidated
        self.on_complete = on_complete
        self.owns_pool = executor is None
        self.pool = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="status-snapshot")
        self.lock = Lock()
        self.future = None
        self.pending_key = None
        self.cache_key = None
        self.value = None
        self.completed = 0
        self.as_of = None
        self.error = None
        self.error_detail = None
        self.attempted = float("-inf")
        self.started_at = None
        self.generation = 0
        self.pending_generation = 0
        self.cache_generation = None
        self.pending_started = None
        self.last_fault_log_key = None
        self.last_fault_log_at = float("-inf")

    def invalidate(self):
        with self.lock:
            self.generation += 1

    def refresh(self, key, loader):
        """Schedule from a background owner; HTTP readers never start work."""
        if not self.lock.acquire(blocking=False):
            return False
        try:
            self._collect()
            changed = self.pending_generation != self.generation or self.pending_key != key
            if self.future is not None or self._fresh(key) or (
                    not changed and monotonic() - self.attempted < self.ttl):
                return False
            self.pending_key = key
            self.attempted = self.pending_started = monotonic()
            self.pending_generation = self.generation
            self.started_at = datetime.now(UTC).isoformat()
            self.future = self.pool.submit(loader)
            self.future.add_done_callback(self._notify_complete)
            return True
        finally:
            self.lock.release()

    def peek(self, key):
        """Non-waiting memory read, including when the loader or lock is stuck."""
        if not self.lock.acquire(blocking=False):
            raise SnapshotUnavailable("STATUS_SNAPSHOT_BUSY")
        try:
            if self.cache_key != key or self.value is None:
                raise SnapshotUnavailable("STATUS_SNAPSHOT_LOADING_OR_UNAVAILABLE")
            value = self.value
            metadata = {"state": "FRESH" if self._fresh(key) else "STALE",
                "as_of": self.as_of, "refresh_pending": self.future is not None,
                "generation_requested": self.generation, "generation_computed": self.cache_generation,
                "error_type": self.error, "error_detail": self.error_detail}
        finally:
            self.lock.release()
        # Collected values are replaced, never edited by the cache owner.
        return {**deepcopy(value), "snapshot": deepcopy(metadata)}

    def _notify_complete(self, future):
        if self.on_complete is not None and not future.cancelled() and future.exception() is None:
            try:
                self.on_complete()
            except Exception:
                # Delivery failure must not destroy the completed read snapshot.
                pass

    def _collect(self):
        if self.future is None or not self.future.done():
            return
        try:
            value = self.future.result()
            # Progress snapshots may remain useful, but their old generation must
            # never be labelled fresh or renew any underlying evidence timestamp.
            if self.pending_generation == self.generation or self.retain_invalidated:
                self.value = value
                self.cache_key = self.pending_key
                self.cache_generation = self.pending_generation
                self.completed = self.pending_started
                self.as_of = self.started_at
                self.error = None
                self.error_detail = None
                self.last_fault_log_key = None
        except Exception as exc:
            self.error = type(exc).__name__
            self.error_detail = getattr(exc, "diagnostic", None)
            if self.error_detail:
                key = tuple(self.error_detail.get(field) for field in
                            ("code", "phase", "error_type", "sqlite_code", "returncode"))
                now = monotonic()
                if key != self.last_fault_log_key or now - self.last_fault_log_at >= 60:
                    logging.getLogger(__name__).warning("status_query_failed %s", self.error_detail)
                    self.last_fault_log_key, self.last_fault_log_at = key, now
        self.future = None

    def read(self, key, loader):
        wait_until = monotonic() + self.wait_seconds
        for attempt in range(2):
            with self.lock:
                self._collect()
                fresh = self._fresh(key)
                changed = self.pending_generation != self.generation or self.pending_key != key
                if not fresh and self.future is None and (changed or monotonic() - self.attempted >= self.ttl):
                    self.pending_key = key
                    self.attempted = self.pending_started = monotonic()
                    self.pending_generation = self.generation
                    self.started_at = datetime.now(UTC).isoformat()
                    self.future = self.pool.submit(loader)
                    self.future.add_done_callback(self._notify_complete)
                future = self.future
                generation = self.generation
            if not fresh and future is not None:
                try:
                    future.result(timeout=max(0, wait_until - monotonic()))
                except TimeoutError:
                    pass
                except Exception:
                    pass
            with self.lock:
                self._collect()
                invalidated = generation != self.generation or self.pending_generation != self.generation
            if not invalidated or attempt == 1:
                break
        with self.lock:
            self._collect()
            fresh = self._fresh(key)
            if self.cache_key != key or self.value is None:
                raise SnapshotUnavailable("STATUS_SNAPSHOT_LOADING_OR_UNAVAILABLE")
            result = deepcopy(self.value)
            result["snapshot"] = {"state": "FRESH" if fresh else "STALE",
                "as_of": self.as_of, "refresh_pending": self.future is not None,
                "generation_requested": self.generation, "generation_computed": self.cache_generation,
                "error_type": self.error, "error_detail": deepcopy(self.error_detail)}
            return result

    def _fresh(self, key):
        return (self.cache_key == key and self.value is not None
                and self.cache_generation == self.generation
                and monotonic() - self.completed < self.ttl and self.error is None)

    def close(self):
        if self.owns_pool:
            self.pool.shutdown(wait=False, cancel_futures=True)
