"""TEST_ONLY capacity proof. No provider, credentials, DB, or production writes.

The successful transport and reviewed statement are deliberately fictional.
They isolate local capacity; they do not establish the installed SDK's capability
or approve a provider coverage method. The actual source loop is not mocked.
"""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import ast
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
from threading import RLock
from types import ModuleType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from kquant import option_calendar_source as calendar
from kquant import options_price_action_source as actions
from kquant import options_radar_supervisor as supervisor


BASE = datetime(2026, 10, 13, 12, 30, tzinfo=UTC)
RESULTS = {}
MILESTONES = (30, 899, 900, 905, 1799, 1800, 2699, 2700)


@pytest.fixture(autouse=True)
def no_network_or_database(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("TEST_ONLY: network and database access are forbidden")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(sqlite3, "connect", denied)


def fictional_method(root):
    raw = b"TEST_ONLY fictional inclusive coverage; NOT provider evidence or approval"
    path = root / "TEST_ONLY-method.txt"
    path.write_bytes(raw)
    claim = dict(assertion="COMPANY_ACTION_RANGE_COMPLETENESS_AND_PRICE_TYPES",
        interface="FundamentalContext.corporate_actions",
        range_semantics="INCLUSIVE_COMPLETE_SINGLE_RESPONSE",
        known_action_types=["TEST_ONLY_SPLIT"],
        price_changing_action_types=["TEST_ONLY_SPLIT"],
        economic_date_type="TEST_ONLY_EFFECTIVE", date_zone="America/New_York")
    return dict(status="APPROVED", source_kind="OFFICIAL_DOCUMENT",
        reviewer="TEST_ONLY_REVIEWER", interface=claim["interface"],
        source_url="https://open.longbridge.com/docs/TEST_ONLY-fictional-method",
        source_path=path.name, source_sha256=sha256(raw).hexdigest(), excerpt=raw.decode(),
        reviewed_at=BASE.isoformat(), valid_until=(BASE + timedelta(days=1)).isoformat(),
        claim=claim, claim_hash=actions.common.digest(claim))


def synthetic_scope(count, *, duplicates=False, excluded=0):
    rows = []
    for number in range(count + excluded):
        verified = number < count
        symbol = f"TEST{number:03d}"
        row = dict(symbol=symbol, provider_symbol=symbol + ".US",
            identity_status="verified" if verified else "unknown", groups=["A", "B"])
        if duplicates:
            rows.extend({**row, "direction": direction, "group_id": group}
                        for direction in (1, -1) for group in ("A", "B"))
        else:
            rows.append(row)
    return rows


class SyntheticClock:
    def __init__(self):
        self.seconds = 0.0

    def now(self):
        return BASE + timedelta(seconds=self.seconds)

    def monotonic(self):
        return self.seconds

    def advance(self, seconds):
        self.seconds += seconds


class SyntheticTransport:
    """One-symbol hypothetical dated method plus raw one-category calendar."""
    def __init__(self, clock, *, latency=0, pages=1):
        self.clock, self.latency, self.pages = clock, latency, pages
        self.calls = []

    def corporate_actions(self, symbol, *, start_date, end_date):
        self.calls.append(dict(kind="action", at=self.clock.seconds, symbol=symbol,
                               start=start_date.isoformat(), end=end_date.isoformat()))
        self.clock.advance(self.latency)
        self.calls[-1]["received_at_seconds"] = self.clock.seconds
        return {"data": {"items": [], "total_count": 0, "has_more": False}}

    def request(self, method, path):
        parsed = urlsplit(path)
        assert method == "get" and parsed.path == "/v1/quote/finance_calendar"
        query = parse_qs(parsed.query)
        assert query["markets[]"] == ["US"]
        category = query["types[]"][0]
        assert category in {value.lower() for value in calendar.CATEGORY_NAMES.values()}
        day = query["date"][0]
        self.calls.append(dict(kind="calendar", at=self.clock.seconds, category=category,
                               start=day, end=query["date_end"][0]))
        self.clock.advance(self.latency)
        self.calls[-1]["received_at_seconds"] = self.clock.seconds
        next_date = "" if self.pages == 1 else (
            datetime.fromisoformat(day).date() + timedelta(days=1)).isoformat()
        return {"code": 0, "data": {"date": day, "next_date": next_date,
                "list": [{"date": day, "count": 0, "infos": []}]}}


def run_actual_source_loop(root, monkeypatch, *, symbols, latency=0, pages=1):
    from kquant import options_two_hour_data as data
    from kquant import options_opening_trend_reference as reference
    from kquant import option_official_source as official
    from kquant import options_opening_trend_event_auto as event_auto

    clock = SyntheticClock()
    transport = SyntheticTransport(clock, latency=latency, pages=pages)
    method = fictional_method(root)
    scope = synthetic_scope(symbols, duplicates=True, excluded=11 if symbols == 100 else 0)

    class SyntheticDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock.now()
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    # Only input/time boundaries are substituted. All tested functions remain real.
    monkeypatch.setattr(supervisor, "datetime", SyntheticDateTime)
    monkeypatch.setattr(supervisor, "monotonic", clock.monotonic)
    monkeypatch.setattr(calendar, "datetime", SyntheticDateTime)
    monkeypatch.setattr(calendar, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(actions, "monotonic", clock.monotonic)
    monkeypatch.setattr(data, "universe", lambda path: {"items": scope, "scope_hash": "TEST_ONLY"})
    monkeypatch.setattr(reference, "ROOT", root)
    monkeypatch.setattr(reference, "load_reviews", lambda: {"company_action_coverage_method": method})
    monkeypatch.setattr(supervisor, "market_schedule", lambda day, path: {
        "is_trading_day": True, "regular_close_utc": "2026-10-13T20:00:00+00:00"})
    monkeypatch.setattr(official, "refresh_active_reviews", lambda *a, **k: {
        "status": "TEST_ONLY_ADJACENT_REVIEW_NOT_EXERCISED"})
    monkeypatch.setattr(event_auto, "refresh_bound_sources", lambda *a, **k: {
        "status": "TEST_ONLY_ADJACENT_BINDING_NOT_EXERCISED"})
    # CalendarSourceRunner imports an enum only. No real SDK module is executed.
    sdk = ModuleType("longbridge.openapi")
    sdk.CalendarCategory = SimpleNamespace(**{name: name for name in calendar.CATEGORY_NAMES.values()})
    monkeypatch.setitem(sys.modules, "longbridge.openapi", sdk)

    runner = calendar.CalendarSourceRunner(root / "TEST_ONLY-NO-DATABASE",
                                          store=root / "sources", context=transport)
    loop = supervisor.OptionRadarSupervisor.__new__(supervisor.OptionRadarSupervisor)
    loop.db_path, loop._calendar_runner = runner.db_path, runner
    loop._status, loop._lock = {}, RLock()
    loop.one_minute_shadow_enabled = True
    samples, tick_budgets = [], []
    index = runner.store / "price-actions/index.json"

    def census(at):
        now = BASE + timedelta(seconds=at)
        records = json.loads(index.read_text())["records"] if index.exists() else {}
        usable = actions.load_facts(runner.store, now=now, root=root)
        sample = {"at_seconds": at, **actions.action_counts(records, now),
                  "revalidated_fresh": len(usable), "registered_records": len(records),
                  "not_yet_observed_in_scope": symbols - sum(bool(row.get("received_at"))
                                                           for row in records.values())}
        samples.append(sample)

    class SyntheticStop:
        def is_set(self):
            return clock.seconds >= 2701

        def wait(self, delay):
            budget = dict(loop._status.get("source_request_budget", {}))
            if budget:
                tick_budgets.append({"at_seconds": clock.seconds, **budget})
            before, after = clock.seconds, min(2701, clock.seconds + delay)
            seen = {row["at_seconds"] for row in samples}
            for milestone in MILESTONES:
                if milestone not in seen and before <= milestone <= after:
                    census(milestone)
            clock.seconds = after
            return self.is_set()

    loop._stop = SyntheticStop()
    try:
        loop._run_calendar_sources()
    finally:
        assert runner.source_call_gate.close()["in_flight"] is False
    assert [row["at_seconds"] for row in samples] == list(MILESTONES)
    assert tick_budgets and all(0 <= row["used"] <= 12 for row in tick_budgets)
    assert all(row["local_cap"] == 12 and row["window_seconds"] == 840 for row in tick_budgets)
    assert all(row["provider_limit_verified"] is False for row in tick_budgets)
    assert all(row["pending_reservations"] == 0 for row in tick_budgets)
    assert not list(root.rglob("*.db")) and not list(root.rglob("*.sqlite*"))
    windows = {}
    for row in tick_budgets:
        opened = row["opened_at"]
        state = windows.setdefault(opened, {"used_max": 0, "ticks": 0})
        state["used_max"] = max(state["used_max"], row["used"])
        state["ticks"] += 1
    result = dict(classification="TEST_ONLY_HYPOTHETICAL_METHOD_NOT_PRODUCTION",
        symbols=symbols, duplicated_direction_group_rows=len(scope), latency_seconds=latency,
        samples=samples, windows=windows, calls=transport.calls,
        action_requests=sum(row["kind"] == "action" for row in transport.calls),
        calendar_requests=sum(row["kind"] == "calendar" for row in transport.calls),
        final_action_state=loop._status.get("price_action_sources"),
        final_calendar_state={key: loop._status.get("event_sources", {}).get(key) for key in
            ("status", "calendar_requests", "source_complete_categories", "trade_eligible")},
        whole_tick_mocked=False, provider_requests=0, databases_opened=0,
        production_approval=False, adjacent_binding_and_s0_exercised=False)
    intervals = {}
    for call in transport.calls:
        if call["kind"] == "action":
            intervals.setdefault(call["symbol"], []).append(call["received_at_seconds"])
    result["action_renewal_intervals"] = {symbol: {
        "receipts_seconds": receipts,
        "max_gap_seconds": max((right - left for left, right in zip(receipts, receipts[1:])), default=None),
        "last_fact_valid_through_seconds": receipts[-1] + 900,
    } for symbol, receipts in intervals.items()}
    return result


@pytest.mark.parametrize("latency", [0, 1.5])
def test_six_symbol_capacity_renews_across_three_ttl_windows(tmp_path, monkeypatch, latency):
    result = run_actual_source_loop(tmp_path, monkeypatch, symbols=6, latency=latency)
    RESULTS[f"sustainable_6_latency_{latency}"] = result
    assert all(row["revalidated_fresh"] == 6 for row in result["samples"])
    assert all(row["expired"] == 0 for row in result["samples"])
    assert result["calendar_requests"] == result["action_requests"] == 24
    assert len(result["action_renewal_intervals"]) == 6
    assert all(row["max_gap_seconds"] < 900 and row["last_fact_valid_through_seconds"] > 2700
               for row in result["action_renewal_intervals"].values())


def test_100_symbol_backlog_cannot_remain_current(tmp_path, monkeypatch):
    result = run_actual_source_loop(tmp_path, monkeypatch, symbols=100)
    RESULTS["unsustainable_100"] = result
    assert result["action_requests"] == 24 and result["calendar_requests"] == 24
    assert all(row["revalidated_fresh"] < 100 for row in result["samples"])
    assert next(row for row in result["samples"] if row["at_seconds"] == 905)["expired"] == 3
    assert result["final_action_state"]["applicable_symbols"] == 100
    assert result["final_action_state"]["identity_excluded"] == 11


def test_calendar_pagination_cannot_be_assumed_free(tmp_path, monkeypatch):
    result = run_actual_source_loop(tmp_path, monkeypatch, symbols=6, pages=2)
    RESULTS["calendar_needs_second_pages"] = result
    assert result["calendar_requests"] == 24
    assert result["final_calendar_state"]["source_complete_categories"] == 0
    assert result["final_calendar_state"]["trade_eligible"] is False


def test_symbol_only_installed_contract_has_no_dated_or_bulk_signature():
    venv = Path(sys.executable).parents[1]
    metadata = venv / "Lib/site-packages/longbridge-4.4.1.dist-info/METADATA"
    stub = venv / "Lib/site-packages/longbridge/openapi.pyi"
    if not metadata.is_file() or not stub.is_file():
        pytest.skip("Installed 4.4.1 evidence is specific to the authorized local interpreter")
    assert "Version: 4.4.1" in metadata.read_text(encoding="utf-8")
    tree = ast.parse(stub.read_text(encoding="utf-8"))
    context = next(row for row in tree.body if isinstance(row, ast.ClassDef) and row.name == "FundamentalContext")
    methods = {row.name: row for row in context.body if isinstance(row, ast.FunctionDef)}
    method = methods["corp_action"]
    assert [row.arg for row in method.args.args] == ["self", "symbol"]
    assert not method.args.kwonlyargs and method.args.vararg is None and method.args.kwarg is None
    assert "corporate_actions" not in methods
    RESULTS["installed_contract"] = dict(version="4.4.1", signature="corp_action(self, symbol: str)",
        sdk_constructed=False, provider_requests=0, supports_bulk=False, supports_dated_arguments=False,
        stub_path=str(stub), stub_line=method.lineno, metadata_path=str(metadata))


def test_current_httpclient_capability_rejection_costs_zero_requests(tmp_path):
    sent = []
    transport = SimpleNamespace(request=lambda *a, **k: sent.append((a, k)))
    runner = calendar.CalendarSourceRunner(tmp_path / "TEST_ONLY-NO-DATABASE",
        store=tmp_path / "sources", context=transport)
    budget = actions.SourceRequestBudget(tmp_path / "budget.json", cap=12, now=BASE)
    try:
        for _ in range(2):
            reserved = budget.grant(3, event_reserve=6)
            result = actions.refresh(runner, now=BASE, clock=lambda: BASE, root=tmp_path,
                scope=synthetic_scope(1, duplicates=True), reviews={})
            budget.settle(reserved, result["requests"])
            assert result["requests"] == 0
        assert sent == [] and budget.snapshot()["used"] == 0
        assert result["states"] == {"SOURCE_CAPABILITY_UNCONFIRMED": 1}
        RESULTS["current_httpclient"] = dict(requests=0, used=budget.snapshot()["used"],
            states=result["states"], source_wakeup=result["source_wakeup"])
    finally:
        runner.source_call_gate.close()


def test_refresh_deadline_and_expiry_are_not_extended(tmp_path):
    method = fictional_method(tmp_path)
    observed = actions.observe({"data": {"items": [], "has_more": False}},
        symbol="TEST", requested_at=BASE, received_at=BASE, target_session=BASE.date(),
        interface="FundamentalContext.corporate_actions",
        query={"symbol": "TEST.US", "start_date": "2026-10-12", "end_date": "2026-10-13"})
    observed["coverage_fact"] = actions.coverage_fact(observed, method=method, now=BASE, root=tmp_path)
    fact = observed["coverage_fact"]
    assert actions.refresh_due_at(observed, completed_at=BASE) == BASE + timedelta(seconds=840)
    assert actions.common.timestamp(fact["valid_until"]) == BASE + timedelta(seconds=900)
    assert actions.valid_fact(fact, symbol="TEST", previous="2026-10-12", session="2026-10-13",
        now=BASE + timedelta(seconds=899), root=tmp_path)
    assert actions.valid_fact(fact, symbol="TEST", previous="2026-10-12", session="2026-10-13",
        now=BASE + timedelta(seconds=900), root=tmp_path) is None
    RESULTS["expiry_boundary"] = dict(renewal_due_seconds=840, expiry_seconds=900,
        usable_at_899=True, usable_at_900=False, owner_approval=fact["owner_approval"])


def test_zz_emit_test_only_results():
    output = os.environ.get("P13_CAPACITY_TEST_RESULTS")
    if output:
        path = Path(output).resolve()
        assert path.parent == Path(r"C:\Users\Administrator\Desktop\Codex coding")
        assert path.name == "P13_source_capacity_20261013.tests.json"
        path.write_text(json.dumps({"classification": "TEST_ONLY", "results": RESULTS}, indent=2),
                        encoding="utf-8")
