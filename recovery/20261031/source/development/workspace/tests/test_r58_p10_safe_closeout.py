"""TEST_ONLY actual modules and gateway routes, never production source facts."""
import asyncio
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import ClientDisconnect, Request

from kquant import options_one_minute as common
from kquant import options_price_action_source as actions
from kquant import options_price_facts as facts
from kquant import options_price_reference as reference
from kquant import options_opening_momentum as model
from kquant import options_opening_momentum_journal as journal
from kquant_crypto.gateway import LoginFingerprintReader, LoginFingerprintCheck, create_gateway_app
from kquant.security import generate_password_hash as hash_password
from test_r58_p7_inputs import fact_inputs


def action_method(root, now):
    raw = b"TEST_ONLY provider range statement, not a production reply"
    (root / "action-reply.txt").write_bytes(raw)
    claim = dict(assertion="COMPANY_ACTION_RANGE_COMPLETENESS_AND_PRICE_TYPES",
        interface="FundamentalContext.corporate_actions", range_semantics="INCLUSIVE_COMPLETE_SINGLE_RESPONSE",
        known_action_types=["split", "meeting"], price_changing_action_types=["split"],
        economic_date_type="ex_date", date_zone="America/New_York")
    proof = dict(status="APPROVED", source_kind="FORMAL_PROVIDER_REPLY", reviewer="TEST_ONLY_REVIEWER",
        interface=claim["interface"], reviewed_at=now.isoformat(), valid_until=(now + timedelta(days=1)).isoformat(),
        source_path="action-reply.txt", source_sha256=sha256(raw).hexdigest(), excerpt=raw.decode(),
        claim=claim, claim_hash=common.digest(claim), authenticity_review_path="action-review.json")
    review = dict(status="ACCEPTED", provider="LONGBRIDGE", channel="SUPPORT_TICKET", reference_id="TEST_ONLY",
        issuer_origin="TEST_ONLY", method="ORIGINAL_PROVIDER_CHANNEL_MANUALLY_VERIFIED", reviewer=proof["reviewer"],
        issued_at=now.isoformat(), reviewed_at=now.isoformat(), source_sha256=proof["source_sha256"],
        applicable_interfaces=[proof["interface"]])
    raw_review = json.dumps(review).encode()
    (root / "action-review.json").write_bytes(raw_review)
    proof["authenticity_review_sha256"] = sha256(raw_review).hexdigest()
    return proof


def action_observation(now, response=None):
    return actions.observe(response or {"data": {"items": []}}, symbol="TEST", requested_at=now,
        received_at=now, target_session=date(2026, 10, 2), interface="FundamentalContext.corporate_actions",
        query={"symbol": "TEST.US", "start_date": "2026-10-01", "end_date": "2026-10-02"})


def test_observer_fact_binding_persistence_reference_and_actual_s0(tmp_path, monkeypatch):
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    reviews.pop("instrument_price_actions")
    method = action_method(tmp_path, args["now"])
    value = actions.coverage_fact(action_observation(args["now"]), method=method, now=args["now"], root=tmp_path)
    assert value["status"] == "PROGRAM_VERIFIED" and value["owner_approval"] is False
    folder = tmp_path / "work/option_foundation/price-action-facts/TEST"
    folder.mkdir(parents=True)
    (folder / "2026-10-02.json").write_text(json.dumps(value))
    reviews["company_action_coverage_method"] = method
    db = tmp_path / "TEST_ONLY.db"
    journal.initialize(db)
    quote["session_price_binding"] = facts.persist_binding(db, facts.bind(quote, symbol="TEST",
        session="2026-10-02", now=args["now"], reviews=reviews, root=tmp_path))
    assert quote["session_price_binding"]["status"] == "VERIFIED"
    args["reference"] = reference.build(quote, symbol="TEST", session="2026-10-02", now=args["now"],
                                       reviews=reviews, root=tmp_path)
    assert reference.valid(args["reference"], symbol="TEST", session="2026-10-02", now=args["now"])
    result = model.evaluate(**args)
    assert result["state"] == "NUMERIC_PASS" and not result["qualified_signal"]


