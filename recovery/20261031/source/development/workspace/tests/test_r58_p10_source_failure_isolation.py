"""TEST_ONLY source-boundary tests, not recovered Supervisor/SDK acceptance."""
import ast
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kquant import options_price_action_source as sources


NOW = datetime(2026, 10, 6, 12, 40, tzinfo=UTC)


def test_calendar_failure_does_not_stop_next_actual_persistent_first_coverage(tmp_path):
    requests = []
    class Transport:
        def corporate_actions(self, symbol, *, start_date, end_date):
            requests.append(symbol)
            return {"data": {"items": []}}
    def calendar_failure(**kwargs):
        raise RuntimeError("CALENDAR_CREDENTIALS_UNAVAILABLE")
    runner = SimpleNamespace(store=tmp_path / "sources", max_requests=20,
                             _context=lambda: Transport(), refresh=calendar_failure)
    scope = [{"symbol": f"TEST{index:03}", "identity_status": "verified"} for index in range(100)]
    scope += [{"symbol": f"UNKNOWN{index:02}", "identity_status": "identity_unconfirmed"} for index in range(11)]
    path = runner.store / "shared-source-budget.json"
    budget = sources.SourceRequestBudget(path, cap=20, now=NOW)
    first_grant = budget.grant(3, event_reserve=6)
    first = sources.refresh(runner, now=NOW, clock=lambda: NOW, root=tmp_path,
                            scope=scope, reviews={}, batch_size=first_grant)
    budget.settle(first_grant, first["requests"])
    failed = sources.refresh_calendar_in_budget(runner, budget=budget, now=NOW, cancelled=lambda: False)
    assert failed["status"] == "SOURCE_REQUEST_FAILED" and failed["requests"] is None
    assert runner.max_requests == 20 and budget.value["used"] == 9
    restarted = sources.SourceRequestBudget(path, cap=20, now=NOW + timedelta(seconds=5))
    next_grant = restarted.grant(3)
    second = sources.refresh(runner, now=NOW + timedelta(seconds=5),
                             clock=lambda: NOW + timedelta(seconds=5), root=tmp_path,
                             scope=scope, reviews={}, batch_size=next_grant)
    restarted.settle(next_grant, second["requests"])
    assert len(requests) == len(set(requests)) == 6
    assert second["observed_symbols"] == 6 and second["first_coverage_remaining"] == 94
    assert not second["trade_eligible"] and restarted.value["used"] == 12
    index = json.loads((runner.store / "price-actions/index.json").read_text())
    assert len(index["records"]) == 100
    assert all(row["attempts"] == 1 for row in index["records"].values() if row.get("received_at"))
    (tmp_path / "TEST_ONLY-source-failure-trace.json").write_text(json.dumps({
        "test_only": True, "actual_sdk": False, "first_batch": first,
        "calendar_failure": failed, "after_restart": second, "requested_symbols": requests,
        "persisted_budget": restarted.value, "first_coverage_remaining": 94,
        "complete_supervisor_executed": False}), encoding="utf-8")


@pytest.mark.parametrize("native_count", [0, 3, None])
def test_calendar_budget_counts_restore_and_unknown_reservation(tmp_path, native_count):
    runner = SimpleNamespace(max_requests=20)
    observed_caps = []
    def refresh(**kwargs):
        observed_caps.append(runner.max_requests)
        return {"status": "TEST_ONLY_SOURCE_REFRESH", "requests": native_count}
    runner.refresh = refresh
    budget = sources.SourceRequestBudget(tmp_path / "budget.json", cap=20, now=NOW)
    result = sources.refresh_calendar_in_budget(runner, budget=budget, now=NOW, cancelled=lambda: False)
    assert result["status"] == "TEST_ONLY_SOURCE_REFRESH" and observed_caps == [6]
    assert runner.max_requests == 20
    assert budget.value["used"] == (6 if native_count is None else native_count)


def test_unknown_cap_and_cancel_do_not_request_or_reserve(tmp_path):
    def unexpected(**kwargs):
        pytest.fail("source called without capacity/after cancellation")
    runner = SimpleNamespace(max_requests=None, refresh=unexpected)
    budget = sources.SourceRequestBudget(tmp_path / "unknown.json", cap=None, now=NOW)
    assert sources.refresh_calendar_in_budget(runner, budget=budget, now=NOW, cancelled=lambda: False)["status"] == "WAIT_SHARED_SOURCE_BUDGET"
    assert sources.refresh_calendar_in_budget(runner, budget=budget, now=NOW, cancelled=lambda: True)["status"] == "CANCELLED_BEFORE_REQUEST"
    assert budget.value["used"] == 0


def test_overspent_reservation_pauses_shared_window_across_restart(tmp_path):
    runner = SimpleNamespace(max_requests=20, refresh=lambda **kwargs: {"requests": 7})
    path = tmp_path / "budget.json"
    budget = sources.SourceRequestBudget(path, cap=20, now=NOW)
    result = sources.refresh_calendar_in_budget(runner, budget=budget, now=NOW, cancelled=lambda: False)
    assert result["status"] == "SOURCE_REQUEST_CAP_VIOLATION" and budget.value["used"] == 7
    assert runner.max_requests == 20 and budget.remaining == 0 and budget.grant(3) == 0
    restarted = sources.SourceRequestBudget(path, cap=20, now=NOW + timedelta(seconds=5))
    assert restarted.grant(3) == 0
    renewed = sources.SourceRequestBudget(path, cap=20, now=NOW + timedelta(seconds=840))
    assert renewed.grant(3) == 3
    (tmp_path / "TEST_ONLY-source-overrun-trace.json").write_text(json.dumps({
        "test_only": True, "source_result": result, "at_violation": budget.value,
        "after_restart": restarted.value, "original_window_renewed": renewed.value,
        "production_cap_changed": False}), encoding="utf-8")


def test_supervisor_wires_actual_helper_and_no_long_global_failure_wait():
    # Supplemental wiring assertion only; missing imports prevent full topology.
    path = Path(sources.__file__).with_name("options_radar_supervisor.py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_run_calendar_sources")
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "refresh_calendar_in_budget" for n in ast.walk(method))
    waits = [n.args[0].value for n in ast.walk(method) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "wait"
             and n.args and isinstance(n.args[0], ast.Constant)]
    assert 5 in waits and 900 not in waits and 3600 not in waits
