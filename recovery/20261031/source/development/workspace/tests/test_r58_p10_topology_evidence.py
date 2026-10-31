"""Check measurement denominators without spawning apps or reading business data."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest


@pytest.fixture
def harness():
    path = Path(__file__).parents[1] / "scripts" / "check_r58_p10_topology.py"
    spec = spec_from_file_location("topology_evidence_test", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def event(symbol, point, value, strategy="opening_momentum"):
    return {"symbol": symbol, "bar_end": point, "research_strategy": strategy,
            "runtime_timing": {"enqueue_to_commit_seconds": value}}


def test_first_evaluation_not_revision(harness):
    values = [event("AAPL", "point", 3), event("AAPL", "point", .01), event("MSFT", "point", 4)]
    result = harness.first_timings(values, "point")["enqueue_to_commit_seconds"]
    assert result == {"n": 2, "p95_seconds": 4}


@pytest.mark.parametrize('session,previous', [('2026-10-12', '2026-10-09'),
                                            ('2026-09-08', '2026-09-04')])
def test_actual_setup_covers_previous_exchange_session(harness, tmp_path, session, previous):
    import json
    from datetime import date
    from kquant.market_clock import session_bounds_utc
    opening, _ = session_bounds_utc(date.fromisoformat(session))
    watch = Path(__file__).parents[3] / 'evidence/retained-watchlist.json'
    harness.setup({'out': str(tmp_path), 'watch': str(watch),
                   'session': session, 'opening': opening.isoformat()})
    sources = json.loads((tmp_path / 'TEST_ONLY-sources.json').read_text())
    rows = sources['instrument_price_actions']
    assert len(rows) == 100
    assert all(row['coverage_from_session'] == previous for row in rows.values())
    assert all(row['coverage_through_session'] == session for row in rows.values())


def test_other_checkpoint_and_strategy_excluded(harness):
    values = [event("AAPL", "earlier", 1), event("MSFT", "point", 2, "opening_trend"), event("MSFT", "point", 3)]
    result = harness.first_timings(values, "point")["enqueue_to_commit_seconds"]
    assert result == {"n": 1, "p95_seconds": 3}


def test_missing_measurement_not_zero(harness):
    values = [event("AAPL", "point", None)]
    assert harness.first_timings(values, "point")["enqueue_to_commit_seconds"] == {"n": 0, "p95_seconds": None}


def test_loop_observer_redacts_and_does_not_waive_connection_reset(harness, tmp_path):
    from types import SimpleNamespace
    import json
    emitted = []
    callbacks = []
    loop = SimpleNamespace(set_exception_handler=callbacks.append,
                           default_exception_handler=emitted.append)
    handler = harness.install_loop_observer(loop, tmp_path, 'gateway')
    error = ConnectionResetError(10054, 'PRIVATE_TOKEN_NOT_FOR_LOG')
    error.winerror = 10054
    handler(loop, {'exception': error, 'message': 'PRIVATE_TOKEN_NOT_FOR_LOG',
                   'transport': 'PRIVATE_TOKEN_NOT_FOR_LOG'})
    errors = []
    rows = harness.loop_observations(tmp_path, errors)
    assert rows[0]['role'] == 'gateway'
    assert rows[0]['pid'] > 0
    assert rows[0]['winerror'] == 10054
    assert rows[0]['request_id'] is None
    assert rows[0]['classification'] == 'UNATTRIBUTED_LOOP_EXCEPTION'
    assert errors == [{'code': 'UNATTRIBUTED_EVENT_LOOP_EXCEPTIONS', 'count': 1}]
    assert emitted and callbacks == [handler]
    assert 'PRIVATE_TOKEN_NOT_FOR_LOG' not in json.dumps([rows, emitted])


def test_loop_observation_corruption_is_not_clean(harness, tmp_path):
    (tmp_path / 'TEST_ONLY-loop-backend-1.jsonl').write_text('broken')
    errors = []
    assert harness.loop_observations(tmp_path, errors) == []
    assert errors[0]['code'] == 'LOOP_EVIDENCE_UNREADABLE'


def test_actual_event_loop_callback_is_durable_and_fails_acceptance(harness, tmp_path):
    import asyncio
    import os

    async def exercise():
        loop = asyncio.get_running_loop()
        harness.install_loop_observer(loop, tmp_path, 'backend')
        delivered = asyncio.Event()

        def failing_callback():
            delivered.set()
            error = ConnectionResetError(10054, 'PRIVATE_CALLBACK_CONTEXT')
            error.winerror = 10054
            raise error

        loop.call_soon(failing_callback)
        await asyncio.wait_for(delivered.wait(), timeout=2)

    asyncio.run(exercise())
    errors = []
    rows = harness.loop_observations(tmp_path, errors)
    assert len(rows) == 1
    assert rows[0]['pid'] == os.getpid()
    assert rows[0]['role'] == 'backend'
    assert rows[0]['exception_type'] == 'ConnectionResetError'
    assert rows[0]['winerror'] == 10054
    assert rows[0]['observed_at']
    assert errors == [{'code': 'UNATTRIBUTED_EVENT_LOOP_EXCEPTIONS', 'count': 1}]
    assert 'PRIVATE_CALLBACK_CONTEXT' not in next(tmp_path.glob('TEST_ONLY-loop-*.jsonl')).read_text()


@pytest.mark.skipif(__import__('sys').platform != 'win32', reason='Windows TCP reset semantics')
def test_real_local_tcp_reset_allows_next_connection(harness, tmp_path):
    import asyncio
    import socket
    import struct

    async def exercise():
        loop = asyncio.get_running_loop()
        harness.install_loop_observer(loop, tmp_path, 'isolated-tcp')
        connected = asyncio.Event()
        reset_seen = loop.create_future()

        class Echo(asyncio.Protocol):
            def connection_made(self, transport):
                self.transport = transport
                connected.set()

            def data_received(self, data):
                self.transport.write(data)

            def connection_lost(self, exc):
                if not reset_seen.done():
                    reset_seen.set_result(exc)

        server = await loop.create_server(Echo, '127.0.0.1', 0)
        peer = socket.socket()
        writer = None
        try:
            peer.setblocking(False)
            address = server.sockets[0].getsockname()
            await asyncio.wait_for(loop.sock_connect(peer, address), 2)
            await asyncio.wait_for(connected.wait(), 2)
            peer.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('HH', 1, 0))
            peer.close()
            error = await asyncio.wait_for(reset_seen, 2)
            assert isinstance(error, ConnectionResetError)
            # Windows IOCP may report ERROR_NETNAME_DELETED for a peer RST.
            assert error.winerror in {64, 10054}
            reader, writer = await asyncio.wait_for(asyncio.open_connection(*address), 2)
            writer.write(b'TEST_ONLY_RECOVERY')
            await writer.drain()
            assert await asyncio.wait_for(reader.readexactly(18), 2) == b'TEST_ONLY_RECOVERY'
        finally:
            peer.close()
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            server.close()
            await server.wait_closed()

    asyncio.run(exercise())
    errors = []
    assert harness.loop_observations(tmp_path, errors) == []
    assert errors == []


def test_nearest_rank_and_empty_sample(harness):
    assert harness.percentile(list(range(1, 21))) == 19
    assert harness.percentile([]) is None


def test_fault_drive_rejected_without_lookup(harness, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("FAULT_PATH_LOOKUP_ATTEMPTED")
    monkeypatch.setattr(Path, "lstat", forbidden)
    with pytest.raises(ValueError, match="FAULT_DRIVE_FORBIDDEN"):
        harness.safe("F:/KQUANT-/work/options_one_minute/one_minute.sqlite3")


def test_browser_report_is_utf8_and_keeps_chinese_scope(harness, tmp_path):
    path = tmp_path / "browser-report.json"
    path.write_text('{"gateway_service_label":"\\u7f51\\u9875"}', encoding="utf-8")
    errors = []
    assert harness.load_browser_report(path, errors)["gateway_service_label"] == "\u7f51\u9875"
    path.write_text('{"gateway_service_label":"\u7f51\u9875"}', encoding="utf-8")
    assert harness.load_browser_report(path, errors)["gateway_service_label"] == "\u7f51\u9875"
    assert errors == []


def test_missing_and_corrupt_browser_reports_do_not_drop_cleanup_report(harness, tmp_path):
    path = tmp_path / "browser-report.json"
    errors = []
    assert harness.load_browser_report(path, errors) is None
    path.write_bytes(b"\xff")
    assert harness.load_browser_report(path, errors) is None
    assert errors[0]["code"] == "BROWSER_REPORT_UNREADABLE"


def test_watch_schema_is_checked_before_isolated_store_creation(harness, tmp_path):
    import json
    path = tmp_path / "watch.json"
    path.write_text('{"groups": []}')
    with pytest.raises(ValueError, match="FULL_WATCH_111_INPUT_REQUIRED"):
        harness.load_watch(path)
    rows = [{"symbol": str(i), "identity_status": "verified", "provider_symbol": f"{i}.US"} for i in range(111)]
    path.write_text(json.dumps({"items": rows}))
    assert len(harness.load_watch(path)["items"]) == 111
    rows[-1]["symbol"] = rows[0]["symbol"]
    path.write_text(json.dumps({"items": rows}))
    with pytest.raises(ValueError, match="WATCH_INPUT_IDENTITY_OR_DUPLICATE"):
        harness.load_watch(path)


def test_missing_policy_not_database_failure():
    from kquant.status_worker import safe_failure
    error = FileNotFoundError("secret path must not be included")
    result = safe_failure(error, phase="policy")
    assert result["code"] == "POLICY_CONFIG_MISSING"
    assert "secret" not in str(result)
    assert safe_failure(error)["code"] == "DATABASE_MISSING"


def test_policy_error_protocol_survives_worker_transport():
    import json
    import sys
    from kquant import status_worker
    diagnostic = status_worker.safe_failure(FileNotFoundError(), phase="policy")
    program = "import sys; sys.stdout.write(" + repr(json.dumps({"_status_error": diagnostic})) + "); sys.exit(1)"
    with pytest.raises(status_worker.StatusQueryFailure) as error:
        status_worker.run_json([sys.executable, "-B", "-c", program], diagnostics=True)
    assert error.value.diagnostic["code"] == "POLICY_CONFIG_MISSING"
    assert error.value.diagnostic["phase"] == "policy"


@pytest.mark.parametrize("kind", ["current", "compact"])
def test_missing_policy_rejects_before_spawn_and_restoration_is_rechecked(tmp_path, monkeypatch, kind):
    from kquant import status_worker
    monkeypatch.setattr(status_worker, "ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(status_worker, "run_json", lambda *a, **k: calls.append(a) or {"ok": True})
    def load():
        if kind == "current":
            return status_worker.load_current_cards(tmp_path / "unused.sqlite3", research_strategy="opening_trend")
        return status_worker.load_opening_trend(tmp_path / "unused.sqlite3", compact=True)
    with pytest.raises(status_worker.StatusQueryFailure) as exc:
        load()
    assert exc.value.diagnostic["code"] == "POLICY_CONFIG_MISSING"
    assert calls == []
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "options_opening_trend_v1.json").write_text("{}")
    assert load()["ok"]
    assert len(calls) == 1


def test_invalid_strategy_rejects_before_policy_path_lookup(monkeypatch):
    from kquant import status_worker
    class NoLookup:
        def __truediv__(self, other):
            pytest.fail("invalid strategy must not access a path")
    monkeypatch.setattr(status_worker, "ROOT", NoLookup())
    with pytest.raises(ValueError, match="INVALID_RESEARCH_STRATEGY"):
        status_worker.load_current_cards("unused", research_strategy="invalid")


@pytest.mark.parametrize("changed_source", [False, True])
def test_prepared_v3_reuse_still_checks_source_bytes_before_math(tmp_path, monkeypatch, changed_source):
    import os
    from types import SimpleNamespace
    from test_r58_p7_inputs import fact_inputs
    from kquant import options_price_reference as prices
    from kquant.options_opening_trend_runtime import TrendLane, LANE_BATCH_BOUND
    from kquant import options_opening_momentum_journal as journal
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    monkeypatch.setattr(prices, "ROOT", tmp_path)
    built = prices.build(quote, symbol="TEST", session="2026-10-02", now=args["now"],
                         reviews=reviews, root=tmp_path)
    assert prices.valid(built, symbol="TEST", session="2026-10-02", now=args["now"])
    if changed_source:
        source = tmp_path / "test-fact.txt"
        info = source.stat()
        raw = source.read_bytes()
        source.write_bytes(b"X" + raw[1:])
        os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
    def no_second_build(*a, **k):
        pytest.fail("freshly assembled V3 must not be assembled twice")
    monkeypatch.setattr(prices, "build", no_second_build)
    lane = TrendLane.__new__(TrendLane)
    lane.history = SimpleNamespace(get=lambda *a: ({}, {"state": "READY"}))
    lane.source_root = tmp_path
    lane.reference_checks, lane.state, lane.rechecked = {}, {}, set()
    lane.on_recheck = None
    lane.clock = lambda: args["now"]
    job = "TEST", args["opening"].date(), args["bars"], args["scope_hash"], built
    results, _, _ = lane._calculate(("opening_momentum", "2026-10-02", "TEST", 1),
                                    job, args["now"], [], None, reviews)
    assert results[0]["state"] == ("INCOMPLETE" if changed_source else "NUMERIC_PASS")
    assert lane.state["assembled_reference"]["verified_symbols"] == (0 if changed_source else 1)
    assert all(not row["qualified_signal"] for row in results)
    assert 0 < LANE_BATCH_BOUND <= journal.BATCH_BOUND
