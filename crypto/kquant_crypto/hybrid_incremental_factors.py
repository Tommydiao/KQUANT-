"""Bounded closed-hour research adapter; no provider, model or trading imports."""
import hashlib
import json
import math

from .hybrid_multifactor_dev import CORE_SYMBOLS, snapshot, cross_section
from .hybrid_trend_features import TrendFeatures
from .hybrid_dependence_features import dependence_snapshot
from .hybrid_factor_contract import factor_records


def fingerprint(bar):
    return [bar.start, bar.open, bar.high, bar.low, bar.close, bar.volume]


class IncrementalFactors:
    def __init__(self, first_close, *, receipt_basis, source, max_pending_hours=48):
        if type(first_close) is not int or first_close % 3600:
            raise ValueError('Explicit hourly start required')
        if receipt_basis not in {'OBSERVED_RECEIPT', 'REPLAY_CLOCK_FIXTURE'} or not source:
            raise ValueError('Explicit non-fabricated receipt provenance required')
        if type(max_pending_hours) is not int or max_pending_hours < 1:
            raise ValueError('Positive buffer limit required')
        self.next_close = first_close
        self.receipt_basis = receipt_basis
        self.source = source
        self.max_pending_hours = max_pending_hours
        self.pending = {}
        self.history = {s: [] for s in CORE_SYMBOLS}
        self.trend = {s: TrendFeatures() for s in CORE_SYMBOLS}
        self.digest = 'incremental_factors_dev_v1'
        self.last_frozen_at = None

    def ingest(self, symbol, bar, *, received_at, closed):
        if symbol not in CORE_SYMBOLS or closed is not True:
            raise ValueError('Only core closed-hour inputs accepted')
        end = bar.start + 3600
        if type(bar.start) is not int or bar.start % 3600 or type(received_at) is not int or received_at < end:
            raise ValueError('Receipt cannot precede the market bar close')
        values = fingerprint(bar)[1:]
        if any(not math.isfinite(v) for v in values) or min(values[:4]) <= 0 or values[4] < 0:
            raise ValueError('Invalid OHLCV')
        if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
            raise ValueError('Invalid OHLC geometry')
        if end < self.next_close:
            prior = next((b for b in self.history[symbol] if b.start == bar.start), None)
            if prior is not None and fingerprint(prior) != fingerprint(bar):
                raise ValueError('Consumed bar correction cannot rewrite frozen snapshots')
            return 'ALREADY_CONSUMED_NO_REWRITE'
        if end >= self.next_close + self.max_pending_hours * 3600:
            raise ValueError('Bounded queue exceeded; recover missing history explicitly')
        key = (symbol, end)
        if key in self.pending:
            if fingerprint(self.pending[key][0]) != fingerprint(bar):
                raise ValueError('Conflicting bar requires a new research version')
            return 'DUPLICATE'
        self.pending[key] = (bar, received_at)
        return 'QUEUED'

    def advance(self, frozen_at):
        if type(frozen_at) is not int or (self.last_frozen_at is not None and frozen_at < self.last_frozen_at):
            raise ValueError('Freeze clock must be explicit and monotone')
        output = []
        while self.next_close <= frozen_at:
            stamp = self.next_close
            keys = [(s, stamp) for s in CORE_SYMBOLS]
            if any(k not in self.pending or self.pending[k][1] > frozen_at for k in keys):
                break
            inputs = [self.pending[k] for k in keys]
            self.digest = hashlib.sha256(json.dumps([self.digest,
                [(s, fingerprint(b), receipt) for s, (b, receipt) in zip(CORE_SYMBOLS, inputs)]],
                sort_keys=True, allow_nan=False).encode()).hexdigest()
            trends = {}
            for s, (bar, _) in zip(CORE_SYMBOLS, inputs):
                self.history[s] = (self.history[s] + [bar])[-25:]
                trends[s] = self.trend[s].update(bar, stamp)
            # Arithmetic uses market-aligned closed bars. Receipt availability is
            # attached afterwards and is never replaced by the market close time.
            aligned = {s: snapshot(self.history[s], stamp) for s in CORE_SYMBOLS}
            for s in CORE_SYMBOLS:
                row = dict(aligned[s], symbol=s, as_of=stamp, source=self.source,
                    available_at=frozen_at, feature_snapshot_frozen_at=frozen_at,
                    received_at=max(receipt for _, receipt in inputs),
                    availability_basis=self.receipt_basis, dataset_hash=self.digest,
                    delay_seconds=frozen_at-stamp, execution_enabled=False)
                row['cross_section'] = cross_section(aligned, s, stamp)
                row['trend'] = trends[s]
                row['dependence'] = dependence_snapshot(self.history, s, stamp)
                for part in ('cross_section', 'trend', 'dependence'):
                    row[part] = dict(row[part], available_at=frozen_at, availability_basis=self.receipt_basis)
                row['factor_contract'] = factor_records(row)
                output.append(row)
            for key in keys:
                del self.pending[key]
            self.next_close += 3600
        self.last_frozen_at = frozen_at
        return output
