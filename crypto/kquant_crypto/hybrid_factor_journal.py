"""Bounded research event journal; deterministic recovery without pickle."""
import hashlib
import copy
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from .hybrid_incremental_factors import IncrementalFactors, fingerprint


def canonical(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))


class FactorJournal:
    def __init__(self, path, *, first_close, receipt_basis, source, max_events=10000):
        self.db = sqlite3.connect(path, timeout=5)
        self.contract = dict(first_close=first_close, receipt_basis=receipt_basis, source=source)
        self.limit = max_events
        self._cache = None
        if type(max_events) is not int or max_events < 1:
            self.db.close()
            raise ValueError('Positive event bound required')
        IncrementalFactors(**self.contract)
        try:
            self.db.execute('BEGIN IMMEDIATE')
            names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if names - {'factor_metadata', 'factor_events'}:
                raise ValueError('Not an independent factor research database')
            self.db.execute('CREATE TABLE IF NOT EXISTS factor_metadata (id INTEGER PRIMARY KEY CHECK(id=1), contract TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS factor_events (seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL, digest TEXT NOT NULL)')
            modules = ('hybrid_factor_journal.py', 'hybrid_incremental_factors.py',
                       'hybrid_multifactor_dev.py', 'hybrid_trend_features.py',
                       'hybrid_dependence_features.py', 'hybrid_factor_contract.py',
                       'strategy_dual_mode_v1.py')
            code_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                           for name in modules}
            contract = canonical(dict(self.contract, version='factor_journal_dev_v1',
                                      max_events=max_events, code_hashes=code_hashes))
            old = self.db.execute('SELECT contract FROM factor_metadata WHERE id=1').fetchone()
            if old and old[0] != contract:
                raise ValueError('Frozen journal contract mismatch')
            if not old:
                self.db.execute('INSERT INTO factor_metadata VALUES(1,?)', (contract,))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            self.db.close()
            raise

    @staticmethod
    def apply(engine, payload):
        if payload['kind'] == 'ingest':
            return engine.ingest(payload['symbol'], SimpleNamespace(**payload['bar']),
                                 received_at=payload['received_at'], closed=payload['closed'])
        if payload['kind'] == 'advance':
            return engine.advance(payload['frozen_at'])
        raise ValueError('Unknown research event')

    def replay(self):
        engine = IncrementalFactors(**self.contract)
        count = 0
        for payload, result, digest in self.db.execute('SELECT payload,result,digest FROM factor_events ORDER BY seq'):
            actual = canonical(self.apply(engine, json.loads(payload)))
            if actual != result or hashlib.sha256((payload + result).encode()).hexdigest() != digest:
                raise ValueError('Frozen event integrity mismatch')
            count += 1
        return engine, count

    def append(self, event_id, payload):
        if not isinstance(event_id, str) or not event_id:
            raise ValueError('Stable event ID required')
        raw = canonical(payload)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            # Read tokens under the write lock. Another connection's commit
            # invalidates data_version; writes through this connection invalidate
            # total_changes. Copy cached state so rollback cannot consume inputs.
            version = self.db.execute('PRAGMA data_version').fetchone()[0]
            changes = self.db.total_changes
            if self._cache is not None and self._cache[:2] == (version, changes):
                engine, count = copy.deepcopy(self._cache[2]), self._cache[3]
            else:
                engine, count = self.replay()
            old = self.db.execute('SELECT payload,result FROM factor_events WHERE event_id=?', (event_id,)).fetchone()
            if old:
                if old[0] != raw:
                    raise ValueError('Event correction requires a new research version')
                self.db.commit()
                return json.loads(old[1])
            if count >= self.limit:
                raise ValueError('Journal capacity reached; explicit archive required')
            result = canonical(self.apply(engine, json.loads(raw)))
            digest = hashlib.sha256((raw + result).encode()).hexdigest()
            self.db.execute('INSERT INTO factor_events(event_id,payload,result,digest) VALUES(?,?,?,?)',
                            (event_id, raw, result, digest))
            self.db.commit()
            self._cache = (version, self.db.total_changes, engine, count+1)
            return json.loads(result)
        except BaseException:
            self.db.rollback()
            self._cache = None
            raise

    def ingest(self, event_id, symbol, bar, *, received_at, closed):
        fields = dict(zip(('start', 'open', 'high', 'low', 'close', 'volume'), fingerprint(bar)))
        return self.append(event_id, dict(kind='ingest', symbol=symbol, bar=fields,
                                          received_at=received_at, closed=closed))

    def advance(self, event_id, frozen_at):
        return self.append(event_id, dict(kind='advance', frozen_at=frozen_at))

    def close(self):
        self.db.close()
