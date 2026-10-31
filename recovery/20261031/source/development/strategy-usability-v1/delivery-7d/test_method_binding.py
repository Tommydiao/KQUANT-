"""Actual method consumer with genuine choice and explicitly synthetic future inputs."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from contextlib import closing

import pytest

from kquant import options_minute_decisions as decisions
from kquant import options_one_minute as common
from kquant import options_opening_momentum_journal as journal
from kquant import options_opening_trend_store as store
from kquant import options_intraday_comparison as comparison

HERE = Path(__file__).parent
PATCH = HERE / 'patches'
BASE = HERE.parents[1] / 'workspace'
CONFIG = 'config/review_acceptances/options_opening_trend_reference_sources.json'


def proof():
    return json.loads((PATCH / CONFIG).read_text())['canonical_resolution_method']


def synthetic_inputs():
    opening = datetime(2026, 10, 19, 13, 30, tzinfo=timezone.utc)
    rows = []
    for index in range(5):
        start = opening + timedelta(minutes=index)
        end = start + timedelta(minutes=1)
        request = end + timedelta(milliseconds=100)
        native = dict(interface='QuoteContext.candlesticks', adjustment='NoAdjust',
            provider_symbol='TEST_ONLY.US', request_started_at=request.isoformat(),
            clock_evidence=dict(state='VERIFIED_BOUND', uncertainty_ms=50,
                checked_at=(end - timedelta(seconds=1)).isoformat(), source_hash='TEST_ONLY_clock'))
        rows.append(dict(symbol='TEST_ONLY', interval='1m', closed=True,
            open_at=start.isoformat(), available_at=end.isoformat(),
            received_at=(end + timedelta(milliseconds=300)).isoformat(),
            request_started_at=request.isoformat(), open=100+index, high=101+index,
            low=99.9+index, close=100.9+index, sdk_evidence=native, test_only=True))
    first = rows[0]
    end = common.timestamp(first['available_at'])
    push = {**deepcopy(first), 'low': 99.6, 'close': 100.3,
        'received_at': (end + timedelta(milliseconds=50)).isoformat(),
        'sdk_evidence': {'interface': 'QuoteContext.set_on_candlestick'}}
    early = {**deepcopy(push), 'received_at': (end - timedelta(milliseconds=150)).isoformat(), 'low': 99}
    native = dict(symbol='TEST_ONLY', provider_symbol='TEST_ONLY.US', currency='USD',
        source='LONGBRIDGE_SECURITY_STATIC_INFO', received_at=opening.isoformat(), test_only=True)
    native['source_hash'] = common.digest(native)
    return dict(symbol='TEST_ONLY', opening=opening, closing=opening + timedelta(hours=6, minutes=30),
        checkpoint=opening + timedelta(minutes=5), now=opening + timedelta(minutes=5, seconds=1),
        bars=[early, push, *rows], history={}, scope_hash='TEST_ONLY_scope',
        reference=dict(symbol='TEST_ONLY', session='2026-10-19', previous_close=None,
            raw_quote=dict(symbol='TEST_ONLY', currency='USD', currency_evidence=native),
            reference_blockers=['PRICE_REFERENCE_UNVERIFIED']))


def test_pending_binding_only_changes_canonical_field_and_binds_actual_reply():
    parent = json.loads((BASE / CONFIG).read_text(encoding='utf-8-sig'))
    pending = json.loads((PATCH / CONFIG).read_text())
    assert parent['canonical_resolution_method'] is None
    selected = pending.pop('canonical_resolution_method')
    assert pending == {key: value for key, value in parent.items() if key != 'canonical_resolution_method'}
    raw = (PATCH / selected['acceptance_path']).read_bytes()
    receipt = json.loads(raw)
    assert sha256(raw).hexdigest() == selected['acceptance_sha256']
    assert receipt['approved_by'] == 'OWNER' and receipt['status'] == 'APPROVED'
    assert receipt['human_decision_evidence']['source'] == 'DIRECT_USER_REPLY'
    assert 'call_639ba14a627c4da59e9fee8f0e80acc7' in receipt['human_decision_evidence']['reference']
    assert receipt['method_hash'] == common.digest(decisions.LOCAL_METHOD)
    assert not receipt['new_candidate_launch_approval']
    assert not receipt['qualified_signal_approval']


def test_acceptance_has_fixed_effective_boundary_no_retroactive_adoption():
    selected = proof()
    first = datetime(2026, 10, 16, 15, 24, 33, tzinfo=timezone.utc)
    end = datetime(2026, 10, 23, 14, 30, 22, tzinfo=timezone.utc)
    assert decisions._method(selected, now=first-timedelta(microseconds=1), root=PATCH) is None
    assert decisions._method(selected, now=first, root=PATCH) == selected
    assert decisions._method(selected, now=end-timedelta(microseconds=1), root=PATCH) == selected
    assert decisions._method(selected, now=end, root=PATCH) is None


@pytest.mark.parametrize('change', ['hash', 'method', 'status', 'outside_root'])
def test_accepted_choice_cannot_hide_a_changed_contract(change):
    selected = deepcopy(proof())
    if change == 'hash':
        selected['acceptance_sha256'] = '0' * 64
    if change == 'method':
        selected['method']['clock_evidence_max_age_seconds'] = 901
    if change == 'status':
        selected['status'] = 'PROPOSED'
    if change == 'outside_root':
        selected['acceptance_path'] = '../constraint.json'
    assert decisions._method(selected, now=synthetic_inputs()['now'], root=PATCH) is None


def test_real_resolver_pair_and_cas_with_pending_method(tmp_path, monkeypatch):
    args = synthetic_inputs()
    path = tmp_path / 'TEST_ONLY-research.sqlite3'
    store.initialize(path)
    journal.initialize(path)
    monkeypatch.setattr(decisions, 'ROOT', PATCH)
    before = comparison.evaluate_comparison_pair(**args)
    assert all(row['state'] == 'INCOMPLETE' for row in before)
    assert before[0]['strategy_comparison']['s1']['reasons'] == ['SOURCE_CONFLICT']
    key = 'opening_momentum', '2026-10-19', 'TEST_ONLY', 1
    job = 'TEST_ONLY', args['opening'].date(), args['bars'], args['scope_hash'], args['reference']
    old = journal.begin(path, key, job, args['now'])
    selected = decisions.resolve(path, args['bars'], symbol=args['symbol'], session='2026-10-19',
        now=args['now'], proof=proof(), root=PATCH)
    first = next(item for item in selected if item['open_at'] == args['opening'].isoformat())
    assert len(first['observed_raw_ids']) == 3
    assert len(first['eligible_version_ids']) == 2
    assert len(first['rejected_versions']) == 1
    assert first['selected_version_id'] == common.digest(args['bars'][2])
    after = comparison.evaluate_comparison_pair(**args, source_decisions=selected)
    assert after[0]['state'] == 'INCOMPLETE'
    assert 'PRICE_REFERENCE_UNVERIFIED' in after[0]['reasons']
    assert after[0]['strategy_comparison']['s1']['state'] == 'NUMERIC_PASS'
    assert after[1]['strategy_comparison']['s1']['state'] == 'NO_TRIGGER'
    for row in after:
        assert row['strategy_comparison']['cohort'] == 'S1_INTRADAY_ONLY_DATA'
        assert not row['qualified_signal']
        assert not row['strategy_comparison']['s1']['qualified_signal']
    fixed_deadline = after[0]['strategy_comparison']['s1']['deadline_at']
    assert fixed_deadline == '2026-10-19T13:40:00+00:00'
    fingerprint = journal.input_fingerprint(job, selected)
    assert journal.ready(path, key, job, args['now'], fingerprint=fingerprint)
    assert not journal.finish(path, old, rows=after)
    fresh = journal.begin(path, key, job, args['now'], fingerprint=fingerprint)
    assert fresh.generation == old.generation + 1
    assert journal.finish(path, fresh, rows=after)
    assert not journal.ready(path, key, job, args['now'], fingerprint=fingerprint)
    assert decisions.resolve(path, args['bars'], symbol=args['symbol'], session='2026-10-19',
        now=args['now'], proof=proof(), root=PATCH) == []
    later = deepcopy(args['bars'][1])
    later['received_at'] = (args['now'] + timedelta(seconds=1)).isoformat()
    assert decisions.accepted(first, [*args['bars'], later], symbol=args['symbol'], start=args['opening'],
        now=args['now']+timedelta(seconds=2), root=PATCH) is None
    assert decisions.resolve(path, [*args['bars'], later], symbol=args['symbol'], session='2026-10-19',
        now=args['now']+timedelta(seconds=2), proof=proof(), root=PATCH) == []
    revised = comparison.evaluate_comparison_pair(**{**args, 'bars': [*args['bars'], later],
        'now': args['now']+timedelta(seconds=2)}, source_decisions=selected)
    assert revised[0]['strategy_comparison']['s1']['state'] == 'INCOMPLETE'
    assert revised[0]['strategy_comparison']['s1']['deadline_at'] == fixed_deadline


@pytest.mark.parametrize('change', ['clock_missing', 'clock_stale', 'clock_wide', 'request_early', 'wrong_adjustment'])
def test_owner_choice_does_not_prove_synthetic_clock_or_price_facts(tmp_path, change):
    args = synthetic_inputs()
    path = tmp_path / 'TEST_ONLY-research.sqlite3'
    journal.initialize(path)
    pull = args['bars'][2]
    native = pull['sdk_evidence']
    if change == 'clock_missing':
        native.pop('clock_evidence')
    if change == 'clock_stale':
        native['clock_evidence']['checked_at'] = (args['opening']-timedelta(hours=1)).isoformat()
    if change == 'clock_wide':
        native['clock_evidence']['uncertainty_ms'] = 1001
    if change == 'request_early':
        native['request_started_at'] = pull['available_at']
    if change == 'wrong_adjustment':
        native['adjustment'] = 'ForwardAdjust'
    assert decisions.resolve(path, args['bars'][:3], symbol=args['symbol'], session='2026-10-19',
        now=args['now'], proof=proof(), root=PATCH) == []


def test_tied_conflicting_versions_cannot_choose_by_input_order(tmp_path):
    args = synthetic_inputs()
    path = tmp_path/'TEST_ONLY-tie.sqlite3'
    journal.initialize(path)
    pull = args['bars'][2]
    tied = {**deepcopy(pull), 'close': pull['close']-.1}
    assert decisions.resolve(path, [pull, tied], symbol=args['symbol'], session='2026-10-19',
        now=args['now'], proof=proof(), root=PATCH) == []


def test_batch_is_atomic_idempotent_bounded_and_empty_has_no_write(tmp_path, monkeypatch):
    args = synthetic_inputs()
    path = tmp_path/'TEST_ONLY-atomic.sqlite3'
    journal.initialize(path)
    first = dict(session='2026-10-19', symbol='GOOD', open_at=args['opening'].isoformat(),
        known_at=args['now'].isoformat(), test_only=True)
    second = {**first, 'symbol': 'FAIL_TEST_ONLY'}
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TRIGGER reject_test BEFORE INSERT ON two_hour_jobs "
            "WHEN NEW.symbol='FAIL_TEST_ONLY' BEGIN SELECT RAISE(ABORT,'TEST_ONLY_INTERRUPTED'); END")
    with pytest.raises(sqlite3.IntegrityError, match='TEST_ONLY_INTERRUPTED'):
        decisions.append_many(path, [first, second])
    with closing(sqlite3.connect(path)) as db, db:
        assert db.execute('SELECT count(*) FROM two_hour_jobs').fetchone()[0] == 0
        db.execute('DROP TRIGGER reject_test')
    batch = decisions.append_many(path, [first, second])
    assert decisions.append_many(path, [first, second]) == batch
    assert decisions.append(path, first) == batch[0]
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT count(*) FROM two_hour_jobs').fetchone()[0] == 2
    with pytest.raises(ValueError, match='WRITE_BOUND_EXCEEDED'):
        decisions.append_many(path, [first]*(decisions.WRITE_BOUND+1))
    monkeypatch.setattr(decisions, 'connect_store', lambda *a, **kw: pytest.fail('EMPTY_WRITE_ATTEMPT'))
    assert decisions.append_many(path, []) == []