def test_actual_source_refresh_auto_binds_wakes_original_checkpoint_and_cas_commits(tmp_path, monkeypatch):
    from kquant.options_opening_trend_runtime import TrendLane
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    reviews.pop("instrument_price_actions")
    reviews["company_action_coverage_method"] = action_method(tmp_path, args["now"])
    review_path = tmp_path / "TEST_ONLY-reviews.json"
    review_path.write_text(json.dumps(reviews), encoding="utf-8")
    minute, research = tmp_path / "TEST_ONLY-minutes.db", tmp_path / "TEST_ONLY-research.db"
    common.initialize(minute)
    common.save_bars(args["bars"], "2026-10-02", minute)
    events, native_requests = [], []
    class SharedTransport:
        def corporate_actions(self, symbol, *, start_date, end_date):
            native_requests.append((symbol, start_date.isoformat(), end_date.isoformat()))
            return {"data": {"items": [], "total_count": 0, "has_more": False}}
    transport = SharedTransport()
    runner = SimpleNamespace(store=tmp_path / "calendar", _context=lambda: transport)
    lane = TrendLane(minute, SimpleNamespace(publish=events.append), path=research,
        clock=lambda: args["now"], source_root=tmp_path, source_reviews_path=review_path)
    job_id = journal.identity(("opening_momentum", "2026-10-02", "TEST", 1), args["scope_hash"])
    def wait_until(predicate):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if predicate(): return
            time.sleep(.02)
        pytest.fail(f"actual lane did not progress: {lane.state}")
    def checkpoint_state():
        with closing(sqlite3.connect(research, timeout=.1)) as db:
            return db.execute("SELECT state,deadline_at,payload_json FROM two_hour_jobs WHERE job_id=?", (job_id,)).fetchone()
    try:
        lane.enqueue("TEST", args["opening"].date(), args["bars"], args["scope_hash"], {"raw_quote": quote})
        wait_until(lambda: checkpoint_state() and checkpoint_state()[0] == "WAIT_INPUT")
        before = checkpoint_state()
        output = actions.refresh(runner, now=args["now"], clock=lambda: args["now"], root=tmp_path,
            reviews=reviews, scope=[{"symbol": "TEST", "identity_status": "verified"}])
        assert output["source_wakeup"] == {"woken": 1, "errors": []}
        wait_until(lambda: checkpoint_state()[0] == "COMPLETED")
        after = checkpoint_state()
        assert before[1] == after[1] == (args["opening"] + timedelta(minutes=10)).isoformat()
        assert json.loads(after[2])["input_generation"] > json.loads(before[2])["input_generation"]
        assert native_requests == [("TEST.US", "2026-10-01", "2026-10-02")]
        with closing(sqlite3.connect(research)) as db:
            passed = json.loads(db.execute("SELECT payload_json FROM evaluations WHERE state='NUMERIC_PASS'").fetchone()[0])
            binding = passed["reference_evidence"]["session_price_binding"]
            assert db.execute("SELECT 1 FROM two_hour_jobs WHERE job_id=?", (binding["fact_hash"],)).fetchone()
            assert db.execute("SELECT COUNT(*) FROM qualified_claims").fetchone()[0] == 0
        later = reference.build(quote, symbol="TEST", session="2026-10-02", now=args["now"] + timedelta(seconds=1), reviews=reviews, root=tmp_path)
        assert later["session_price_binding"]["fact_hash"] == binding["fact_hash"]
        assert not passed["qualified_signal"]
    finally:
        lane.close()


@pytest.mark.parametrize("body", [None, [], "unrecognized"])
def test_malformed_native_data_is_incomplete_not_parser_exception(tmp_path, body):
    now = datetime(2026, 10, 2, 13, 35, 10, tzinfo=UTC)
    observed = action_observation(now, {"data": body})
    value = actions.coverage_fact(observed, method=action_method(tmp_path, now), now=now, root=tmp_path)
    assert not value["complete"] and "COMPANY_ACTION_RESPONSE_SCHEMA_UNCONFIRMED" in value["reasons"]


