from copy import deepcopy
from datetime import date, timedelta
import json

import pytest

import first_hour
from kquant import options_opening_trend_coverage as coverage
from kquant import options_opening_trend_projection as projection


def fixture(momentum=True):
    opening, _ = first_hour.session_bounds_utc(date(2026, 10, 22))
    policy = first_hour.policies()['S0']
    if not momentum:
        policy = {k: v for k, v in policy.items() if k != 'checkpoint_minutes'}
    registered = [dict(symbol='TEST'+str(i), identity_status='verified' if i < 9 else 'UNKNOWN')
                  for i in range(10)]
    factors = [None, {}, dict(day_open=100, momentum=.1, close_position=.8, price=101,
        momentum_threshold=.01, close_position_threshold=.7, prior_boundary=100,
        reference={}, previous_close=99,
        checks=dict(momentum=True, close_position=True, prior_breakout=False, daily_direction=True),
        auxiliary={'role':'AUXILIARY_ONLY'})]
    partial = deepcopy(factors[-1])
    partial.update(previous_close=None, state='PARTIAL_PRICE_COMPONENTS')
    partial['checks']['daily_direction'] = None
    factors.extend([partial, {**factors[-1], 'momentum':float('nan')},
                    dict(opening_high=110, opening_low=90, opening_width=20, day_open=100,
                         previous_close=99, vwap=101, price=102, trend_bar={}, reference={})])
    records = []
    for point in range(1, 12):
        end = opening+timedelta(minutes=5*point)
        for i, instrument in enumerate(registered[:-1]):
            for right in ('CALL','PUT'):
                for revision in range(2):
                    stamp = end+timedelta(seconds=revision*305)
                    records.append(dict(evaluation_id=str(len(records)), policy_hash=policy['policy_hash'],
                        policy_id=policy['policy_id'], session='2026-10-22', symbol=instrument['symbol'],
                        right=right, scope_hash='TEST_ONLY', calculation_bar_end=end.isoformat(),
                        evaluated_at=stamp.isoformat(), computed_at=stamp.isoformat(),
                        input_received_at=(stamp-timedelta(seconds=1)).isoformat(),
                        state=('NUMERIC_PASS','NO_TRIGGER','EXPIRED','INCOMPLETE')[i%4],
                        factor_evidence=deepcopy(factors[(i+revision)%len(factors)]), reasons=['TEST_ONLY']))
    return opening, registered, policy, records


@pytest.mark.parametrize('momentum', [True, False])
@pytest.mark.parametrize('elapsed', [0, 5, 10, 55, 60, 70])
def test_identical_reconciliation_across_time_and_policy(momentum, elapsed):
    opening, registered, policy, records = fixture(momentum)
    prepared = [coverage.PreparedCoverageRow(row) for row in records]
    for observer in (None, opening+timedelta(minutes=7)):
        args = dict(registered=registered, now=opening+timedelta(minutes=elapsed, seconds=2),
                    policy=policy, scope_hash='TEST_ONLY', observer_started_at=observer)
        expected = coverage.reconcile(records=records, **args)
        actual = coverage.reconcile(records=prepared, **args)
        assert json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)


def test_projection_watermark_revision_and_reset_are_unchanged(monkeypatch):
    opening, registered, policy, records = fixture()
    records = records[:4]
    actual, original = projection.ProjectionCache(), projection.parent.ProjectionCache()
    args = dict(registered=registered, now=opening+timedelta(minutes=7), policy=policy, scope_hash='TEST_ONLY')
    deltas = [
        dict(identity=['store',1], after=0, source_count=4, source_last=4, rows=list(enumerate(records[:2],1))),
        dict(identity=['store',1], after=2, source_count=4, source_last=4, rows=list(enumerate(records[2:],3))),
        dict(identity=['store',1], after=4, source_count=4, source_last=4, rows=[]),
        dict(identity=['store',1], after=3, source_count=4, source_last=4, rows=[]),
        dict(identity=['store',2], after=0, source_count=1, source_last=1, rows=[(1,records[0])]),
        dict(identity=['store',2], after=1, source_count=0, source_last=0, rows=[]),
    ]
    for delta in deltas:
        assert actual.apply(delta, **args) == original.apply(delta, **args)
        assert actual.after == original.after
        assert actual.identity == original.identity
        assert actual.rows == original.rows


def test_unchanged_projection_does_not_regrade_or_hide_changed_input(monkeypatch):
    opening, registered, policy, records = fixture()
    row = records[0]
    row['factor_evidence'] = deepcopy(records[8]['factor_evidence'])
    actual = projection.ProjectionCache()
    args = dict(registered=registered, now=opening+timedelta(minutes=7), policy=policy, scope_hash='TEST_ONLY')
    calls = []
    grade = coverage._factor_grade
    def observed(value):
        calls.append(value['evaluation_id'])
        return grade(value)
    monkeypatch.setattr(coverage, '_factor_grade', observed)
    actual.apply(dict(identity=['s'], after=0, source_count=1, source_last=1, rows=[(1,row)]), **args)
    count = len(calls)
    assert count > 0
    for minute in (8, 9, 10, 60):
        args['now'] = opening+timedelta(minutes=minute)
        actual.apply(dict(identity=['s'], after=1, source_count=1, source_last=1, rows=[]), **args)
    assert len(calls) == count
    with pytest.raises(TypeError):
        actual.rows[1]['state'] = 'NUMERIC_PASS'
    row['state'] = 'INCOMPLETE'
    assert actual.rows[1]['state'] != row['state']
    revised = {**row, 'evaluation_id':'new', 'evaluated_at':(opening+timedelta(minutes=6)).isoformat()}
    actual.apply(dict(identity=['s'], after=1, source_count=2, source_last=2, rows=[(2,revised)]), **args)
    assert len(calls) > count
    assert actual.rows[2]['state'] == 'INCOMPLETE'
