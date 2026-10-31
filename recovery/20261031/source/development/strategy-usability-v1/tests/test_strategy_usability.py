from copy import deepcopy
from datetime import timedelta
from importlib.util import spec_from_file_location, module_from_spec

import pytest

from bootstrap import BASE
from kquant import options_one_minute as common
from kquant import options_opening_momentum as s0
from kquant import options_intraday_comparison as compare
from kquant.options_research_diagnostics import option_cost, greek_scenario, path_label

spec = spec_from_file_location("s0_existing_test_inputs", BASE / "tests/test_options_opening_momentum.py")
fixtures = module_from_spec(spec)
spec.loader.exec_module(fixtures)


def inputs(right="CALL", minutes=5):
    args = fixtures.inputs(right, minutes)
    native = dict(symbol="TEST", provider_symbol="TEST.US", currency="USD",
        source="LONGBRIDGE_SECURITY_STATIC_INFO", received_at=args["opening"].isoformat())
    native["source_hash"] = common.digest(native)
    args["reference"]["raw_quote"] = dict(symbol="TEST", currency="USD", currency_evidence=native)
    for row in args["bars"]:
        row["sdk_evidence"] = dict(provider_symbol="TEST.US", adjustment="NoAdjust", interface="QuoteContext.candlesticks")
    return args


def pair(args):
    return compare.evaluate_comparison_pair(**{k: v for k, v in args.items() if k != "right"})


@pytest.mark.parametrize("right", ["CALL", "PUT"])
@pytest.mark.parametrize("minutes", [5, 10, 15, 20, 25])
def test_exact_s0_payload_unchanged_and_subset(right, minutes):
    args = inputs(right, minutes)
    for row in pair(args):
        baseline = s0.evaluate(**{**args, "right": row["right"]})
        nested = row.pop("strategy_comparison")
        assert row == baseline
        if baseline["state"] == "NUMERIC_PASS":
            assert nested["s1"]["state"] == "NUMERIC_PASS"
        assert nested["cohort"] == "PAIRED_POLICY_COMPARISON"


@pytest.mark.parametrize("right,previous", [("CALL", 110), ("PUT", 90)])
def test_direction_is_only_rule_difference(right, previous):
    args = inputs(right)
    args["reference"]["previous_close"] = previous
    result = next(row for row in pair(args) if row["right"] == right)
    assert result["state"] == "NO_TRIGGER"
    assert result["strategy_comparison"]["s1"]["state"] == "NUMERIC_PASS"
    assert result["strategy_comparison"]["s1"]["conditions"]["previous_close_direction"] == "NOT_REQUIRED"


def test_missing_prev_does_not_block_s1_or_mean_s0_reject():
    args = inputs()
    args["reference"]["previous_close"] = None
    result = pair(args)[0]
    assert result["state"] == "INCOMPLETE"
    assert result["strategy_comparison"]["s1"]["state"] == "NUMERIC_PASS"
    assert result["strategy_comparison"]["cohort"] == "S1_INTRADAY_ONLY_DATA"


@pytest.mark.parametrize("bad", ["identity", "currency", "scale", "missing", "zero", "conflict", "future", "open"])
def test_s1_required_inputs_fail_closed(bad):
    args = inputs()
    args["reference"]["previous_close"] = None
    if bad == "identity":
        args["reference"]["raw_quote"]["symbol"] = "OTHER"
    if bad == "currency":
        args["reference"]["raw_quote"]["currency_evidence"]["currency"] = "HKD"
    if bad == "scale":
        args["bars"][0]["sdk_evidence"]["adjustment"] = "ForwardAdjust"
    if bad == "missing":
        args["bars"].pop(2)
    if bad == "zero":
        for row in args["bars"]:
            row.update(open=100, high=100, low=100, close=100)
    if bad == "conflict":
        extra = deepcopy(args["bars"][0])
        extra.update(open=100.2, received_at=args["now"].isoformat())
        args["bars"].append(extra)
    if bad == "future":
        args["bars"][0]["received_at"] = (args["now"] + timedelta(seconds=1)).isoformat()
    if bad == "open":
        args["bars"][0]["open"] = None
    assert pair(args)[0]["strategy_comparison"]["s1"]["state"] == "INCOMPLETE"


def test_exact_deadline_and_revision_identity():
    args = inputs()
    first = pair(args)[0]["strategy_comparison"]["s1"]
    args["checkpoint"] = args["opening"] + timedelta(minutes=5)
    args["now"] = args["opening"] + timedelta(minutes=10)
    expired = pair(args)[0]["strategy_comparison"]["s1"]
    assert expired["state"] == "EXPIRED"
    assert expired["deadline_at"] == first["deadline_at"]
    args = inputs()
    args["bars"][-1]["close"] += .01
    revised = pair(args)[0]["strategy_comparison"]["s1"]
    assert revised["evaluation_id"] != first["evaluation_id"]


