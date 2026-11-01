"""Content-addressed immutable preparation, never an eligibility/result cache."""
from collections import OrderedDict
import json
from threading import Lock
from datetime import timedelta

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


def evidence_metadata(value):
    """Parse immutable evidence structure, not its current eligibility."""
    paths, boundaries, seen = set(), set(), set()
    def visit(item):
        if not isinstance(item, (dict, list, tuple)) or id(item) in seen:
            return
        seen.add(id(item))
        if isinstance(item, dict):
            for name, child in item.items():
                if name in {'source_path', 'acceptance_path'} and isinstance(child, str):
                    paths.add(child)
                if name in {'valid_until', 'expires_at', 'known_at', 'valid_from',
                            'received_at', 'available_at', 'reviewed_at', 'approved_at'}:
                    try:
                        boundaries.add(common.timestamp(child))
                    except (ValueError, TypeError, AttributeError):
                        pass
                elif isinstance(child, (dict, list, tuple)):
                    visit(child)
            if item.get('state') == 'VERIFIED_BOUND' and item.get('checked_at'):
                try:
                    boundaries.add(common.timestamp(item['checked_at']) + timedelta(seconds=900))
                except (ValueError, TypeError):
                    pass
        else:
            for child in item:
                visit(child)
    visit(value)
    return frozenset(paths), frozenset(boundaries)


def semantic_identity(bar):
    fields = ('symbol', 'open_at', 'close_at', 'available_at', 'provider_time',
              'open', 'high', 'low', 'close', 'volume', 'turnover', 'amount', 'confirmed')
    row = {name: bar.get(name) for name in fields if name in bar}
    row['interface'] = bar.get('sdk_evidence', {}).get('interface')
    try:
        row['received_before_available'] = common.timestamp(bar['received_at']) < common.timestamp(bar['available_at'])
    except (KeyError, TypeError, ValueError, AttributeError):
        row['received_before_available'] = 'UNVERIFIED'
    return common.digest(row)


class PreparedMinute(FrozenDict):
    __slots__ = ("_identity", "_evidence_metadata", "_semantic_identity", "_native_structure")
    __setattr__ = _readonly

    def __init__(self, value):
        dict.__init__(self, ((key, freeze(item)) for key, item in value.items()))
        object.__setattr__(self, "_identity", common.digest(value))
        object.__setattr__(self, "_evidence_metadata", evidence_metadata(value))
        object.__setattr__(self, "_semantic_identity", semantic_identity(value))
        from kquant import options_minute_admission as admission
        prepare_structure = getattr(admission, 'native_structure', None)
        object.__setattr__(self, "_native_structure", prepare_structure(value) if prepare_structure else None)

    @property
    def identity(self):
        return self._identity

    @property
    def evidence_metadata(self):
        return self._evidence_metadata

    @property
    def semantic_identity(self):
        return self._semantic_identity

    @property
    def native_structure(self):
        return self._native_structure


class PreparedSources(FrozenDict):
    """One fresh read's immutable source bundle, shared only by that read's users."""
    __slots__ = ('_identity', '_evidence_metadata')
    __setattr__ = _readonly

    def __init__(self, value):
        dict.__init__(self, ((key, freeze(item)) for key, item in value.items()))
        object.__setattr__(self, '_identity', common.digest(value))
        object.__setattr__(self, '_evidence_metadata', evidence_metadata(value))

    @property
    def identity(self):
        return self._identity

    @property
    def evidence_metadata(self):
        return self._evidence_metadata


class PriceBlockPreparation:
    """Reuse pure five-row aggregation only after the caller's live admission."""

    def __init__(self, bound=2048):
        if bound < 1:
            raise ValueError('PRICE_BLOCK_CACHE_BOUND_INVALID')
        self.bound = bound
        self.entries = OrderedDict()
        self.lock = Lock()

    def aggregate(self, rows, aggregate):
        result = []
        for offset in range(0, len(rows) - 4, 5):
            group = rows[offset:offset + 5]
            # Mutable input and replacement algorithms never inherit a cached result.
            if not all(isinstance(row, PreparedMinute) for row in group):
                result.extend(aggregate(group))
                continue
            key = (aggregate, tuple(row.identity for row in group))
            with self.lock:
                cached = self.entries.get(key)
                if cached is not None:
                    self.entries.move_to_end(key)
            if cached is None:
                cached = freeze(aggregate(group))
                with self.lock:
                    self.entries[key] = cached
                    self.entries.move_to_end(key)
                    while len(self.entries) > self.bound:
                        self.entries.popitem(last=False)
            result.extend(cached)
        return result


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
    __slots__ = ('_admission_key', '_evidence_metadata')
    __setattr__ = _readonly

    def __init__(self, envelope):
        value = envelope['decision']
        dict.__init__(self, ((key, freeze(item)) for key, item in value.items()))
        object.__setattr__(self, '_admission_key', decision_key(value))
        object.__setattr__(self, '_evidence_metadata', evidence_metadata(value))

    @property
    def admission_key(self):
        return self._admission_key

    @property
    def evidence_metadata(self):
        return self._evidence_metadata


def partition(rows, *, symbol, opening, until, now):
    # Same admission policy as the parent; only immutable content hashing is shared.
    from kquant.options_minute_admission import classify, POLICY_HASH
    raw, eligible, rejected = {}, {}, {}
    for row in rows:
        try:
            if common.timestamp(row["received_at"]) > now:
                continue
        except (KeyError, TypeError, ValueError, AttributeError):
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
