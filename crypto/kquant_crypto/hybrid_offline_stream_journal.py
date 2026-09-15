"""Independent synthetic event journal, not an account ledger or OMS adapter."""
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from .hybrid_spot_stream_contract_v12 import (
    MockConnection, OfflineExecutionDecoder, OrderExpectation, to_jsonable,
)
from .hybrid_mock_broker import exact_decimal


class OfflineStreamJournal:
    def __init__(self, directory, connection, *, max_records=10000):
        if not isinstance(connection, MockConnection):
            raise ValueError('Synthetic connection required')
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(directory / 'offline_stream_journal.sqlite3', timeout=5)
        self.connection, self.max_records = connection, max_records
        with self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY CHECK(id=1), scope TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, report_key TEXT UNIQUE NOT NULL, raw TEXT NOT NULL, received INTEGER NOT NULL, expectation TEXT, normalized TEXT NOT NULL)')
            scope = json.dumps(asdict(connection), sort_keys=True)
            old = self.db.execute('SELECT scope FROM metadata WHERE id=1').fetchone()
            if not old:
                self.db.execute('INSERT INTO metadata VALUES (1, ?)', (scope,))
        if old and old[0] != scope:
            self.db.close()
            raise ValueError('Separate journal required for another connection epoch')

    def append(self, payload, *, received_at_ms, expected=None):
        # Rebuild under the write lock. No mutated decoder survives a rollback.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            decoder = OfflineExecutionDecoder(self.connection, max_records=self.max_records)
            for raw, received, expectation, normalized, key in self.db.execute(
                    'SELECT raw, received, expectation, normalized, report_key FROM events ORDER BY seq'):
                replay = decoder.decode(raw, received_at_ms=received,
                                        expected=OrderExpectation(**json.loads(expectation)) if expectation else None)
                if replay.order.report_key != key or to_jsonable(replay) != json.loads(normalized):
                    raise ValueError('Stored event integrity mismatch; append blocked')
            result = decoder.decode(payload, received_at_ms=received_at_ms, expected=expected)
            if not result.duplicate_report:
                self.db.execute('INSERT INTO events(report_key,raw,received,expectation,normalized) VALUES(?,?,?,?,?)',
                                (result.order.report_key, result.raw_json, received_at_ms,
                                 json.dumps(asdict(expected)) if expected else None,
                                 json.dumps(to_jsonable(result), sort_keys=True)))
            self.db.commit()
            return result
        except BaseException:
            self.db.rollback()
            raise

    def close(self):
        self.db.close()

    def inventory_projection(self, **contract):
        from .hybrid_inventory_projection import project_inventory
        before = self.db.execute('SELECT COALESCE(MAX(seq),0),COUNT(*) FROM events').fetchone()
        reconciliation = self.reconcile()
        decoder = OfflineExecutionDecoder(self.connection, max_records=self.max_records)
        fills = []
        self.db.execute('BEGIN')
        try:
            if self.db.execute('SELECT COALESCE(MAX(seq),0),COUNT(*) FROM events').fetchone() != before:
                raise ValueError('Journal advanced during reconciliation; retry snapshot')
            for raw, received, expectation, normalized, key in self.db.execute(
                    'SELECT raw,received,expectation,normalized,report_key FROM events ORDER BY seq'):
                result = decoder.decode(raw, received_at_ms=received,
                    expected=OrderExpectation(**json.loads(expectation)) if expectation else None)
                if result.order.report_key != key or to_jsonable(result) != json.loads(normalized):
                    raise ValueError('Stored event integrity mismatch; inventory blocked')
                if result.fill and result.fill.symbol == contract['symbol']:
                    fills.append(result.fill)
            projection = project_inventory(fills, **contract)
            evidence_blockers = sorted({reason for order in reconciliation['orders']
                for reason in order['reasons'] if reason != 'COMMISSION_CONVERSION_UNVERIFIED'
                and not reason.startswith('COMMISSION_UNCONVERTED:')})
            if reconciliation['problems']:
                evidence_blockers.append('JOURNAL_INTEGRITY_UNVERIFIED')
            projection['reconciliation_blockers'] = evidence_blockers
            if evidence_blockers:
                projection.update(rounded_quantity=None, step_remainder=None,
                                  below_minimum_unsellable=None, minimum_filters_satisfied=False)
            self.db.commit()
            return projection
        except BaseException:
            self.db.rollback()
            raise

    @exact_decimal
    def reconcile(self):
        """Reconcile stored synthetic facts, never synthesize missing fills."""
        decoder = OfflineExecutionDecoder(self.connection, max_records=self.max_records)
        orders = {}
        problems = []
        self.db.execute('BEGIN')
        try:
            for seq, raw, received, expectation, normalized, report_key in self.db.execute(
                    'SELECT seq,raw,received,expectation,normalized,report_key FROM events ORDER BY seq'):
                result = decoder.decode(raw, received_at_ms=received,
                                        expected=OrderExpectation(**json.loads(expectation)) if expectation else None)
                if to_jsonable(result) != json.loads(normalized):
                    problems.append({'seq': seq, 'reason': 'STORED_NORMALIZATION_MISMATCH'})
                if result.order.report_key != report_key:
                    problems.append({'seq': seq, 'reason': 'STORED_REPORT_KEY_MISMATCH'})
                order = result.order
                item = orders.setdefault(order.order_key, {'cumulative': Decimal(0),
                    'cumulative_quote': Decimal(0), 'fills': Decimal(0), 'fill_quote': Decimal(0),
                    'commissions_by_asset': {},
                    'fee_unknown': False, 'unconverted_fee_assets': set(), 'protocol_reasons': set()})
                resolvable = {'CUMULATIVE_TOTAL_IS_NOT_FILL_EVIDENCE',
                              'OUT_OF_ORDER_CUMULATIVE_REQUIRES_RECONCILIATION'}
                item['protocol_reasons'].update(r for r in result.reconciliation_reasons if r not in resolvable)
                item['cumulative'] = max(item['cumulative'], order.cumulative_quantity)
                item['cumulative_quote'] = max(item['cumulative_quote'], order.cumulative_quote)
                if result.fill:
                    fill = result.fill
                    item['fills'] += fill.quantity
                    item['fill_quote'] += fill.quote_quantity
                    item['fee_unknown'] |= fill.commission is None or (fill.commission > 0 and fill.commission_asset is None)
                    if fill.commission_asset and fill.commission:
                        item['unconverted_fee_assets'].add(fill.commission_asset)
                        fees = item['commissions_by_asset']
                        fees[fill.commission_asset] = fees.get(fill.commission_asset, Decimal(0)) + fill.commission
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        output = []
        for key, item in orders.items():
            reasons = sorted(item['protocol_reasons'])
            if item['cumulative'] != item['fills']:
                reasons.append('CUMULATIVE_FILL_QUANTITY_MISMATCH')
            if item['cumulative_quote'] != item['fill_quote']:
                reasons.append('CUMULATIVE_FILL_QUOTE_MISMATCH')
            if item['fee_unknown']:
                reasons.append('COMMISSION_UNKNOWN')
            if item['unconverted_fee_assets']:
                reasons.append('COMMISSION_CONVERSION_UNVERIFIED')
            output.append({'order_key': key, 'reasons': reasons,
                           'cumulative_quantity': str(item['cumulative']),
                           'observed_fill_quantity': str(item['fills']),
                           'cumulative_quote': str(item['cumulative_quote']),
                           'observed_fill_quote': str(item['fill_quote']),
                           'commissions_by_asset': {asset: str(value) for asset, value
                                                    in sorted(item['commissions_by_asset'].items())},
                           'commission_coverage_complete': not item['fee_unknown'],
                           'commission_valuation': 'NATIVE_UNITS_ONLY_NOT_CONVERTED'})
        return {'scope': 'SYNTHETIC_JOURNAL_ONLY', 'orders': output, 'problems': problems,
                'status': 'REQUIRES_RECONCILIATION' if problems or any(x['reasons'] for x in output) else 'INTERNAL_FACTS_CONSISTENT',
                'account_reconciled': False, 'execution_allowed': False}
