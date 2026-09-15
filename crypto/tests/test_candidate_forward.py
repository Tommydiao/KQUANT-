"""Focused offline tests: no sockets, public REST calls, or private execution."""
import asyncio
from copy import deepcopy
from contextlib import contextmanager
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kquant_crypto import candidate_forward as forward
from kquant_crypto.strategy_dual_mode_v1 import Bar


class Portfolio:
    execution = "quotes"
    policy = {"symbols": list(forward.SYMBOLS)}

    def __init__(self):
        self.batches = []
        self.quotes = []
        self.pending = {}
        self.accept_entries = False
        self.rows = {"events": [], "trades": [], "equity": []}

    def on_closed_batch(self, bars, hourly, now, allow_entries=True):
        self.accept_entries = allow_entries
        if bars:
            self.batches.append((bars, hourly, now, allow_entries))
            self.rows["equity"].append({"time": now, "equity": 10000})

    def on_quote(self, *args):
        self.quotes.append((*args, self.accept_entries))

    def drain(self):
        rows, self.rows = self.rows, {"events": [], "trades": [], "equity": []}
        return rows

    def snapshot(self):
        return {"test_state": True}

    def restore(self, state):
        self.restored = state

    def status(self):
        return {"positions": {}}


def kline(symbol, start, **changes):
    k = {"s": symbol, "i": "5m", "x": True, "t": start * 1000,
         "T": (start + 300) * 1000 - 1, "o": "10", "h": "12",
         "l": "9", "c": "11", "v": "2"}
    k.update(changes)
    return {"stream": symbol.lower() + "@kline_5m", "data": {"s": symbol, "k": k}}


def quote(symbol="BTCUSDT", sequence=1, **changes):
    data = {"s": symbol, "u": sequence, "b": "10", "a": "11"}
    data.update(changes)
    return {"stream": symbol.lower() + "@bookTicker", "data": data}


def feed_at(start=3600):
    p = Portfolio()
    feed = forward.ForwardFeed(p, state={"last_close": start})
    feed.connected = True
    return p, feed