@pytest.mark.parametrize("defect", ["no_method", "legacy_range", "wrong_symbol", "changed_raw", "more", "count", "date", "unknown_type", "split", "expired", "reply_changed"])
def test_action_negatives_do_not_claim_unchanged(tmp_path, defect):
    now = datetime(2026, 10, 2, 13, 35, 10, tzinfo=UTC)
    method, observation = action_method(tmp_path, now), action_observation(now)
    if defect == "no_method": method = None
    if defect == "legacy_range": observation["query"].pop("start_date")
    if defect == "wrong_symbol": observation["query"]["symbol"] = "OTHER.US"
    if defect == "changed_raw": observation["raw_response_sha256"] = "wrong"
    if defect == "more": observation["raw_response"]["data"]["has_more"] = True
    if defect == "count": observation["raw_response"]["data"]["total_count"] = 1
    if defect in {"date", "unknown_type", "split"}:
        observation["raw_response"]["data"]["items"] = [dict(date="20261001" if defect != "date" else "20260901",
            act_type="unknown" if defect == "unknown_type" else "split", date_type="ex_date", date_zone="America/New_York")]
    if defect not in {"changed_raw"}: observation["raw_response_sha256"] = common.digest(observation["raw_response"])
    if defect == "reply_changed": (tmp_path / "action-reply.txt").write_bytes(b"changed")
    value = actions.coverage_fact(observation, method=method, now=now, root=tmp_path)
    checked = now + timedelta(seconds=901) if defect == "expired" else now
    assert actions.valid_fact(value, symbol="TEST", previous="2026-10-01", session="2026-10-02", now=checked, root=tmp_path) is None


def test_fair_first_coverage_and_no_repeated_methodless_requests(tmp_path):
    now = datetime.now(UTC)
    requested = []
    class SharedContext:
        def corporate_actions(self, symbol, *, start_date, end_date):
            requested.append(symbol)
            if "S000" in symbol: raise TimeoutError()
            return {"data": {"items": []}}
    context = SharedContext()
    runner = SimpleNamespace(store=tmp_path / "calendar", _context=lambda: context)
    scope = [{"symbol": f"S{i:03}", "identity_status": "verified"} for i in range(100)]
    scope += [{"symbol": f"X{i}", "identity_status": "unknown"} for i in range(11)]
    for _ in range(34):
        actions.refresh(runner, now=now, scope=scope, reviews={}, root=tmp_path)
    assert len(requested) == 100
    assert len(set(requested)) == 100
    result = actions.refresh(runner, now=now + timedelta(seconds=301), scope=scope, reviews={}, root=tmp_path)
    assert result["requests"] == 1 and result["observed_symbols"] == 100
    records = json.loads((runner.store / "price-actions/index.json").read_text())["records"]
    assert len(records) == 100 and "X0" not in records


def test_shared_budget_restart_unknown_count_and_backward_clock(tmp_path):
    now = datetime.now(UTC)
    path = tmp_path / "budget.json"
    budget = actions.SourceRequestBudget(path, cap=20, now=now)
    assert budget.grant(3, event_reserve=6) == 3
    budget.settle(3, 2)
    assert budget.grant(18) == 18
    budget.settle(18, None)
    restarted = actions.SourceRequestBudget(path, cap=20, now=now + timedelta(seconds=5))
    assert restarted.remaining == 0 and restarted.grant(3) == 0
    backward = actions.SourceRequestBudget(path, cap=20, now=now - timedelta(seconds=1))
    assert backward.remaining == 0
    renewed = actions.SourceRequestBudget(path, cap=20, now=now + timedelta(seconds=840))
    assert renewed.grant(20) == 20


def test_calendar_batch_cannot_reserve_all_capacity_and_starve_first_coverage(tmp_path):
    budget = actions.SourceRequestBudget(tmp_path / "shared-budget.json", cap=20, now=datetime.now(UTC))
    assert budget.grant(3, event_reserve=6) == 3
    assert budget.grant_calendar_batch() == 6
    assert budget.remaining == 11
    assert [budget.grant(3) for _ in range(4)] == [3, 3, 3, 2]
    assert budget.remaining == 0


