"""Offline scope/normalization/budget checks; no SDK, network, or .env access."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

import probe_market_readiness as probe

UTC = timezone.utc
AS_OF = datetime(2026, 10, 7, 11, 0, tzinfo=UTC)
PROFILE = {"name": "VERIFIED_SDK_NAIVE_ASIA_SHANGHAI", "naive_timezone": "Asia/Shanghai",
           "evidence_sha256": "a" * 64}
MANIFEST = {"items": [{"symbol": "NVDA", "provider_symbol": "NVDA.US", "identity_status": "verified"},
                       {"symbol": "GWH", "provider_symbol": "GWH.US", "identity_status": "verified"},
                       {"symbol": "$COMP", "provider_symbol": None, "identity_status": "identity_unconfirmed"}]}
EXPIRY = date(2026, 10, 12)
CALL, PUT = "NVDA261012C00100000.US", "NVDA261012P00100000.US"


class FakeClock:
    def __init__(self):
        self.elapsed = 0.0
        self.waits = []
    def monotonic(self):
        return self.elapsed
    def now(self):
        return AS_OF + timedelta(seconds=self.elapsed)
    def sleep(self, delay):
        self.waits.append(delay)
        self.elapsed += delay


class FakeQuotes:
    def __init__(self, *, expiries=None):
        self.calls = []
        self.expiries = expiries if expiries is not None else [date(2026, 10, 9), EXPIRY]
    def __call__(self, method, *args):
        self.calls.append((method, args))
        if method == "trading_session":
            return [SimpleNamespace(market="US", trade_sessions=[SimpleNamespace(
                begin_time=time(9, 30), end_time=time(16), trade_session="Intraday")])]
        if method == "trading_days":
            return SimpleNamespace(trading_days=[AS_OF.date()], half_trading_days=[])
        if method == "static_info":
            return [SimpleNamespace(symbol=code, name_en="NVIDIA" if code == "NVDA.US" else "Native GWH",
                                    currency="USD", exchange="NASDAQ", lot_size=1, stock_derivatives=["Option"],
                                    access_token="SHOULD_NOT_CAPTURE") for code in args[0]]
        if method == "quote":
            return [SimpleNamespace(symbol=code, last_done=Decimal("100.00000000000000001"),
                prev_close=Decimal("99.01"), timestamp=AS_OF.astimezone(probe.ZoneInfo("Asia/Shanghai")).replace(tzinfo=None),
                trade_status="Normal" if code == "NVDA.US" else "Halted",
                secret="SHOULD_NOT_CAPTURE") for code in args[0]]
        if method == "option_chain_expiry_date_list":
            return self.expiries
        if method == "option_chain_info_by_date":
            return [SimpleNamespace(price=Decimal("100"), call_symbol=CALL, put_symbol=PUT, standard=True)]
        if method == "calc_indexes":
            return [SimpleNamespace(symbol=code, delta=Decimal("0.51234567890123456789"), gamma=Decimal(".01"))
                    for code in args[0]]
        if method == "option_quote":
            return [SimpleNamespace(symbol=code, expiry_date=EXPIRY, underlying_symbol="NVDA.US",
                contract_multiplier=Decimal("100"), contract_size=Decimal("100"),
                strike_price=Decimal("100"), direction="Call" if code == CALL else "Put", timestamp=AS_OF)
                for code in args[0]]
        if method == "depth":
            return SimpleNamespace(bids=[SimpleNamespace(position=1, price=Decimal("1.00"), volume=5, order_num=2)],
                                   asks=[SimpleNamespace(position=1, price=Decimal("1.04"), volume=8, order_num=2)])
        pytest.fail("Unexpected non-quote interface: " + method)


def execute(fake=None, **kwargs):
    clock, fake = FakeClock(), fake or FakeQuotes()
    report = probe.execute_quote_probe(fake, MANIFEST, "NVDA", PROFILE, now=clock.now,
                                       sleeper=clock.sleep, monotonic=clock.monotonic, **kwargs)
    return report, fake, clock


@pytest.mark.parametrize('rows', [[], [SimpleNamespace(symbol='WRONG.US')]])
def test_missing_or_wrong_quote_stops_before_option_discovery(rows):
    fake = FakeQuotes()
    def fetch(method, *args):
        if method == 'quote':
            fake.calls.append((method, args))
            return rows
        return fake(method, *args)
    report, _, _ = execute(fetch)
    assert report['contract_discovery']['state'] == 'UNDERLYING_QUOTE_UNAVAILABLE_OR_SCOPE_MISMATCH'
    assert not any(method.startswith('option_') for method, _ in fake.calls)


@pytest.mark.parametrize('has_bars', [False, True])
def test_opt_in_minute_layer_precedes_chain_without_claiming_closed(has_bars):
    fake = FakeQuotes()
    def fetch(method, *args):
        if method == 'candlesticks':
            fake.calls.append((method, args))
            return [SimpleNamespace(timestamp=AS_OF, open=100, high=101, low=99, close=100)] if has_bars else []
        return fake(method, *args)
    report, _, _ = execute(fetch, include_minute=True)
    methods = [method for method, _ in fake.calls]
    assert methods.index('quote') < methods.index('candlesticks')
    if has_bars:
        assert methods.index('candlesticks') < methods.index('option_chain_expiry_date_list')
    else:
        assert report['contract_discovery']['state'] == 'MINUTE_RESPONSE_EMPTY'
        assert 'option_chain_expiry_date_list' not in methods
    assert report['requests'] <= 12


def test_unknown_access_code_stops_after_first_attempt():
    calls = []
    def rejected(method, *args):
        calls.append(method)
        error = RuntimeError('redacted')
        error.code = 403208
        raise error
    report, _, _ = execute(rejected)
    assert len(calls) == 1
    assert report['status'] == 'BLOCKED_ACCESS_RESPONSE_UNCLASSIFIED'
    assert report['contract_discovery']['state'] == 'NOT_EXECUTED_ACCESS_BLOCKED'


@pytest.mark.parametrize('failed,state', [('option_chain_expiry_date_list', 'EXPIRY_QUERY_UNAVAILABLE'),
                                         ('option_chain_info_by_date', 'CHAIN_QUERY_UNAVAILABLE')])
def test_provider_failure_is_not_absence_of_matching_contract(failed, state):
    fake = FakeQuotes()
    def fetch(method, *args):
        if method == failed:
            raise TimeoutError('timeout')
        return fake(method, *args)
    report, _, _ = execute(fetch)
    assert report['contract_discovery']['state'] == state
    assert report['status'] == 'STOPPED_PROVIDER_ERROR'
    assert report['failed_interface'] == 'QuoteContext.' + failed


@pytest.mark.parametrize('failed', ['trading_session', 'trading_days', 'static_info',
                                   'quote', 'calc_indexes', 'option_quote', 'depth'])
def test_any_provider_exception_stops_subsequent_calls(failed):
    fake = FakeQuotes()
    calls = []
    def fetch(method, *args):
        calls.append(method)
        if method == failed:
            raise RuntimeError('fixture unavailable')
        return fake(method, *args)
    report, _, _ = execute(fetch)
    assert calls[-1] == failed
    assert calls.count(failed) == 1
    assert report['requests'] == len(calls)
    assert report['status'] == 'STOPPED_PROVIDER_ERROR'
    assert report['failed_interface'] == 'QuoteContext.' + failed
    assert report['contract_discovery']['qualification_verified'] is False


def test_whitelist_preserves_decimal_and_rejects_unverified_naive_timestamp():
    row = SimpleNamespace(last_done=Decimal("1.12345678901234567890123456789"), timestamp=datetime(2026, 10, 7, 19),
                          access_token="SHOULD_NOT_CAPTURE")
    captured = probe.fields(row, ("last_done", "timestamp"), probe.timestamp_profile())
    assert captured["last_done"]["raw"] == "1.12345678901234567890123456789"
    assert captured["timestamp"]["normalization_state"] == "UNVERIFIED_NAIVE_TIMESTAMP"
    assert "utc" not in captured["timestamp"]
    assert "SHOULD_NOT_CAPTURE" not in json.dumps(captured)
    verified = probe.native_value(row.timestamp, PROFILE)
    assert verified["utc"] == "2026-10-07T11:00:00+00:00"


def test_scope_unknown_identity_and_outside_manifest_never_guessed():
    with pytest.raises(ValueError, match="IDENTITY_UNVERIFIED"):
        probe.select_scope(MANIFEST, "$COMP")
    with pytest.raises(ValueError, match="NOT_UNIQUE"):
        probe.select_scope(MANIFEST, "SPY")


def test_expiry_and_chain_choice_are_bound_to_native_scope():
    assert probe.choose_expiry([date(2026, 10, 9), EXPIRY, date(2026, 10, 16)], AS_OF.date()) == EXPIRY
    assert probe.choose_expiry([date(2026, 10, 9), date(2026, 10, 16)], AS_OF.date()) is None
    chain = [SimpleNamespace(price=Decimal("100"), call_symbol="MSFT261012C00100000.US",
                            put_symbol="NVDA261009P00100000.US", standard=True),
             SimpleNamespace(price=Decimal("101"), call_symbol=CALL, put_symbol=PUT, standard=False),
             SimpleNamespace(price=Decimal("100"), call_symbol=CALL, put_symbol=PUT, standard=True)]
    chosen = probe.choose_chain_contracts(chain, "NVDA.US", EXPIRY, Decimal("100"))
    assert [row["symbol"] for row in chosen] == [CALL, PUT]
    assert all(row["source_chain_ordinal"] == 2 for row in chosen)


def test_complete_fact_capture_is_bounded_and_never_promotes_raw_units_or_time():
    report, fake, clock = execute()
    assert report["requests"] == 11 <= 12
    assert clock.elapsed == 10.0 and all(delay >= 1.0 for delay in clock.waits)
    assert report["contract_discovery"]["selected_contracts"][0]["symbol"] == CALL
    assert not report["contract_discovery"]["standard_deliverable_source_review_verified"]
    assert all(row["underlying_matches_scope"] and row["returned_code_was_requested"]
               for row in report["native_option_identity_checks"])
    assert report["local_calendar"]["phase"] == "PRE_MARKET"
    assert not report["clock_precision_verified"] and not report["production_admission_verified"]
    assert not report["underlying_time_check"]["fresh_bbo_proven"]
    depths = [row for row in report["observations"] if row["interface"] == "QuoteContext.depth"]
    assert all(row["raw_volume_not_assumed_contract_count"] for row in depths)
    assert "SHOULD_NOT_CAPTURE" not in json.dumps(report)


def test_no_matching_dte_stops_contract_probes_without_faking_an_expiry():
    report, fake, clock = execute(FakeQuotes(expiries=[date(2026, 10, 9), date(2026, 10, 16)]))
    assert report["requests"] == 5
    assert report["contract_discovery"]["state"] == "NO_MATCHING_RETURNED_CALENDAR_DTE"
    assert not any(method in {"option_quote", "calc_indexes", "depth"} for method, args in fake.calls)


def test_request_budget_stops_before_more_read_calls():
    report, fake, clock = execute(max_requests=2)
    assert report["status"] == "REQUEST_BUDGET_REACHED"
    assert report["requests"] == len(fake.calls) == 2


def test_work_deadline_prevents_waiting_past_worker_receipt_budget():
    report, fake, clock = execute(run_seconds=1)
    assert report["status"] == "RUN_TIME_BUDGET_REACHED"
    assert report["requests"] == 1 and clock.elapsed == 0.0


def test_local_calendar_does_not_claim_overnight_is_active_premarket():
    clock = FakeClock()
    report = probe.execute_quote_probe(FakeQuotes(), MANIFEST, "NVDA", PROFILE,
        now=lambda: datetime(2026, 10, 7, 7, tzinfo=UTC), sleeper=clock.sleep,
        monotonic=clock.monotonic, max_requests=1)
    assert report["local_calendar"]["phase"] == "CLOSED"


def test_native_last_price_future_time_is_not_bbo_or_clock_proof():
    capture = probe.native_value(AS_OF + timedelta(seconds=5), PROFILE)
    check = probe.native_time_check(capture, AS_OF, AS_OF)
    assert check["state"] == "PROVIDER_TIME_AFTER_RECEIPT"
    assert not check["fresh_bbo_proven"]


def test_auth_error_is_sanitized_and_stops_without_raw_sdk_message():
    class Failure(Exception):
        code = 401003
        kind = "OpenApi"
    def failed(*args):
        raise Failure("SHOULD_NOT_CAPTURE private token URL")
    report, fake, clock = execute(failed)
    assert report["status"] == "BLOCKED_TOKEN_EXPIRED" and report["requests"] == 1
    assert "SHOULD_NOT_CAPTURE" not in json.dumps(report)


def test_clock_receipt_is_immutable_hash_named_without_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "OUT", tmp_path / "evidence/market-readiness")
    monkeypatch.setattr(sys, "argv", ["probe_market_readiness.py", "clock-only"])
    captured = {"status": "MEASURED_UNVERIFIED", "requests": 0,
                "clock_precision_verified": False, "owner_acceptance_created": False}
    observed_timeouts = []
    def fake_child(*args, **kwargs):
        observed_timeouts.append(kwargs["timeout"])
        return SimpleNamespace(returncode=0, stdout=probe.PREFIX + json.dumps(captured), stderr="")
    monkeypatch.setattr(probe.subprocess, "run", fake_child)
    probe.main()
    summary = json.loads(capsys.readouterr().out)
    path = Path(summary["receipt_path"])
    assert observed_timeouts == [6]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == summary["receipt_sha256"]
    assert summary["receipt_sha256"] in path.name
    assert not json.loads(path.read_bytes())["owner_acceptance_created"]


def test_quote_parent_timeout_does_not_claim_zero_actual_requests(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(MANIFEST), encoding="utf-8")
    monkeypatch.setattr(probe, "ROOT", tmp_path)
    monkeypatch.setattr(probe, "OUT", tmp_path / "evidence/market-readiness")
    monkeypatch.setattr(sys, "argv", ["probe_market_readiness.py", "quote-facts", "--manifest", str(manifest_path)])
    def timed_out(*args, **kwargs):
        assert kwargs["timeout"] == 55
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(probe.subprocess, "run", timed_out)
    probe.main()
    summary = json.loads(capsys.readouterr().out)
    receipt = json.loads(Path(summary["receipt_path"]).read_bytes())
    assert receipt["status"] == "QUOTE_PROBE_TIMED_OUT" and receipt["requests"] is None
    assert receipt["child_terminated"]


def test_diagnostic_native_identity_shares_existing_requests_without_contract_scope_change():
    report, fake, clock = execute(diagnostic_symbol="GWH")
    assert report["requests"] == len(fake.calls) == 11
    assert report["diagnostic_scope"]["provider_symbol"] == "GWH.US"
    assert report["diagnostic_scope"]["manifest_sha256"] == report["scope"]["manifest_sha256"]
    stock_calls = [(method, args) for method, args in fake.calls if method in {"static_info", "quote"}]
    assert len(stock_calls) == 3 and all(args[0] == ["NVDA.US", "GWH.US"] for _, args in stock_calls)
    discovery = [(method, args) for method, args in fake.calls if method.startswith("option_chain_")]
    assert all(args[0] == "NVDA.US" for _, args in discovery)
    assert all(candidate["symbol"].startswith("NVDA") for candidate in report["contract_discovery"]["selected_contracts"])
    assert len(report["diagnostic_response_checks"]) == 3
    assert all(check["response_scope_verified"] for check in report["diagnostic_response_checks"])
    assert report["diagnostic_response_checks"][0]["fields"]["currency"]["raw"] == "USD"
    assert report["diagnostic_response_checks"][1]["fields"]["trade_status"]["raw"] == "Halted"
    assert report["diagnostic_response_checks"][1]["fields"]["timestamp"]["utc"] == AS_OF.isoformat()
    assert report["diagnostic_gap_cause"] == "NOT_DETERMINED_BY_QUOTE_SNAPSHOT"
    assert "SHOULD_NOT_CAPTURE" not in json.dumps(report)
    assert all(row["request_symbols"] == ["NVDA.US", "GWH.US"] for row in report["observations"]
               if row["interface"] in {"QuoteContext.static_info", "QuoteContext.quote"})


@pytest.mark.parametrize("symbol", ["$COMP", "SPY", "NVDA"])
def test_invalid_diagnostic_identity_rejects_before_fetch_or_sdk_import(symbol):
    fake = FakeQuotes()
    with pytest.raises(ValueError):
        execute(fake, diagnostic_symbol=symbol)
    assert fake.calls == []
    arguments = SimpleNamespace(symbol="NVDA", diagnostic_symbol=symbol)
    with pytest.raises(ValueError):
        probe.run_quote_worker(arguments, MANIFEST, PROFILE)


def test_missing_diagnostic_native_response_is_not_guessed_or_treated_as_verified():
    fake = FakeQuotes()
    def primary_only(method, *args):
        rows = fake(method, *args)
        return [row for row in rows if row.symbol == "NVDA.US"] if method in {"quote", "static_info"} else rows
    report, _, _ = execute(primary_only, diagnostic_symbol="GWH")
    assert report["requests"] == 11
    assert all(not check["response_scope_verified"] and check["matching_native_rows"] == 0
               for check in report["diagnostic_response_checks"])
    assert report["underlying_response_scope_verified"]
    assert report["diagnostic_gap_cause"] == "NOT_DETERMINED_BY_QUOTE_SNAPSHOT"


def test_probe_sdk_mapping_pins_quote_only_environment_without_real_context(monkeypatch):
    names = ('LONGBRIDGE_APP_KEY', 'LONGBRIDGE_APP_SECRET', 'LONGBRIDGE_ACCESS_TOKEN')
    values = ('TEST_ONLY_KEY', 'TEST_ONLY_SECRET', 'TEST_ONLY_TOKEN')
    for name, value in zip(names, values):
        monkeypatch.setenv(name, value)
    monkeypatch.setenv('LONGBRIDGE_PAPERTRADING', 'true')
    configurations = []

    def config(*args, **kwargs):
        configurations.append((args, kwargs))
        return 'TEST_ONLY_CONFIG'

    fake_context = SimpleNamespace(trading_session=lambda: [])
    monkeypatch.setitem(sys.modules, 'longbridge.openapi', SimpleNamespace(
        Config=SimpleNamespace(from_apikey=config), QuoteContext=lambda _: fake_context,
        Market=SimpleNamespace(US='TEST_ONLY_US'), CalcIndex=SimpleNamespace(),
        Period=SimpleNamespace(Min_1='TEST_ONLY_MINUTE'),
        AdjustType=SimpleNamespace(NoAdjust='TEST_ONLY_NO_ADJUST'),
        TradeSessions=SimpleNamespace(Intraday='TEST_ONLY_INTRADAY')))
    execute_probe = probe.execute_quote_probe
    fake_clock = FakeClock()
    monkeypatch.setattr(probe, 'execute_quote_probe', lambda *args, **kwargs: execute_probe(
        *args, **kwargs, now=lambda: AS_OF, sleeper=fake_clock.sleep, monotonic=fake_clock.monotonic))
    arguments = SimpleNamespace(symbol='NVDA', diagnostic_symbol=None, max_requests=1, run_seconds=1)
    result = probe.run_quote_worker(arguments, MANIFEST, PROFILE)
    assert result['requests'] == 1
    assert len(configurations) == 1
    assert configurations[0][0] == values
    assert configurations[0][1]['enable_print_quote_packages'] is False
    assert configurations[0][1].get('enable_papertrading') is False
