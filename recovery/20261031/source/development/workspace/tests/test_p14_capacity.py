"""TEST_ONLY P14 comparison through original runner, loop, budget and producer.

Only input/time boundaries and an audit tap are substituted. Fictional methods
and generated facts stay in isolated test storage; they are not source evidence.
"""
from collections import Counter
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from threading import Event, RLock
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from kquant import option_calendar_source as calendar
from kquant import options_price_action_source as actions
from kquant import options_radar_supervisor as supervisor
from kquant.options_source_call import SourceCallBusy, SourceCallGate, SourceCallTimeout
from test_p13_source_capacity import BASE, fictional_method, synthetic_scope


HORIZON = 2700
CAPS = (12, 120)
SCENARIOS = ("healthy", "transient_failures", "slow_1_5s", "slow_10s",
             "graceful_restart", "lost_reservation_restart")
RESULTS = {}


@pytest.fixture(autouse=True)
def isolated_io(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("P14 TEST_ONLY: network/database access denied")
    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(sqlite3, "connect", denied)
    # commit_action must never follow a caller's production data-root override.
    monkeypatch.delenv("KQUANT_RUNTIME_DATA_ROOT", raising=False)


class Clock:
    def __init__(self):
        self.seconds = 0.0

    def now(self):
        return BASE + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds

    def advance(self, seconds):
        assert seconds >= 0
        self.seconds += seconds


class Transport:
    """One-second start spacing across both request kinds, one active callback.

    Simulated latency is not a wall-clock timeout test. The separate gate test
    below exercises a real blocked thread and the original timeout behavior.
    """
    def __init__(self, clock, scenario):
        self.clock, self.scenario = clock, scenario
        self.calls, self.attempts = [], Counter()
        self.active = self.max_active = 0

    def issue(self, kind, key):
        if self.calls:
            self.clock.advance(max(0, self.calls[-1]["start_seconds"] + 1 - self.clock.seconds))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        assert self.active == 1
        self.attempts[(kind, key)] += 1
        latency = {"slow_1_5s": 1.5, "slow_10s": 10}.get(self.scenario, 0)
        if self.scenario == "lease_overrun" and key == "TEST000.US":
            latency = 65
        row = dict(kind=kind, key=key, start_seconds=self.clock.seconds,
                   attempt=self.attempts[(kind, key)], latency_seconds=latency)
        self.calls.append(row)
        try:
            self.clock.advance(latency)
            failed = (self.scenario == "transient_failures" and kind == "action"
                      and int(key[4:7]) < 10 and row["attempt"] == 1)
            row.update(received_seconds=self.clock.seconds, failed=failed)
            if failed:
                raise TimeoutError("TEST_ONLY deterministic first-attempt failure")
        finally:
            self.active -= 1

    def corporate_actions(self, symbol, *, start_date, end_date):
        assert start_date.isoformat() == "2026-10-12"
        assert end_date.isoformat() == "2026-10-13"
        self.issue("action", symbol)
        return {"data": {"items": [], "total_count": 0, "has_more": False}}

    def request(self, method, path):
        parsed = urlsplit(path)
        query = parse_qs(parsed.query)
        assert method == "get" and parsed.path == "/v1/quote/finance_calendar"
        assert query["markets[]"] == ["US"]
        category, day = query["types[]"][0], query["date"][0]
        assert category in {name.lower() for name in calendar.CATEGORY_NAMES.values()}
        self.issue("calendar", category)
        return {"code": 0, "data": {"date": day, "next_date": "",
                "list": [{"date": day, "count": 0, "infos": []}]}}


def object_metrics(symbol, events, calls):
    history = [row for row in events if row["symbol"] == symbol and row["committed"]]
    successes = [row for row in history if row["valid_until_seconds"] is not None]
    observed = [row for row in calls if row["kind"] == "action" and row["key"] == symbol + ".US"]
    # Published current_fact retains the last good file on transport failure;
    # load_facts instead follows the newest index observation, even a failure.
    published, indexed = [], []
    latest_good = latest_index = None
    cursor = 0
    for second in range(HORIZON + 1):
        while cursor < len(history) and history[cursor]["at_seconds"] <= second:
            latest_index = history[cursor]
            if latest_index["valid_until_seconds"] is not None:
                latest_good = latest_index
            cursor += 1
        def state(row):
            if row is None:
                return "never"
            if row["valid_until_seconds"] is None:
                return "failed_or_unusable"
            return "fresh" if second < row["valid_until_seconds"] else "expired"
        published.append(state(latest_good))
        indexed.append(state(latest_index))
    receipts = [row["at_seconds"] for row in successes]
    first = receipts[0] if receipts else None
    first_second = int(first) + int(first % 1 != 0) if first is not None else HORIZON + 1
    totals = Counter(published[:HORIZON])
    durations = {key: totals[key] for key in ("fresh", "expired", "never", "failed_or_unusable")}
    return dict(symbol=symbol, requests=len(observed), failed_requests=sum(row["failed"] for row in observed),
                committed_successes=len(successes), first_usable_seconds=first,
                successful_receipts_seconds=receipts,
                max_renewal_gap_seconds=max((b - a for a, b in zip(receipts, receipts[1:])), default=None),
                last_valid_until_seconds=successes[-1]["valid_until_seconds"] if successes else None,
                seconds_on_integer_grid=durations,
                uninterrupted_after_first=bool(first is not None and all(
                    value == "fresh" for value in published[first_second:])),
                published=published, indexed=indexed, commits=history)


def summarize(events, calls):
    objects = {f"TEST{i:03d}": object_metrics(f"TEST{i:03d}", events, calls) for i in range(100)}
    census = []
    for second in range(HORIZON + 1):
        published = Counter(row["published"][second] for row in objects.values())
        indexed = Counter(row["indexed"][second] for row in objects.values())
        census.append(dict(at_seconds=second, fresh=published["fresh"], expired=published["expired"],
                           never=published["never"], unusable=published["failed_or_unusable"],
                           index_fresh=indexed["fresh"], index_expired=indexed["expired"],
                           index_never=indexed["never"], index_failed_or_unusable=indexed["failed_or_unusable"]))
    all_fresh = next((row["at_seconds"] for row in census if row["fresh"] == 100), None)
    cycles = []
    for start in (0, 900, 1800):
        rows = census[start:start + 900]
        cycles.append(dict(start_seconds=start, end_exclusive_seconds=start + 900,
                           min_fresh=min(row["fresh"] for row in rows),
                           max_fresh=max(row["fresh"] for row in rows),
                           max_expired=max(row["expired"] for row in rows),
                           max_never=max(row["never"] for row in rows),
                           end=census[start + 900],
                           per_object={symbol: dict(Counter(row["published"][start:start + 900]))
                                       for symbol, row in objects.items()}))
    for row in objects.values():
        row.pop("published")
        row.pop("indexed")
    return dict(objects=objects, cycles=cycles,
                first_all_100_fresh_seconds=all_fresh,
                uninterrupted_all_100_after_warmup=bool(all_fresh is not None and all(
                    row["fresh"] == 100 for row in census[all_fresh:])),
                samples=[census[s] for s in (0, 30, 300, 600, 899, 900, 905, 1799, 1800, 2699, 2700)],
                final=census[-1])


def run_comparison(root, monkeypatch, *, cap, scenario):
    from kquant import option_official_source as official
    from kquant import options_opening_trend_event_auto as event_auto
    from kquant import options_opening_trend_reference as reference
    from kquant import options_opening_trend_runtime as runtime
    from kquant import options_two_hour_data as data

    clock, events, ticks, restarts = Clock(), [], [], []
    ledger = {}
    transport = Transport(clock, scenario)
    method = fictional_method(root)
    scope = synthetic_scope(100, duplicates=True, excluded=11)
    original_commit = actions.commit_action
    original_grant = actions.SourceRequestBudget.grant
    original_settle = actions.SourceRequestBudget.settle

    def audit_grant(budget, requested, *, event_reserve=0):
        allowed = original_grant(budget, requested, event_reserve=event_reserve)
        if allowed:
            key, _, opened = budget._pending[-1]
            ledger[key] = dict(opened_at=opened, reserved=allowed, cost=allowed,
                               status="PENDING", actual=None, event_reserve=event_reserve,
                               calls_before=len(transport.calls), transport_started=0)
        return allowed

    def audit_settle(budget, reserved, actual):
        entry = next((item for item in budget._pending if item[1] == reserved), None)
        original_settle(budget, reserved, actual)
        if entry:
            row = ledger[entry[0]]
            row.update(actual=actual, transport_started=len(transport.calls) - row["calls_before"])
            if type(actual) is int and actual >= 0:
                row.update(status="SETTLED", cost=actual)
            else:
                row["status"] = "UNKNOWN_RETAINS_RESERVATION"

    def audit_commit(index, symbol, claim, observation, path, review_root, target, count, now):
        committed = original_commit(index, symbol, claim, observation, path, review_root, target, count, now)
        fact = observation.get("coverage_fact")
        if fact:
            assert fact["owner_approval"] is False
            assert fact["complete"] is True
            assert actions.valid_fact(fact, symbol=symbol, previous="2026-10-12", session="2026-10-13",
                                      now=now, root=root)
            assert actions.valid_fact(fact, symbol=symbol, previous="2026-10-12", session="2026-10-13",
                                      now=actions.common.timestamp(fact["valid_until"]), root=root) is None
        events.append(dict(symbol=symbol, at_seconds=(now - BASE).total_seconds(),
                           committed=committed, requests=count, status=observation["status"],
                           valid_until_seconds=(actions.common.timestamp(fact["valid_until"]) - BASE).total_seconds()
                               if fact else None,
                           fact_hash=fact["fact_hash"] if fact else None))
        return committed

    class DateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock.now()
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    monkeypatch.setattr(actions, "commit_action", audit_commit)
    monkeypatch.setattr(actions.SourceRequestBudget, "grant", audit_grant)
    monkeypatch.setattr(actions.SourceRequestBudget, "settle", audit_settle)
    monkeypatch.setattr(actions, "monotonic", clock.monotonic)
    monkeypatch.setattr(supervisor, "datetime", DateTime)
    monkeypatch.setattr(supervisor, "monotonic", clock.monotonic)
    monkeypatch.setattr(calendar, "datetime", DateTime)
    monkeypatch.setattr(calendar, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(data, "universe", lambda path: {"items": scope, "scope_hash": "P14_TEST_ONLY"})
    monkeypatch.setattr(reference, "ROOT", root)
    monkeypatch.setattr(reference, "load_reviews", lambda: {"company_action_coverage_method": method})
    monkeypatch.setattr(supervisor, "market_schedule", lambda day, path: {
        "is_trading_day": True, "regular_close_utc": "2026-10-13T20:00:00+00:00"})
    monkeypatch.setattr(official, "refresh_active_reviews", lambda *a, **k: {"status": "NOT_EXERCISED"})
    monkeypatch.setattr(event_auto, "refresh_bound_sources", lambda *a, **k: {"status": "NOT_EXERCISED"})
    with runtime._source_listeners_lock:
        assert not list(runtime._source_listeners), "P14 must run isolated from live listeners"
    sdk = ModuleType("longbridge.openapi")
    sdk.CalendarCategory = SimpleNamespace(**{name: name for name in calendar.CATEGORY_NAMES.values()})
    monkeypatch.setitem(sys.modules, "longbridge.openapi", sdk)
    budget_path = root / "sources/shared-source-budget.json"
    index_path = root / "sources/price-actions/index.json"
    restart_at = {"graceful_restart": 430, "lost_reservation_restart": 10}.get(scenario)
    restarted = False
    unknown_reserved = 0

    while clock.seconds < HORIZON:
        runner = calendar.CalendarSourceRunner(root / "TEST_ONLY-NO-DATABASE", store=root / "sources", context=transport)
        assert runner.shared_source_window_cap == 12
        runner.shared_source_window_cap = cap  # Instance-local test proposal, not a production change.
        loop = supervisor.OptionRadarSupervisor.__new__(supervisor.OptionRadarSupervisor)
        loop.db_path, loop._calendar_runner = runner.db_path, runner
        loop._status, loop._lock = {}, RLock()
        loop.one_minute_shadow_enabled = True
        restart_pending = False

        class Stop:
            def is_set(self):
                next_start = max(clock.seconds, transport.calls[-1]["start_seconds"] + 1) if transport.calls else clock.seconds
                return next_start >= HORIZON or restart_pending

            def wait(self, delay):
                nonlocal restart_pending
                ticks.append(dict(at_seconds=clock.seconds, **loop._status["source_request_budget"],
                                  action_status=loop._status.get("price_action_sources", {}).get("status"),
                                  action_error=loop._status.get("price_action_sources", {}).get("error_type"),
                                  calendar_status=loop._status.get("event_sources", {}).get("status"),
                                  calendar_error=loop._status.get("event_sources", {}).get("error_type")))
                clock.advance(min(delay, max(0, HORIZON - clock.seconds)))
                if restart_at is not None and not restarted and clock.seconds >= restart_at:
                    restart_pending = True
                return self.is_set()

        loop._stop = Stop()
        try:
            loop._run_calendar_sources()
        finally:
            assert runner.source_call_gate.close()["in_flight"] is False
        if restart_pending:
            lost = actions.SourceRequestBudget(budget_path, cap=cap, now=clock.now())
            charged = lost.grant(3) if scenario == "lost_reservation_restart" else 0
            unknown_reserved += charged
            before = lost.snapshot()
            budget_hash, index_hash = sha256(budget_path.read_bytes()).hexdigest(), sha256(index_path.read_bytes()).hexdigest()
            recovered = actions.SourceRequestBudget(budget_path, cap=cap, now=clock.now())
            after = recovered.snapshot()
            assert before == after
            assert sha256(index_path.read_bytes()).hexdigest() == index_hash
            assert sha256(budget_path.read_bytes()).hexdigest() == budget_hash
            restarts.append(dict(at_seconds=clock.seconds, before=before, after=after,
                                 unknown_charge=charged, index_sha256=index_hash, budget_sha256=budget_hash))
            restarted = True
        else:
            clock.advance(max(0, HORIZON - clock.seconds))
            break

    assert all(row["local_cap"] == cap and row["window_seconds"] == 840 and 0 <= row["used"] <= cap
               and row["provider_limit_verified"] is False for row in ticks)
    assert transport.max_active == 1
    assert all(b["start_seconds"] - a["start_seconds"] >= 1
               for a, b in zip(transport.calls, transport.calls[1:]))
    assert not list(root.rglob("*.db")) and not list(root.rglob("*.sqlite*"))
    assert all(call["start_seconds"] < HORIZON for call in transport.calls)
    windows = {}
    for tick in ticks:
        key = tick["opened_at"]
        row = windows.setdefault(key, dict(open_seconds=(actions.common.timestamp(key) - BASE).total_seconds(),
                                          used_max=0, used_last=0, pending_max=0, action_requests=0, calendar_requests=0))
        row["used_max"] = max(row["used_max"], tick["used"])
        row["used_last"] = tick["used"]
        row["pending_max"] = max(row["pending_max"], tick["pending_reservations"])
    # Reservations charge the window containing the tick start, not receipt time.
    # All callbacks here finish within their tick; lease-overrun is separately reported.
    openings = sorted(windows.values(), key=lambda row: row["open_seconds"])
    for call in transport.calls:
        window = next(row for row in reversed(openings) if row["open_seconds"] <= call["start_seconds"])
        window[call["kind"] + "_requests"] += 1
    accounting = sum(row["used_last"] for row in windows.values())
    assert accounting == sum(row["cost"] for row in ledger.values())
    for opened, window in windows.items():
        window["ledger_cost"] = sum(row["cost"] for row in ledger.values() if row["opened_at"] == opened)
        assert window["used_last"] == window["ledger_cost"]
    entries = list(ledger.values())
    for position, row in enumerate(entries):
        if row["status"] == "PENDING":
            following = entries[position + 1]["calls_before"] if position + 1 < len(entries) else len(transport.calls)
            row["transport_started"] = following - row["calls_before"]
    assert sum(row["transport_started"] for row in entries) == len(transport.calls)
    reported_surplus = sum(row["cost"] - row["transport_started"] for row in entries if row["status"] != "PENDING")
    unknown_margin = sum(row["cost"] - row["transport_started"] for row in entries if row["status"] == "PENDING")
    assert accounting == len(transport.calls) + unknown_margin + reported_surplus
    assert unknown_margin >= unknown_reserved and reported_surplus >= 0
    result = dict(classification="TEST_ONLY_HYPOTHETICAL_INPUT_NOT_PROVIDER_OR_OWNER_EVIDENCE",
                  cap=cap, window_seconds=840, concurrent_requests=1, minimum_start_interval_seconds=1,
                  pacing_location="TEST_TRANSPORT_BOUNDARY_NOT_PRODUCTION_GATE", calendar_reserve=6,
                  scenario=scenario, scope_objects=100, duplicated_scope_rows=len(scope), identity_excluded=11,
                  horizon_seconds=HORIZON, simulation_finished_seconds=clock.seconds,
                  provider_requests=0, sdk_constructed=False, databases_opened=0, production_approval=False,
                  whole_tick_mocked=False, action_requests=sum(row["kind"] == "action" for row in transport.calls),
                  calendar_requests=sum(row["kind"] == "calendar" for row in transport.calls),
                  failures=sum(row["failed"] for row in transport.calls),
                  failed_commits=sum(not row["committed"] for row in events), unknown_reservation_charge=unknown_reserved,
                  budget_accounted_requests=accounting, windows=windows, restarts=restarts,
                  reservation_ledger=entries, scheduler_counter_surplus=reported_surplus,
                  unknown_pending_reservation_cost=sum(row["cost"] for row in entries if row["status"] == "PENDING"),
                  unknown_pending_charge_margin=unknown_margin,
                  suppressed_refresh_errors=[row for row in ticks if row["action_error"] or row["calendar_error"]],
                  requests=transport.calls, commit_audit=events, **summarize(events, transport.calls))
    final_now = BASE + timedelta(seconds=HORIZON)
    indexed = actions.load_facts(runner.store, now=final_now, root=root)
    published = {symbol: actions.current_fact(root, symbol=symbol, session="2026-10-13", previous="2026-10-12",
                                             now=final_now, method=method) for symbol in result["objects"]}
    assert len(indexed) == result["final"]["index_fresh"]
    assert sum(value is not None for value in published.values()) == result["final"]["fresh"]
    result["final_actual_revalidation"] = dict(load_facts=len(indexed), current_fact=sum(
        value is not None for value in published.values()))
    return result


@pytest.mark.parametrize("scenario", SCENARIOS)
@pytest.mark.parametrize("cap", CAPS)
def test_actual_scheduler_comparison(tmp_path, monkeypatch, cap, scenario):
    result = run_comparison(tmp_path, monkeypatch, cap=cap, scenario=scenario)
    RESULTS[f"{scenario}_{cap}"] = result
    assert len(result["objects"]) == 100 and len(result["cycles"]) == 3
    assert sum(row["requests"] for row in result["objects"].values()) == result["action_requests"]
    if cap == 12:
        assert result["first_all_100_fresh_seconds"] is None
    elif scenario in ("healthy", "slow_1_5s", "graceful_restart", "lost_reservation_restart"):
        assert result["uninterrupted_all_100_after_warmup"]
        assert result["final"]["fresh"] == 100
        assert all(row["committed_successes"] >= 3 for row in result["objects"].values())
    elif scenario == "slow_10s":
        assert not result["uninterrupted_all_100_after_warmup"]
    if scenario == "transient_failures":
        assert result["failures"] > 0
    if "restart" in scenario:
        assert len(result["restarts"]) == 1


@pytest.mark.parametrize("cap", CAPS)
def test_lease_overrun_cannot_publish_late_facts(tmp_path, monkeypatch, cap):
    result = run_comparison(tmp_path, monkeypatch, cap=cap, scenario="lease_overrun")
    RESULTS[f"lease_overrun_{cap}"] = result
    assert result["failed_commits"] > 0
    assert result["objects"]["TEST000"]["committed_successes"] == 0
    assert result["objects"]["TEST000"]["last_valid_until_seconds"] is None


@pytest.mark.parametrize("cap", CAPS)
def test_real_gate_timeout_busy_and_restart_charge(tmp_path, cap):
    release, entered = Event(), Event()
    gate = SourceCallGate(timeout=.02)
    budget = actions.SourceRequestBudget(tmp_path / "budget.json", cap=cap, now=BASE)
    calls = []

    def stuck():
        calls.append("TEST_ONLY")
        entered.set()
        assert release.wait(2)
        return None

    reserved = budget.grant(1, event_reserve=6)
    try:
        with pytest.raises(SourceCallTimeout):
            gate.call(stuck)
        assert entered.is_set() and gate.snapshot()["in_flight"]
        with pytest.raises(SourceCallBusy):
            gate.call(lambda: calls.append("MUST_NOT_START"))
        # Lost settlement retains its reservation; a new budget cannot refund it.
        recovered = actions.SourceRequestBudget(budget.path, cap=cap, now=BASE + timedelta(seconds=1))
        assert recovered.snapshot()["used"] == reserved == 1
        assert recovered.snapshot()["pending_reservations"] == 1
        RESULTS[f"real_gate_timeout_{cap}"] = dict(requests=len(calls), used=1, pending=1,
                                                   busy_extra_requests=0, cancellation_proven=False)
    finally:
        release.set()
        assert gate.close()["in_flight"] is False
    assert calls == ["TEST_ONLY"]


def test_ttl_boundary_and_comparative_evidence():
    assert set(f"{scenario}_{cap}" for scenario in SCENARIOS for cap in CAPS) <= RESULTS.keys()
    assert RESULTS["healthy_120"]["final"]["fresh"] > RESULTS["healthy_12"]["final"]["fresh"]
    assert all(cycle["min_fresh"] == 100 for cycle in RESULTS["healthy_120"]["cycles"][1:])
    for cap in CAPS:
        for row in RESULTS[f"healthy_{cap}"]["commit_audit"]:
            if row["committed"] and row["valid_until_seconds"] is not None:
                assert row["valid_until_seconds"] - row["at_seconds"] == 900


def test_zz_write_evidence():
    output = os.environ.get("P14_CAPACITY_TEST_RESULTS")
    if output:
        path = Path(output).resolve()
        assert path.parent == Path(r"C:\Users\Administrator\Desktop\Codex coding").resolve()
        assert path.name.startswith("P14_CAPACITY_") and path.suffix == ".json"
        path.write_text(json.dumps(dict(schema="P14_CAPACITY_TEST_ONLY_V1", results=RESULTS), indent=2), encoding="utf-8")