class Client:
    def __init__(self, bad_hour=False):
        self.calls = []
        self.bad_hour = bad_hour

    async def get(self, url, params):
        assert url == forward.REST_URL + "/api/v3/klines"
        self.calls.append(params)
        step = 300 if params["interval"] == "5m" else 3600
        starts = range(params["startTime"] // 1000, (params["endTime"] + 1) // 1000, step)
        rows = [[s * 1000, "10", "12", "9", "11", "2" if step == 300 else "24",
                 (s + step) * 1000 - 1] for s in list(starts)[:1000]]
        if self.bad_hour and step == 3600:
            rows[0][2] = "13"
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return rows
        return Response()


def test_bootstrap_native_hours_four_five_minute_pages_and_no_performance():
    client = Client()
    five, hourly = asyncio.run(forward.bootstrap(client, forward.SYMBOLS, 300 * 3600 + 1500))
    assert len(client.calls) == 15
    assert all(len(five[s]) == 3125 and len(hourly[s]) == 260 for s in forward.SYMBOLS)
    p = Portfolio()
    feed = forward.ForwardFeed(p)
    feed.warmup(five, hourly)
    assert len(p.batches) == 3125
    assert sum(bool(b[1]) for b in p.batches) == 260
    assert not any(b[3] for b in p.batches)
    assert p.drain()["equity"] == []
    assert p.quotes == []
    assert feed.records[-1]["evidence_scope"] == "warmup"


def test_bootstrap_rejects_hourly_mismatch():
    with pytest.raises(forward.DataUnavailable, match="mismatch"):
        asyncio.run(forward.bootstrap(Client(bad_hour=True), ("BTCUSDT",), 300 * 3600))


def test_hour_requires_exact_twelve_contiguous_subbars():
    bars = [Bar(3600 + i * 300, 10, 12, 9, 11, 2) for i in range(12)]
    assert forward.aggregate_hour(bars) == Bar(3600, 10, 12, 9, 11, 24)
    for invalid in (bars[:-1], bars[::-1], bars[1:] + [bars[-1]]):
        with pytest.raises(forward.DataUnavailable):
            forward.aggregate_hour(invalid)


def test_missing_symbol_and_out_of_order_batches_wait_common_watermark():
    p, feed = feed_at()
    for s in reversed(forward.SYMBOLS):
        feed.message(kline(s, 3900), 4201)
    assert p.batches == []
    for s in reversed(forward.SYMBOLS):
        feed.message(kline(s, 3600), 4202)
    assert [next(iter(b[0].values())).start for b in p.batches] == [3600, 3900]
    assert [b[3] for b in p.batches] == [False, True]
    assert list(p.batches[0][0]) == list(forward.SYMBOLS)
    feed.message(kline("BTCUSDT", 3900), 4203)
    assert len(p.batches) == 2


def test_late_closed_batch_cannot_generate_entries():
    p, feed = feed_at()
    for s in forward.SYMBOLS:
        feed.message(kline(s, 3600), 3931)
    assert p.batches[-1][3] is False


def test_bookticker_without_event_type_receipt_sequence_and_audit():
    p, feed = feed_at()
    assert feed.message(quote(sequence=10), 3601.125)
    assert not feed.message(quote(sequence=10), 3602)
    assert not feed.message(quote(sequence=9), 3603)
    assert not feed.message(quote(sequence=11), 3600)
    assert len(p.quotes) == 1
    assert p.quotes[0][3:5] == (3601.125, 10)
    event = feed.records[-1]
    assert event["received_at"] == 3601.125 and event["bbo_valid"]
    assert event["bid"] == 10 and event["ask"] == 11


@pytest.mark.parametrize("changes", [{"b": "nan"}, {"a": "0"}, {"b": "12"},
                                     {"u": "1"}, {"E": 1}, {"E": "bad"}])
def test_bad_quotes_rejected(changes):
    p, feed = feed_at()
    assert not feed.message(quote(**changes), 3601)
    assert not p.quotes


def test_stale_data_cancels_entries_but_delivers_real_quote_for_protection():
    p, feed = feed_at()
    p.accept_entries = True
    p.pending["BTCUSDT"] = {"signal_time": 3900}
    assert feed.message(quote(), 3931)
    assert p.quotes and p.quotes[-1][-1] is False
    assert not p.pending
    assert any(e["kind"] == "ENTRY_CANCELED" for e in feed.records)


def test_partial_open_future_and_conflicting_closed_bars():
    p, feed = feed_at()
    assert not feed.message(kline("BTCUSDT", 3600, x=False), 3901)
    with pytest.raises(forward.DataUnavailable):
        feed.message(kline("BTCUSDT", 3600), 3899)
    feed.message(kline("BTCUSDT", 3600), 3901)
    with pytest.raises(forward.DataUnavailable, match="conflicting"):
        feed.message(kline("BTCUSDT", 3600, c="10"), 3902)
    assert p.batches == []


def test_backfill_no_retrospective_quotes_entries_or_equity_and_restores_parts():
    p, feed = feed_at()
    for s in forward.SYMBOLS:
        feed.message(kline(s, 3600), 3901)
    p.drain()
    restored = forward.ForwardFeed(p, state=deepcopy(feed.snapshot()))
    asyncio.run(restored.backfill(Client(), 7201))
    assert restored.last_close == 7200
    assert p.batches[-1][1]["BTCUSDT"].volume == 24
    assert all(not b[3] for b in p.batches[1:])
    assert not p.quotes
    assert not p.drain()["equity"]


def test_process_lock_released_and_not_stealable(tmp_path):
    path = tmp_path / "forward.lock"
    with forward._process_lock(path):
        with pytest.raises(OSError):
            with forward._process_lock(path):
                pytest.fail("second writer acquired lock")
    with forward._process_lock(path):
        pass


@pytest.mark.parametrize("eof", [None, "empty", "raised", "json", "missing"])
def test_run_forward_mock_network_atomic_save_and_restore(tmp_path, monkeypatch, eof):
    class Store:
        def __init__(self):
            self.state = {"test_state": True, "forward": {"last_close": 3600}}
            self.saved = []
            self.stop_requested = True
            self.clear_calls = 0
            self.locked = False
            self.renewals = 0

        @contextmanager
        def process_lock(self, run_id, *, lease_seconds):
            assert lease_seconds == 60
            self.locked = True
            try:
                yield
            finally:
                self.locked = False

        def acquire_lock(self, run_id, *, lease_seconds):
            assert self.locked and lease_seconds == 60
            self.renewals += 1

        def clear_stop(self, run_id):
            assert self.locked
            self.clear_calls += 1
            self.stop_requested = False

        def load(self, run_id):
            return self.state

        def should_stop(self, run_id):
            return self.stop_requested or any(row[1].get("events") and any(e["kind"] == "MARKET_QUOTE" for e in row[1]["events"])
                       for row in self.saved)

        def save(self, run_id, state, **rows):
            assert self.locked
            self.saved.append((deepcopy(state), deepcopy(rows)))

    class HTTP:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False

        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *args):
            pass

    attempts = []

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def recv(self):
            if eof and len(attempts) == 1:
                if eof == "empty":
                    return ""
                if eof == "json":
                    return "{broken"
                if eof == "missing":
                    payload = kline("BTCUSDT", 3600)
                    del payload["data"]["k"]["o"]
                    return json.dumps(payload)
                raise EOFError("mock EOF")
            return json.dumps(quote())

    def connect(url, **kwargs):
        assert url.startswith(forward.WS_URL + "?streams=")
        assert "btcusdt@bookTicker" in url
        attempts.append(url)
        return Socket()

    monkeypatch.setattr(forward.httpx, "AsyncClient", HTTP)
    monkeypatch.setattr(forward, "connect", connect)
    monkeypatch.setattr(forward.time, "time", lambda: 3601.125)
    p, store = Portfolio(), Store()
    original_quote = p.on_quote

    def counted_quote(*args):
        original_quote(*args)
        p.count = getattr(p, "count", 0) + 1

    p.on_quote = counted_quote
    result = asyncio.run(forward.run_forward(p, store, "run", tmp_path, stop_after_seconds=5))
    assert p.restored == {"test_state": True}
    assert len(p.quotes) == 1
    assert store.saved[-1][0]["forward"]["sequence"]["BTCUSDT"] == 1
    assert result["forward"]["reason"] == "stopped"
    assert store.clear_calls == 1
    assert not store.locked
    assert store.renewals == len(store.saved)
    assert store.saved[0][0]["status"] == "running"
    assert store.saved[-1][0]["status"] == "stopped"
    assert result["status"] == "stopped"
    if eof:
        assert len(attempts) == 2
        error = "DataUnavailable" if eof in {"json", "missing"} else "EOFError"
        assert any(error in row[0]["forward"]["reason"] for row in store.saved)
    assert json.loads((tmp_path / "forward_status.json").read_text())["run_id"] == "run"


