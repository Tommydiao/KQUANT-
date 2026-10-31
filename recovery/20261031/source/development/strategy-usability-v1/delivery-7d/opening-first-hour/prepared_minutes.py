"""Content-addressed immutable preparation, never an eligibility/result cache."""
from collections import OrderedDict
import json
from threading import Lock

from kquant import options_one_minute as common


def _readonly(*args, **kwargs):
    raise TypeError("IMMUTABLE_MINUTE_INPUT")


class FrozenList(list):
    __setitem__ = __delitem__ = append = extend = insert = pop = remove = clear = _readonly
    reverse = sort = __iadd__ = __imul__ = _readonly

    def __deepcopy__(self, memo):
        return self


class FrozenDict(dict):
    __setitem__ = __delitem__ = update = setdefault = pop = popitem = clear = __ior__ = _readonly

    def __deepcopy__(self, memo):
        return self


def freeze(value):
    if isinstance(value, (FrozenDict, FrozenList)):
        return value
    if isinstance(value, dict):
        return FrozenDict((key, freeze(item)) for key, item in value.items())
    if isinstance(value, list):
        return FrozenList(freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(freeze(item) for item in value)
    return value


class PreparedMinute(FrozenDict):
    __slots__ = ("_identity",)
    __setattr__ = _readonly

    def __init__(self, value):
        dict.__init__(self, ((key, freeze(item)) for key, item in value.items()))
        object.__setattr__(self, "_identity", common.digest(value))

    @property
    def identity(self):
        return self._identity


class MinutePreparation:
    def __init__(self, bound=8192, factory=PreparedMinute):
        self.bound = bound
        self.factory = factory
        self.entries = OrderedDict()
        self.lock = Lock()
        self.hits = self.misses = 0

    def prepare(self, raw):
        # Exact DB payload bytes/string are the key, not file size or timestamps.
        with self.lock:
            found = self.entries.get(raw)
            if found is not None:
                self.entries.move_to_end(raw)
                self.hits += 1
                return found
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("MINUTE_PAYLOAD_NOT_OBJECT")
        prepared = self.factory(value)
        with self.lock:
            existing = self.entries.get(raw)
            if existing is not None:
                self.hits += 1
                return existing
            self.entries[raw] = prepared
            self.misses += 1
            while len(self.entries) > self.bound:
                self.entries.popitem(last=False)
        return prepared

    def snapshot(self):
        with self.lock:
            return {'entries': len(self.entries), 'bound': self.bound,
                    'hits': self.hits, 'misses': self.misses,
                    'eligibility_cached': False}


def identity(row):
    return row.identity if isinstance(row, PreparedMinute) else common.digest(row)


def decision_key(value):
    return (value.get('selected_version_id'), frozenset(value.get('source_version_ids', [])),
            tuple(value.get('observed_raw_ids') or []), common.canonical(value.get('source_semantics')))


class PreparedDecision(FrozenDict):
    __slots__ = ('_admission_key',)
    __setattr__ = _readonly

    def __init__(self, envelope):
        value = envelope['decision']
        dict.__init__(self, ((key, freeze(item)) for key, item in value.items()))
        object.__setattr__(self, '_admission_key', decision_key(value))

    @property
    def admission_key(self):
        return self._admission_key


def partition(rows, *, symbol, opening, until, now):
    # Same admission policy as the parent; only immutable content hashing is shared.
    from kquant.options_minute_admission import classify, POLICY_HASH
    raw, eligible, rejected = {}, {}, {}
    for row in rows:
        try:
            if common.timestamp(row["received_at"]) > now:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        start, reason = classify(row, symbol=symbol, opening=opening, until=until, now=now)
        if start is None or not opening <= start < until:
            continue
        key = identity(row)
        raw[key] = row
        if reason:
            rejected[key] = reason
        else:
            eligible[key] = row
    return {"raw": raw, "eligible": eligible, "rejected": rejected,
            "eligibility_policy_hash": POLICY_HASH}