def test_amplitude_is_not_shape_or_new_gate():
    a = compare.amplitude(dict(open=100, high=100.05, low=99.99, close=100.04), 100)
    b = compare.amplitude(dict(open=100, high=105, low=99, close=104), 100)
    assert b["range_bps"] / a["range_bps"] == pytest.approx(100)
    assert a["range_vs_prior_atr"] is None
    assert a["role"] == "DIAGNOSTIC_ONLY"


def quote(now):
    return dict(bid=2.4, ask=2.6, delta=.5, multiplier=100, currency="USD",
                multiplier_verified=True, price_unit_verified=True, currency_verified=True,
                bbo_received_at=now.isoformat(), greeks_received_at=now.isoformat())


def test_cost_unknown_and_local_arithmetic():
    now = inputs()["now"]
    result = option_cost(quote(now), now=now)
    assert result["premium_cash_reference"] == 260
    assert result["spread_cash_reference"] == pytest.approx(20)
    assert result["spread_equivalent_underlying_move"] == pytest.approx(.4)
    assert result["spread_pct_ask"] == pytest.approx(.076923076923)
    assert result["round_trip_cost_per_unit"] is None
    fees = dict(currency="USD", source_hash="TEST_ONLY", fee_in=1, fee_out=1, slippage_in=.01, slippage_out=.01)
    assert option_cost(quote(now), now=now, fees=fees)["round_trip_cost_per_unit"] == pytest.approx(.24)
    assert option_cost({**quote(now), "multiplier_verified": False}, now=now)["premium_cash_reference"] is None


@pytest.mark.parametrize("change", [{"bid": 3}, {"ask": None}, {"delta": 0}])
def test_bad_option_inputs(change):
    now = inputs()["now"]
    assert option_cost({**quote(now), **change}, now=now)["cost_equivalent_underlying_move"] is None
    assert option_cost(quote(now), now=now + timedelta(seconds=4))["spread"] is None
    assert option_cost(quote(now), now=now - timedelta(seconds=1))["spread"] is None


def test_greek_units_are_explicit():
    now = inputs()["now"]
    greeks = dict(delta=.5, gamma=.1, vega=.2, theta=-.3, received_at=now.isoformat(),
                  vega_unit="PER_IV_PERCENTAGE_POINT", theta_unit="PER_CALENDAR_DAY")
    args = dict(now=now, underlying_change=1, iv_percentage_points=2, elapsed_calendar_days=.5)
    assert greek_scenario(greeks, **args)["value_change"] == pytest.approx(.8)
    assert greek_scenario({**greeks, "vega_unit": "UNKNOWN"}, **args)["value_change"] is None


def test_label_uses_delayed_open_and_complete_future_path():
    args = inputs()
    event = pair(args)[0]["strategy_comparison"]["s1"]
    rows = deepcopy(args["bars"])
    for i in range(5, 70):
        start = args["opening"] + timedelta(minutes=i)
        rows.append(dict(symbol="TEST", interval="1m", open_at=start.isoformat(),
            available_at=(start + timedelta(minutes=1)).isoformat(),
            received_at=(start + timedelta(minutes=1, milliseconds=50)).isoformat(),
            closed=True, open=105, high=105.5, low=104.8, close=105.2))
    asof = args["opening"] + timedelta(minutes=71)
    label = path_label(event, rows, ready_at=args["now"], as_of=asof)
    assert label["reference_at"] == (args["opening"] + timedelta(minutes=7)).isoformat()
    assert label["state"] == "COMPLETE"
    assert label["y60_pct"] == pytest.approx(.2 / 105)
    assert path_label(event, rows, ready_at=args["now"], as_of=args["now"])["y60_pct"] is None
    rows = [row for row in rows if row["open_at"] != (args["opening"] + timedelta(minutes=10)).isoformat()]
    assert path_label(event, rows, ready_at=args["now"], as_of=asof)["state"] == "PATH_INCOMPLETE"
    assert path_label(event, rows, ready_at=args["opening"] + timedelta(minutes=9), as_of=asof)["state"] == "MISSED_REFERENCE_WINDOW"