def test_public_only_imports_and_fixed_sources():
    import ast
    tree = ast.parse(Path(forward.__file__).read_text())
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(name and any(x in name for x in ("config", "execution", "paper_store")) for name in imports)
    assert forward.REST_URL == "https://data-api.binance.vision"
    assert forward.WS_URL == "wss://data-stream.binance.vision/stream"


def test_actual_portfolio_restored_position_ignores_backfill_lows_then_fresh_bid_exits():
    from kquant_crypto.candidate_policy import load_policy
    from kquant_crypto.candidate_simulation import CandidatePortfolio

    policy = load_policy()
    rules = {s: {"step_size": 0.001, "min_qty": 0.001, "min_notional": 1} for s in forward.SYMBOLS}
    portfolio = CandidatePortfolio(policy, rules, execution="quotes")
    signal = {"mode": "UP_TREND", "unit_net_risk": 1, "entry_reference": 10,
              "stop": 9.5, "target": 15}
    portfolio.decisions["BTCUSDT"] = {"available_at": 3600.5}
    portfolio._reserve("BTCUSDT", signal, 3600)
    portfolio.accept_entries = True
    portfolio.on_quote("BTCUSDT", 10, 10.1, 3601, 1)
    assert "BTCUSDT" in portfolio.positions
    portfolio.drain()
    restored = CandidatePortfolio(policy, rules, execution="quotes")
    restored.restore(deepcopy(portfolio.snapshot()))
    feed = forward.ForwardFeed(restored, state={"last_close": 3600, "sequence": {"BTCUSDT": 1}})
    asyncio.run(feed.backfill(Client(), 7201))
    assert "BTCUSDT" in restored.positions  # REST lows of 9 must not trigger protection.
    assert not restored.drain()["trades"]
    feed.connected = True
    feed.message(quote(sequence=2, b="9", a="9.1"), 7531)
    rows = restored.drain()
    assert len(rows["trades"]) == 1
    assert rows["trades"][0]["exit_time"] == 7531
    assert rows["trades"][0]["exit_reason"] == "stop"
    assert rows["trades"][0]["exit_market_reference"] == 9


