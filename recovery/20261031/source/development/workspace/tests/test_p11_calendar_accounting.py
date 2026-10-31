from datetime import UTC, datetime
from types import SimpleNamespace

from kquant.options_price_action_source import SourceRequestBudget, refresh_calendar_in_budget


def run(tmp_path, response):
    now = datetime(2026, 10, 11, tzinfo=UTC)
    budget = SourceRequestBudget(tmp_path / 'budget.json', cap=12, now=now)
    runner = SimpleNamespace(max_requests=12, refresh=lambda **kwargs: response)
    result = refresh_calendar_in_budget(runner, budget=budget, now=now, cancelled=lambda: False)
    assert runner.max_requests == 12
    return result, budget.value['used']


def test_actual_calendar_counter_is_settled(tmp_path):
    result, used = run(tmp_path, {'calendar_requests': 2})
    assert result['requests'] == used == 2


def test_conflicting_counters_keep_reservation(tmp_path):
    result, used = run(tmp_path, {'calendar_requests': 2, 'requests': 0})
    assert result['status'] == 'SOURCE_REQUEST_COUNTER_CONFLICT'
    assert used == 6


def test_unknown_cost_keeps_reservation(tmp_path):
    result, used = run(tmp_path, {})
    assert result['requests'] is None
    assert used == 6
