from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json

from kquant.options_price_action_source import SourceRequestBudget


def test_calendar_batch_size_does_not_raise_shared_limit(tmp_path):
    from kquant.option_calendar_source import CalendarSourceRunner
    runner = CalendarSourceRunner(tmp_path / 'unused.sqlite3', max_requests=48)
    assert runner.max_requests == 48
    assert runner.shared_source_window_cap == 12
    assert runner.action_batch_size == 3
    assert runner.calendar_reserved_requests == 6


def test_budget_snapshot_distinguishes_local_cap_from_provider_fact(tmp_path):
    budget = SourceRequestBudget(tmp_path / 'budget.json', cap=12,
                                 now=datetime(2026, 10, 12, tzinfo=UTC))
    budget.grant(3)
    state = budget.snapshot()
    assert state['used'] == 3
    assert state['remaining'] == 9
    assert state['pending_reservations'] == 1
    assert state['budget_basis'] == 'LOCAL_SAFETY_LIMIT'
    assert state['provider_limit_verified'] is False


def test_concurrent_instances_cannot_double_spend(tmp_path):
    path = tmp_path / 'budget.json'
    now = datetime(2026, 10, 12, tzinfo=UTC)
    budgets = [SourceRequestBudget(path, cap=12, now=now) for _ in range(12)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        grants = list(pool.map(lambda b: b.grant(3), budgets))
    assert sum(grants) == 12
    assert all(b.remaining == 0 for b in budgets)
    persisted = json.loads(path.read_text())
    assert persisted['used'] == 12
    assert len(persisted['reservations']) == 4


def test_settlement_is_owned_and_once_only(tmp_path):
    path = tmp_path / 'budget.json'
    now = datetime(2026, 10, 12, tzinfo=UTC)
    a = SourceRequestBudget(path, cap=12, now=now)
    b = SourceRequestBudget(path, cap=12, now=now)
    assert a.grant(3) == b.grant(3) == 3
    a.settle(3, 1)
    a.settle(3, 0)
    assert b.remaining == 8
    restarted = SourceRequestBudget(path, cap=12, now=now)
    restarted.settle(3, 0)
    assert restarted.remaining == 8
    b.settle(3, None)
    assert restarted.remaining == 8


def test_old_window_settlement_cannot_refund_new_window(tmp_path):
    path = tmp_path / 'budget.json'
    now = datetime(2026, 10, 12, tzinfo=UTC)
    old = SourceRequestBudget(path, cap=12, now=now)
    assert old.grant(3) == 3
    new = SourceRequestBudget(path, cap=12, now=now + timedelta(seconds=840))
    assert new.grant(5) == 5
    old.settle(3, 0)
    assert new.remaining == 7
