"""Explicit TEST_ONLY transport through real math, queue, storage and selection."""
from datetime import timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from kquant import options_one_minute as common
from kquant import options_opening_trend_store as store
from kquant import options_opening_trend_jobs as jobs
from first_hour import evaluate_comparison_pair, policies
from first_hour_current import current
from first_hour_pipeline import step


def inputs(minutes=55):
    base = Path(__file__).resolve().parents[3]/'workspace'
    spec = spec_from_file_location('first_hour_test_inputs', base/'tests/test_options_opening_momentum.py')
    fixture = module_from_spec(spec)
    spec.loader.exec_module(fixture)
    args = fixture.inputs(minutes=minutes)
    args.pop('right')
    args['checkpoint'] = args['opening']+timedelta(minutes=minutes)
    native = dict(symbol='TEST', provider_symbol='TEST.US', currency='USD',
        source='LONGBRIDGE_SECURITY_STATIC_INFO', received_at=args['opening'].isoformat())
    native['source_hash'] = common.digest(native)
    args['reference']['raw_quote'] = dict(symbol='TEST', currency='USD', currency_evidence=native)
    args['reference']['previous_close'] = None
    for bar in args['bars']:
        bar['sdk_evidence'] = dict(provider_symbol='TEST.US', adjustment='NoAdjust',
                                   interface='QuoteContext.candlesticks')
    return args


class TestOnlyTransport:
    def __init__(self, args, clock):
        self.args, self.clock = args, clock
        self.calls = []
        self.contract_id = 'TEST261006C155000.US'

    def event(self, *args):
        self.calls.append('EVENT')
        return {'event_decision': {'decision': 'WARN'}, 'trade_eligible': True}

    def expiries(self, symbol):
        self.calls.append('EXPIRIES')
        return {'provider_status': 'available', 'symbol': symbol, 'expiries': ['2026-10-06']}

    def chain(self, *args):
        self.calls.append('CHAIN')
        return {'provider_status': 'available', 'contracts': [{'call_symbol': self.contract_id, 'strike_price': 155}]}

    def greeks(self, *args):
        self.calls.append('GREEKS')
        return {'items': [{'contract_symbol': self.contract_id, 'delta': .525}]}

    def contract(self, *args, **kwargs):
        self.calls.append('CONTRACT')
        stamp = self.clock().isoformat()
        return dict(contract_id=self.contract_id, underlying='TEST', right='CALL',
            expiry_date='2026-10-06', strike=155, delta=.525, bid=1, ask=1.01, quote_currency='USD',
            snapshot={'bbo_received_at': stamp, 'calc_received_at': stamp})

    def spot(self, symbol):
        return {'last': self.args['bars'][-1]['close'], 'received_at': self.clock().isoformat()}

    def scope_hash(self):
        return self.args['scope_hash']

    def current_trend(self, original, now):
        return current(original, self.args['bars'], now=now)

    def approval(self, *args):
        raise AssertionError('NO_QUALIFIED_APPROVAL_ALLOWED')


def prepare(path, clock=None):
    args = inputs()
    clock = clock or (lambda: args['now'])
    rows = evaluate_comparison_pair(**args)
    store.initialize(path)
    store.persist(rows, path)
    transport = TestOnlyTransport(args, clock)
    events = []
    for _ in range(12):
        job = jobs.claim(path, now=clock())
        if job is None:
            break
        progress, finished, revision = step(job, transport, clock=clock)
        assert jobs.settle(path, job, now=clock(), progress=progress, finished=finished, revision=revision)
        events.append({'phase': progress.get('phase'), 'revision': revision})
        if revision and revision.get('reference_contract'):
            break
    original = next(row for row in rows if row['right'] == 'CALL')
    detail = store.detail(original['evaluation_id'], path)
    assert detail['strategy_comparison']['reference_contract']['contract_id'] == transport.contract_id
    assert detail['strategy_comparison']['reference_eligibility']['qualified_signal'] is False
    return args, detail, events, transport
