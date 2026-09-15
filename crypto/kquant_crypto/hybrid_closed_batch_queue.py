"""Delay received closed bars until their availability ordering is provable."""
from copy import deepcopy
import math


class ClosedBatchQueue:
    def __init__(self, symbols, last_committed):
        self.symbols = frozenset(symbols)
        self.last_committed = last_committed
        self.pending = {}

    def add(self, symbol, bar, received_upper):
        if symbol not in self.symbols or not math.isfinite(received_upper):
            raise ValueError('Known symbol and finite receipt required')
        start = bar['start']
        if type(start) is not int or start % 300:
            raise ValueError('Closed 5m boundary required')
        if start + 300 <= self.last_committed:
            return False
        bucket = self.pending.setdefault(start, {})
        old = bucket.get(symbol)
        if old:
            if old['bar'] != bar:
                raise ValueError('Conflicting closed bar revision')
            return False
        bucket[symbol] = {'bar': deepcopy(bar), 'received_upper': received_upper}
        return True

    def ready(self, received_lower, received_upper):
        if not all(math.isfinite(v) for v in (received_lower, received_upper)) or received_lower > received_upper:
            raise ValueError('Ordered finite clock interval required')
        if not self.pending:
            return None
        start = min(self.pending)
        bucket = self.pending[start]
        if received_upper - (start + 300) > 30:
            raise ValueError('Closed batch missed original 30-second entry deadline')
        available = max(x['received_upper'] for x in bucket.values())
        if set(bucket) != self.symbols or received_lower < max(start + 300, available):
            return None
        return {'start': start, 'five': {s: deepcopy(x['bar']) for s, x in bucket.items()},
                'inputs_available_at_upper': available}

    def committed(self, start):
        if start not in self.pending:
            raise ValueError('Unknown committed batch')
        self.pending.pop(start)
        self.last_committed = start + 300
