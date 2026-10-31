"""TEST_ONLY controlled-time capacity; never requests the actual provider."""
from collections import Counter
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace

import pytest

from kquant import options_price_action_source as actions
from test_r58_p10_safe_closeout import action_method


@pytest.mark.parametrize('cap', [12, 240])
def test_three_ttl_cycles_through_real_scheduler_and_fact_producer(tmp_path, cap):
    start = datetime(2026, 10, 12, 12, 30, tzinfo=UTC)
    current = [start]
    calls = Counter()
    method = action_method(tmp_path, start)
    scope = [{'symbol': f'S{i:03}', 'identity_status': 'verified'} for i in range(100)]
    scope += [{'symbol': f'X{i:02}', 'identity_status': 'unknown'} for i in range(11)]
    # Deliberately repeat directions/groups; only one security request may issue.
    scope += scope[:100]

    class Transport:
        def corporate_actions(self, symbol, *, start_date, end_date):
            assert start_date.isoformat() == '2026-10-09'
            assert end_date.isoformat() == '2026-10-12'
            calls[symbol] += 1
            if symbol == 'S000.US' and calls[symbol] == 1:
                raise TimeoutError('TEST_ONLY transient failure')
            return {'data': {'items': [], 'total_count': 0, 'has_more': False}}

    runner = SimpleNamespace(store=tmp_path / 'calendar', _context=lambda: transport)
    transport = Transport()
    budget_path = tmp_path / 'budget.json'
    samples, calendar_requests, max_used = [], 0, 0
    for second in range(0, 2701, 5):
        current[0] = start + timedelta(seconds=second)
        # New objects simulate scheduler reloads; leases/budget live on disk.
        budget = actions.SourceRequestBudget(budget_path, cap=cap, now=current[0])
        calendar_due = second % 840 == 0
        reserved = budget.grant(3, event_reserve=6 if calendar_due else 0)
        if reserved:
            result = actions.refresh(runner, now=current[0], clock=lambda: current[0],
                batch_size=reserved, scope=scope, reviews={'company_action_coverage_method': method}, root=tmp_path)
            budget.settle(reserved, result['requests'])
        if calendar_due:
            reserved_calendar = budget.grant_calendar_batch()
            calendar_requests += reserved_calendar
            budget.settle(reserved_calendar, reserved_calendar)
        state = budget.snapshot()
        max_used = max(max_used, state['used'])
        assert 0 <= state['used'] <= cap
        if second % 30 == 0:
            # Read the published facts, not the adapter's optimistic return.
            fresh = actions.load_facts(runner.store, now=current[0], root=tmp_path)
            samples.append({'second': second, 'fresh': len(fresh)})
            assert all(symbol.startswith('S') for symbol in fresh)
    assert len(calls) <= 100 and not any(symbol.startswith('X') for symbol in calls)
    report = {'test_only': True, 'elapsed_simulated_seconds': 2700,
              'cap': cap, 'window_seconds': 840, 'calendar_requests': calendar_requests,
              'actual_action_requests': sum(calls.values()), 'unique_requested': len(calls),
              'unknown_identity_excluded': 11, 'samples': samples, 'max_window_used': max_used,
              'request_counts': dict(calls)}
    (tmp_path / 'capacity-report.json').write_text(json.dumps(report, indent=2))
    if cap == 240:
        assert len(calls) == 100
        assert min(row['fresh'] for row in samples if row['second'] >= 600) == 100
        assert min(calls.values()) >= 3
    else:
        assert max(row['fresh'] for row in samples) < 100
        assert len(calls) < 100