def test_file_generation_cache_replacement_and_preserved_mtime(tmp_path):
    path = tmp_path / "TEST_ONLY.dpapi"
    path.write_bytes(b"original")
    reader = LoginFingerprintReader(path)
    first = reader()
    for _ in range(20): assert reader() == first
    assert reader.hash_reads == 1
    stat = path.stat()
    path.write_bytes(b"modified")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert reader() != first and reader.hash_reads == 2


def test_slow_fingerprint_consumes_finished_generation_and_revocation_is_sticky():
    gate, entered = Event(), Event()
    def read():
        entered.set()
        gate.wait(2)
        return "original"
    checker = LoginFingerprintCheck(read, "original")
    async def exercise():
        first = await checker.state(enabled=True)
        assert first == "UNAVAILABLE" and entered.is_set()
        generation = checker.future
        gate.set()
        await asyncio.wrap_future(generation)
        assert await checker.state(enabled=True) == "UNCHANGED"
        assert checker.future is generation
        checker.reader = lambda: "replacement"
        assert await checker.state(enabled=True) == "CHANGED"
        checker.reader = lambda: "original"
        assert await checker.state(enabled=True) == "CHANGED"
        assert checker.diagnostics["reason"] == "CONFIGURATION_GENERATION_CHANGED"
    try:
        asyncio.run(exercise())
    finally:
        gate.set()
        checker.close()


@pytest.mark.parametrize("result,expected", [("original", "UNCHANGED"), ("replacement", "CHANGED"), ("io_error", "UNAVAILABLE")])
def test_completed_file_result_survives_delayed_async_delivery(monkeypatch, result, expected):
    gate = Event()
    def read():
        assert gate.wait(2)
        if result == "io_error":
            raise OSError("TEST_ONLY unavailable file")
        return result
    checker = LoginFingerprintCheck(read, "original")
    async def delayed_delivery(awaitable, *, timeout):
        assert timeout == .05
        gate.set()
        await awaitable
        raise TimeoutError("TEST_ONLY delayed completed-result delivery")
    monkeypatch.setattr(asyncio, "wait_for", delayed_delivery)
    try:
        assert asyncio.run(checker.state(enabled=True)) == expected
        assert checker.diagnostics["timeouts"] == 0
        assert checker.future.done()
    finally:
        gate.set()
        checker.close()


def test_actual_gateway_cold_login_logout_and_configuration_revocation(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "true")
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_EMAIL", "test-only@example.invalid")
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH", hash_password("TEST_ONLY long test password"))
    monkeypatch.setenv("KQUANT_WORKSPACE_SESSION_SECRET", "TEST_ONLY_SECRET_" * 4)
    path = tmp_path / "KQUANT/workspace_login.dpapi"
    path.parent.mkdir()
    path.write_bytes(b"TEST_ONLY not real DPAPI")
    app = create_gateway_app(stocks_url="http://TEST_ONLY", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "ok"})))
    with TestClient(app) as client:
        assert client.get("/api/stocks/health").status_code == 401
        assert client.post("/api/auth/login", json={"email": "test-only@example.invalid", "password": "TEST_ONLY long test password"}).status_code == 200
        assert client.get("/api/auth/session").json()["authenticated"] is True
        assert client.get("/api/stocks/health").status_code == 200
        client.post("/api/auth/logout")
        assert client.get("/api/stocks/health").status_code == 401
        path.write_bytes(b"TEST_ONLY replacement DPAPI")
        assert client.get("/api/auth/session").json()["restart_required"] is True
        response = client.get("/api/stocks/health")
        assert response.status_code == 503 and response.headers["Retry-After"] == "1"
        assert "replacement" not in response.text and "source_hash" not in response.text


def test_gateway_get_never_reads_body_and_disconnected_write_is_not_forwarded(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "false")
    requested = []
    app = create_gateway_app(stocks_url="http://TEST_ONLY", transport=httpx.MockTransport(
        lambda request: requested.append(request.method) or httpx.Response(200, json={"status": "ok"})))
    async def disconnected(request):
        raise ClientDisconnect()
    monkeypatch.setattr(Request, "body", disconnected)
    with TestClient(app) as client:
        assert client.get("/api/stocks/health").status_code == 200
        assert client.post("/api/stocks/watchlist").status_code == 499
    assert requested == ["GET"]