def test_failed_commit_is_fatal_not_network_retry(tmp_path):
    class Store:
        calls = 0

        @contextmanager
        def process_lock(self, run_id, *, lease_seconds):
            yield

        def acquire_lock(self, run_id, *, lease_seconds):
            pass

        def clear_stop(self, run_id):
            pass

        def load(self, run_id):
            return {}

        def should_stop(self, run_id):
            return True

        def save(self, *args, **kwargs):
            self.calls += 1
            raise OSError("disk full")

    store = Store()
    with pytest.raises(RuntimeError, match="commit failed"):
        asyncio.run(forward.run_forward(Portfolio(), store, "run", tmp_path))
    assert store.calls == 1


def test_valuation_unavailable_when_position_quotes_disconnect_or_age():
    p, feed = feed_at()
    p.status = lambda: {"positions": {"BTCUSDT": {"quantity": 1}}, "equity": 10000}
    assert feed.valuation_status(3601)["unable_to_value"]
    feed.message(quote(), 3601)
    assert not feed.valuation_status(3631)["unable_to_value"]
    assert feed.valuation_status(3631.01)["stale_quote_symbols"] == ["BTCUSDT"]
    feed.connected = False
    assert feed.valuation_status(3602)["unable_to_value"]
    p.status = lambda: {"positions": {}, "equity": 10000}
    assert not feed.valuation_status(3602)["unable_to_value"]


@pytest.mark.parametrize("bid,ask", [(8.8, 9), (15.1, 15.5)])
def test_actual_quote_entry_gap_liquidates_at_bid_not_ask(bid, ask):
    from kquant_crypto.candidate_policy import load_policy
    from kquant_crypto.candidate_simulation import CandidatePortfolio

    policy = load_policy()
    rules = {s: {"step_size": 0.001, "min_qty": 0.001, "min_notional": 1} for s in forward.SYMBOLS}
    p = CandidatePortfolio(policy, rules, execution="quotes")
    p.decisions["BTCUSDT"] = {"available_at": 3600.5}
    p._reserve("BTCUSDT", {"mode": "UP_TREND", "unit_net_risk": 1,
                          "entry_reference": 10, "stop": 9.5, "target": 15}, 3600)
    p.accept_entries = True
    p.on_quote("BTCUSDT", bid, ask, 3601.125, 1)
    trade = p.drain()["trades"][0]
    assert trade["entry_market_reference"] == ask
    assert trade["exit_market_reference"] == bid
    assert trade["entry_time"] == trade["exit_time"] == 3601.125
    assert trade["exit_price"] == pytest.approx(bid * (1 - p.slippage))


def test_real_store_resume_clears_stop_under_lease_and_releases_writer(tmp_path, monkeypatch):
    from kquant_crypto.candidate_policy import load_policy
    from kquant_crypto.candidate_simulation import CandidatePortfolio
    from kquant_crypto.candidate_simulation_store import CandidateStore

    policy = load_policy()
    p = CandidatePortfolio(policy, {}, execution="quotes")
    store = CandidateStore(tmp_path / "candidate.sqlite3")
    store.create_run("resume", {"policy_hash": policy["policy_hash"]})
    state = p.snapshot()
    state["forward"] = {"last_close": 3600}
    state["status"] = "stopped"
    store.save("resume", state)
    store.request_stop("resume")
    saves = []
    save = store.save

    def recording_save(run_id, state, **rows):
        saves.append(deepcopy(state))
        save(run_id, state, **rows)

    monkeypatch.setattr(store, "save", recording_save)
    result = asyncio.run(forward.run_forward(p, store, "resume", tmp_path / "output", stop_after_seconds=0))
    assert not store.should_stop("resume")
    assert not store._tokens
    assert [s["status"] for s in saves] == ["running", "stopped"]
    assert store.list_runs()[0]["status"] == "stopped"
    assert result["status"] == "stopped"
    assert store.load("resume")["forward"]["last_close"] == 3600
    with store.process_lock("resume"):
        pass


