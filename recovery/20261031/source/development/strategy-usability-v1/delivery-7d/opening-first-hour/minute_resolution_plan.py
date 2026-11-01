"""Bounded pure selection reuse; never stores method authority or eligibility."""
from collections import OrderedDict
from threading import Lock

from prepared_minutes import PreparedMinute


class ResolutionPreparation:
    def __init__(self, bound=8192):
        self.bound = bound
        self.entries = OrderedDict()
        self.lock = Lock()
        self.hits = self.misses = 0

    def select(self, raw_pairs, eligible_pairs, method_identity, policy_identity, factory):
        # Eligibility is recomputed by the caller. Only exact immutable content
        # and the resulting sets may reuse a pure selection, not a saved verdict.
        if not all(isinstance(row, PreparedMinute) for _, row in raw_pairs):
            return factory()
        key = (method_identity, policy_identity,
               tuple(identity for identity, _ in raw_pairs),
               tuple(identity for identity, _ in eligible_pairs))
        with self.lock:
            if key in self.entries:
                self.hits += 1
                self.entries.move_to_end(key)
                return self.entries[key]
        value = factory()
        if value is not None and not isinstance(value, str):
            raise TypeError('RESOLUTION_SELECTION_MUST_BE_ID_OR_NONE')
        with self.lock:
            self.misses += 1
            self.entries[key] = value
            self.entries.move_to_end(key)
            while len(self.entries) > self.bound:
                self.entries.popitem(last=False)
        return value

    def snapshot(self):
        with self.lock:
            return dict(entries=len(self.entries), bound=self.bound, hits=self.hits,
                        misses=self.misses, eligibility_cached=False, authority_cached=False)