def test_existing_store_keeps_both_versions_without_s1_qualification(tmp_path):
    from kquant import options_opening_trend_store as store
    import sqlite3
    args = inputs()
    args["reference"]["previous_close"] = None
    rows = pair(args)
    path = tmp_path / "isolated-research.sqlite3"
    store.initialize(path)
    store.persist(rows, path)
    assert store.detail(rows[0]["evaluation_id"], path)["strategy_comparison"]["s1"]["state"] == "NUMERIC_PASS"
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM qualified_claims").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM qualification_jobs").fetchone()[0] == 1
        assert db.execute("SELECT e.policy_hash FROM evaluations e JOIN qualification_jobs USING(evaluation_id)").fetchone()[0] == compare.load_policy()["policy_hash"]
    store.persist(rows, path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 4


def test_s1_reference_uses_actual_lane_without_claims(tmp_path):
    from kquant import options_opening_trend_store as store, options_opening_trend_jobs as jobs
    from kquant.options_opening_trend_pipeline import step
    from kquant.options_opening_trend_current import current
    import sqlite3
    args = inputs()
    args["reference"]["previous_close"] = None
    rows = pair(args)
    now = args["now"]
    identity = "TEST261006C105000.US"
    class Transport:
        def event(self, *a): return {"event_decision": {"decision": "WARN"}, "trade_eligible": True}
        def expiries(self, *a): return {"expiries": ["2026-10-06"]}
        def chain(self, *a): return {"contracts": [{"call_symbol": identity, "strike_price": 105}]}
        def greeks(self, *a): return {"items": [{"contract_symbol": identity, "delta": .525}]}
        def contract(self, *a): return dict(contract_id=identity, underlying="TEST", right="CALL",
            expiry_date="2026-10-06", strike=105, delta=.525, bid=1, ask=1.01, quote_currency="USD",
            snapshot={"bbo_received_at": now.isoformat(), "calc_received_at": now.isoformat()})
        def spot(self, *a): return {"last": 105, "received_at": now.isoformat()}
        def scope_hash(self): return "scope"
        def current_trend(self, original, stamp): return current(original, args["bars"], now=stamp)
        def approval(self, *a): raise AssertionError("S1_MUST_NOT_REQUEST_OLD_QUALIFIED_APPROVAL")
    path = tmp_path / "research.sqlite3"
    store.initialize(path)
    store.persist(rows, path)
    for _ in range(6):
        job = jobs.claim(path, now=now)
        assert job is not None
        progress, finished, revision = step(job, Transport(), clock=lambda: now)
        assert jobs.settle(path, job, now=now, progress=progress, finished=finished, revision=revision)
    parent = store.detail(rows[0]["evaluation_id"], path)
    assert parent["state"] == "INCOMPLETE"
    assert parent["strategy_comparison"]["reference_contract"]["contract_id"] == identity
    assert parent["strategy_comparison"]["option_cost"]["premium_cash_reference"] is None
    assert store.current_cards(path=path, session=rows[0]["session"], scope_hash="scope", now=now,
        policy=s0.load_policy())["evaluations"][0]["strategy_comparison"]["reference_contract"]["contract_id"] == identity
    with pytest.raises(ValueError, match="S1_QUALIFIED_PUBLICATION_FORBIDDEN"):
        store.append_revision(rows[0]["strategy_comparison"]["s1"]["evaluation_id"],
            {"state": "QUALIFIED", "checked_at": (now + timedelta(seconds=1)).isoformat()}, path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM qualified_claims").fetchone()[0] == 0
    assert jobs.claim(path, now=common.timestamp(rows[0]["strategy_comparison"]["s1"]["deadline_at"])) is None


def test_both_pass_share_one_contract_collection(tmp_path):
    from kquant import options_opening_trend_store as store
    import sqlite3
    path = tmp_path / "research.sqlite3"
    store.initialize(path)
    store.persist(pair(inputs()), path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM qualification_jobs").fetchone()[0] == 1
        assert db.execute("SELECT e.policy_hash FROM evaluations e JOIN qualification_jobs USING(evaluation_id)").fetchone()[0] == s0.load_policy()["policy_hash"]


def test_post_commit_observation_is_not_computation_or_retry_time(tmp_path):
    from kquant import options_opening_trend_store as store, options_opening_momentum_journal as journal
    from kquant.options_research_availability import record_many
    path = tmp_path / 'research.sqlite3'
    store.initialize(path)
    journal.initialize(path)
    args = inputs()
    rows = pair(args)
    store.persist(rows, path)
    assert 'research_ready_at' not in store.detail(rows[0]['evaluation_id'], path)
    ready = args['now'] + timedelta(seconds=2)
    record_many(path, rows, observed_at=ready)
    record_many(path, rows, observed_at=ready + timedelta(seconds=12))
    result = store.detail(rows[0]['evaluation_id'], path)
    assert result['research_ready_at'] == ready.isoformat()
    assert result['evaluated_at'] == args['now'].isoformat()
    assert result['deadline_at'] == rows[0]['deadline_at']


def test_live_research_projection_bounded_without_losing_detail(tmp_path):
    from kquant import options_opening_trend_store as store
    from kquant import options_opening_momentum_journal as journal
    path = tmp_path / 'research.sqlite3'
    store.initialize(path)
    journal.initialize(path)
    args = inputs()
    args['reference']['previous_close'] = None
    rows = []
    for i in range(100):
        row = deepcopy(pair(args)[0])
        row.update(symbol=f'TEST{i}', evaluation_id=f'parent-{i}')
        child = row['strategy_comparison']['s1']
        child.update(symbol=f'TEST{i}', evaluation_id=f'child-{i}')
        rows.append(row)
    store.persist(rows, path)
    result = store.current_cards(path=path, session=rows[0]['session'], scope_hash='scope', now=args['now'], policy=s0.load_policy())
    assert result['evaluations_total'] == 100
    assert result['evaluations_deferred']
    assert len(common.canonical(result).encode('utf-8')) < 40000
    assert store.detail('parent-99', path)['strategy_comparison']['s1']['factor_evidence']
    assert result['candidates'] == []