def test_quote_batching_commits_all_buffered_records_with_fill_and_checkpoint(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from kquant_crypto.candidate_simulation_store import CandidateStore

    clock = SimpleNamespace(wall=3601.0, monotonic_value=0.0)
    monkeypatch.setattr(forward, "time", SimpleNamespace(
        time=lambda: clock.wall, monotonic=lambda: clock.monotonic_value))
    p = Portfolio()
    p.count = 0
    original_quote = p.on_quote

    def on_quote(*args):
        original_quote(*args)
        if args[4] == 3:
            p.count += 1
            p.rows["events"].append({"event_id": "fill", "kind": "VIRTUAL_ENTRY", "time": args[3]})
            p.rows["trades"].append({"trade_id": "fill", "time": args[3]})

    p.on_quote = on_quote
    p.snapshot = lambda: {"test_state": True, "count": p.count}
    store = CandidateStore(tmp_path / "batched.sqlite3")
    store.create_run("batch", {})
    store.save("batch", {"test_state": True, "forward": {"last_close": 3600}})
    delivered = []
    commits = []
    real_save = store.save

    def save(run_id, state, **rows):
        commits.append((len(delivered), deepcopy(state), deepcopy(rows)))
        real_save(run_id, state, **rows)

    monkeypatch.setattr(store, "save", save)
    monkeypatch.setattr(store, "should_stop", lambda run_id: len(delivered) == 9)

    class HTTP:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return Client()

        async def __aexit__(self, *args):
            pass

    class Socket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def recv(self):
            index = len(delivered) + 1
            clock.monotonic_value = index * 0.1 if index <= 5 else 5.4 + (index - 6) * 0.1
            clock.wall = 3601 + clock.monotonic_value if index <= 6 else 3901 + (index - 7) * 0.1
            payload = quote(sequence=index) if index <= 6 else kline(forward.SYMBOLS[index - 7], 3600)
            delivered.append(index)
            return json.dumps(payload)

    monkeypatch.setattr(forward.httpx, "AsyncClient", HTTP)
    monkeypatch.setattr(forward, "connect", lambda *args, **kwargs: Socket())
    asyncio.run(forward.run_forward(p, store, "batch", tmp_path / "output"))
    assert [item[0] for item in commits] == [0, 0, 3, 6, 9, 9]
    fill_state, fill_rows = commits[2][1:]
    assert fill_state["count"] == 1
    assert fill_state["forward"]["sequence"]["BTCUSDT"] == 3
    assert [r["sequence"] for r in fill_rows["events"] if r["kind"] == "MARKET_QUOTE"] == [1, 2, 3]
    assert fill_rows["trades"][0]["trade_id"] == "fill"
    assert any(r["kind"] == "VIRTUAL_ENTRY" for r in fill_rows["events"])
    all_rows = store.report_data("batch")
    quotes = [r for r in all_rows["events"] if r["kind"] == "MARKET_QUOTE"]
    assert sorted(r["sequence"] for r in quotes) == [1, 2, 3, 4, 5, 6]
    assert all_rows["state"]["forward"]["sequence"]["BTCUSDT"] == 6
    assert all_rows["state"]["forward"]["last_close"] == 3900


def test_ingestion_does_not_hide_portfolio_programming_error():
    p, feed = feed_at()

    def broken_quote(*args):
        raise KeyError("portfolio bug")

    p.on_quote = broken_quote
    with pytest.raises(KeyError, match="portfolio bug"):
        feed.message(quote(), 3601)
