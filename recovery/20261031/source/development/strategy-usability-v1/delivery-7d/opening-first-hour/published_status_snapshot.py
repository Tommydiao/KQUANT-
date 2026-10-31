"""Single-owner snapshot publication; readers never contend on the loader lock."""
from copy import deepcopy
from time import monotonic

from .status_snapshot import StatusSnapshot as OriginalStatusSnapshot, SnapshotUnavailable


class PublishedStatusSnapshot(OriginalStatusSnapshot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._published = None

    def _collect(self):
        super()._collect()
        # One reference publishes the complete version, including failed refreshes.
        # Values are owned by the loader/cache and are never mutated after return.
        if self.value is not None:
            self._published = (
                self.cache_key, self.value, self.cache_generation, self.completed,
                self.as_of, self.error, deepcopy(self.error_detail),
            )

    def peek(self, key):
        published = self._published
        if published is None or published[0] != key:
            raise SnapshotUnavailable("STATUS_SNAPSHOT_LOADING_OR_UNAVAILABLE")
        _, value, generation, completed, as_of, error, detail = published
        requested = self.generation
        result = deepcopy(value)
        # Invalidation during the copy must also revoke freshness.
        fresh = (generation == requested == self.generation
                 and monotonic() - completed < self.ttl and error is None)
        result["snapshot"] = {
            "state": "FRESH" if fresh else "STALE", "as_of": as_of,
            "refresh_pending": self.future is not None,
            "generation_requested": self.generation, "generation_computed": generation,
            "error_type": error, "error_detail": deepcopy(detail),
        }
        return result
