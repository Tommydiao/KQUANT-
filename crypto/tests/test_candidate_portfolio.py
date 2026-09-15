"""Independent execution-contract tests, not market-performance evidence.

Every signal comes from the real kernel after 251 complete hours. Synthetic
OHLCV fixtures exercise event paths without relaxing the frozen policy.
"""

from __future__ import annotations

import builtins
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType

import pytest

from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.candidate_simulation import CandidatePortfolio
from kquant_crypto.strategy_dual_mode_v1 import Bar, DualRegimeKernel, RANGE, UP_TREND


SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
OFFSET = 12 * 3600
SIGNAL_START = OFFSET + 251 * 3600
RULES = {s: {"step_size": 0.001, "min_qty": 0.001, "min_notional": 5}
         for s in SYMBOLS}


def bar(start, close, *, open=None, high=None, low=None):
    opening = close if open is None else open
    return Bar(start, opening, max(opening, close) + .1 if high is None else high,
               min(opening, close) - .1 if low is None else low, close, 1)


def aggregate(parts):
    assert len(parts) == 12
    assert parts[0].start % 3600 == 0
    assert all(b.start == parts[0].start + i * 300 for i, b in enumerate(parts))
    return Bar(parts[0].start, parts[0].open, max(b.high for b in parts),
               min(b.low for b in parts), parts[-1].close, sum(b.volume for b in parts))


def closed_stream(mode, hours=251):
    for hour in range(hours):
        close = 100 + hour if mode == UP_TREND else 100
        parts = [bar(OFFSET + hour * 3600 + i * 300, close) for i in range(12)]
        if mode == RANGE and hour == 248:
            parts[0] = bar(parts[0].start, close, high=110, low=90)
        hourly = aggregate(parts)
        for i, current in enumerate(parts):
            yield current, hourly if i == 11 else None


def batch(portfolio, current, hourly=None, *, symbols=SYMBOLS, allow=True, now=None):
    portfolio.on_closed_batch(
        {s: current for s in symbols},
        {} if hourly is None else {s: hourly for s in symbols},
        current.start + 300 if now is None else now, allow_entries=allow,
    )


@pytest.fixture(scope="module")
def warm_states():
    states = {}
    for mode in (UP_TREND, RANGE):
        for candidate in ("A", "B"):
            portfolio = CandidatePortfolio(load_policy(candidate=candidate), deepcopy(RULES))
            for current, hourly in closed_stream(mode):
                batch(portfolio, current, hourly, allow=False)
            assert not portfolio.trades and not portfolio.positions and not portfolio.pending
            assert all(k.ready and k.mode == mode for k in portfolio.kernels.values())
            states[mode, candidate] = json.loads(json.dumps(portfolio.snapshot()))
    return states


def warmed(states, mode=UP_TREND, candidate="A", *, execution="ohlcv", multiplier=1,
           only_mode=None, portfolio_class=CandidatePortfolio):
    portfolio = portfolio_class(load_policy(candidate=candidate), deepcopy(RULES),
                                execution=execution, cost_multiplier=multiplier,
                                only_mode=only_mode)
    # No warmup fills occur, so its closed-data state is scenario-independent.
    # Stamp the destination scenario only on these flat, untraded fixtures.
    state = deepcopy(states[mode, candidate])
    state.update(execution=execution, cost_multiplier=multiplier, only_mode=only_mode)
    portfolio.restore(state)
    return portfolio


def trigger(portfolio, mode=UP_TREND, *, symbols=SYMBOLS):
    if mode == RANGE:
        batch(portfolio, bar(SIGNAL_START, 92.9), symbols=symbols)
        current = bar(SIGNAL_START + 300, 93.1)
    else:
        current = bar(SIGNAL_START, 365, open=350, high=380, low=340)
    batch(portfolio, current, symbols=symbols)
    assert portfolio.pending, portfolio.decisions
    return current.start + 300


def enter_normal(portfolio, mode=UP_TREND, *, symbols=SYMBOLS):
    start = trigger(portfolio, mode, symbols=symbols)
    price = 365 if mode == UP_TREND else 93.1
    batch(portfolio, bar(start, price), symbols=symbols)
    assert portfolio.positions and not portfolio.trades
    return start + 300


def assert_costs(trade, portfolio):
    buy = trade["entry_market_reference"] * (1 + portfolio.slippage)
    sell = trade["exit_market_reference"] * (1 - portfolio.slippage)
    quantity = trade["quantity"]
    fees = quantity * (buy + sell) * portfolio.fee
    assert trade["entry_price"] == pytest.approx(buy)
    assert trade["exit_price"] == pytest.approx(sell)
    assert trade["fees"] == pytest.approx(fees)
    assert trade["net_pnl"] == pytest.approx(quantity * (sell - buy) - fees)
    assert trade["net_r"] == pytest.approx(trade["net_pnl"] / (quantity * trade["unit_net_risk"]))


@pytest.mark.parametrize("mode", [UP_TREND, RANGE])
@pytest.mark.parametrize("candidate", ["A", "B"])
def test_complete_stream_decisions_match_direct_kernel_and_quote_adapter(mode, candidate):
    policy = load_policy(candidate=candidate)
    historical = CandidatePortfolio(policy, deepcopy(RULES))
    quotes = CandidatePortfolio(policy, deepcopy(RULES), execution="quotes")
    direct = DualRegimeKernel(candidate)
    stream = list(closed_stream(mode))
    if mode == UP_TREND:
        stream.append((bar(SIGNAL_START, 365, open=350, high=380, low=340), None))
    else:
        stream.extend([(bar(SIGNAL_START, 92.9), None), (bar(SIGNAL_START + 300, 93.1), None)])
    for current, hourly in stream:
        expected = direct.on_bar(current, hourly)
        batch(historical, current, hourly, allow=False)
        batch(quotes, current, hourly, allow=False)
        for portfolio in (historical, quotes):
            actual = portfolio.decisions["BTCUSDT"]
            assert {key: actual[key] for key in expected} == expected
        if current.start + 300 < OFFSET + 250 * 3600:
            assert not expected["ready"] and expected["signal"] is None
    assert expected["signal"] is not None
    assert historical.kernels["BTCUSDT"].to_dict() == direct.to_dict()
    assert quotes.kernels["BTCUSDT"].to_dict() == direct.to_dict()
    assert expected["signal"]["expected_net_rr"] >= (2 if mode == UP_TREND else 1.5)
    assert not historical.positions and not quotes.positions


def test_next_bar_entry_freezes_plan_and_no_signal_bar_fill(warm_states):
    portfolio = warmed(warm_states)
    start = trigger(portfolio, symbols=("BTCUSDT",))
    plan = deepcopy(portfolio.pending["BTCUSDT"])
    assert not portfolio.positions and portfolio.cash == 10000
    batch(portfolio, bar(start, 367, open=366), symbols=("BTCUSDT",))
    position = portfolio.positions["BTCUSDT"]
    assert position["entry_time"] == start
    assert position["entry_price"] == pytest.approx(366 * 1.0005)
    assert position["stop"] == plan["stop"] and position["target"] == plan["target"]
    assert position["bars_held"] == 1
    assert position["unit_net_risk"] == plan["unit_net_risk"]


@pytest.mark.parametrize("existing", [False, True])
def test_stop_first_when_both_touched_including_entry_bar(warm_states, existing):
    portfolio = warmed(warm_states)
    start = enter_normal(portfolio) if existing else trigger(portfolio)
    plan = deepcopy((portfolio.positions if existing else portfolio.pending)["BTCUSDT"])
    batch(portfolio, bar(start, 365, high=plan["target"] + 1, low=plan["stop"] - 1))
    assert len(portfolio.trades) == 2
    for trade in portfolio.trades:
        assert trade["exit_reason"] == "stop"
        assert trade["exit_market_reference"] == plan["stop"]
        assert trade["net_pnl"] < 0
        assert_costs(trade, portfolio)


def test_open_gap_target_precedes_later_low_and_queued_exit(warm_states):
    portfolio = warmed(warm_states)
    start = enter_normal(portfolio)
    plan = deepcopy(portfolio.positions["BTCUSDT"])
    portfolio.exits.update({s: "timeout" for s in portfolio.positions})
    batch(portfolio, bar(start, 365, open=plan["target"] + 5,
                         high=plan["target"] + 6, low=plan["stop"] - 5))
    assert len(portfolio.trades) == 2
    for trade in portfolio.trades:
        assert trade["exit_reason"] == "gap_target"
        assert trade["exit_time"] == start
        assert trade["exit_market_reference"] == plan["target"]
        assert_costs(trade, portfolio)


def test_open_gap_stop_uses_worse_open(warm_states):
    portfolio = warmed(warm_states)
    start = enter_normal(portfolio)
    stop = portfolio.positions["BTCUSDT"]["stop"]
    batch(portfolio, bar(start, stop - 5, open=stop - 8, low=stop - 9))
    for trade in portfolio.trades:
        assert trade["exit_reason"] == "gap_stop"
        assert trade["exit_market_reference"] == stop - 8
        assert trade["net_r"] < -1
        assert_costs(trade, portfolio)


@pytest.mark.parametrize("direction", ["stop", "target"])
def test_entry_gap_keeps_entry_exit_and_both_costs(warm_states, direction):
    portfolio = warmed(warm_states, RANGE)
    start = trigger(portfolio, RANGE)
    plan = deepcopy(portfolio.pending["BTCUSDT"])
    reference = plan[direction] + (-1 if direction == "stop" else 1)
    batch(portfolio, bar(start, reference))
    assert not portfolio.positions and not portfolio.pending
    assert len(portfolio.trades) == 2
    assert sum(e["kind"] == "VIRTUAL_ENTRY" for e in portfolio.events) == 2
    for trade in portfolio.trades:
        assert trade["exit_reason"] == "entry_gap_" + direction
        assert trade["entry_time"] == trade["exit_time"] == start
        assert trade["net_pnl"] < 0 and trade["fees"] > 0
        assert_costs(trade, portfolio)
    if direction == "stop":
        assert portfolio.kernels["BTCUSDT"].box is None
        assert portfolio.decisions["BTCUSDT"]["mode_invalidated"]


@pytest.mark.parametrize("direction", ["stop", "target"])
def test_quote_immediate_entry_gap_exit_uses_bid(warm_states, direction):
    portfolio = warmed(warm_states, RANGE, execution="quotes")
    time = trigger(portfolio, RANGE, symbols=("BTCUSDT",))
    plan = portfolio.pending["BTCUSDT"]
    ask = plan[direction] + (-1 if direction == "stop" else 1)
    bid = ask - .2
    portfolio.on_quote("BTCUSDT", bid, ask, time + 1, sequence=1)
    trade = portfolio.trades[0]
    assert trade["entry_market_reference"] == ask
    assert trade["exit_market_reference"] == bid
    assert trade["exit_reason"] == "entry_gap_" + direction
    assert trade["net_pnl"] < 0
    assert_costs(trade, portfolio)


def test_quote_entry_waits_for_availability_and_does_not_reuse_old_ohlc(warm_states):
    portfolio = warmed(warm_states, execution="quotes")
    time = trigger(portfolio, symbols=("BTCUSDT",))
    portfolio.on_quote("BTCUSDT", 364.9, 365, time, sequence=1)
    assert not portfolio.positions
    portfolio.on_quote("BTCUSDT", 364.9, 365, time + 1, sequence=2)
    assert "BTCUSDT" in portfolio.positions
    stop = portfolio.positions["BTCUSDT"]["stop"]
    batch(portfolio, bar(time, 365, low=stop - 50), symbols=("BTCUSDT",))
    assert not portfolio.trades
    portfolio.on_quote("BTCUSDT", stop - 1, stop, time + 301, sequence=3)
    assert portfolio.trades[0]["exit_market_reference"] == stop - 1
    assert portfolio.trades[0]["exit_reason"] == "stop"


def test_two_positions_fixed_order_and_reservations_obey_frozen_risk(warm_states):
    portfolio = warmed(warm_states)
    start = trigger(portfolio, symbols=tuple(reversed(SYMBOLS)))
    assert list(portfolio.pending) == ["BTCUSDT", "ETHUSDT"]
    assert any(e["kind"] == "ENTRY_REJECTED" and e["symbol"] == "SOLUSDT"
               and e["reason"] == "position_limit" for e in portfolio.events)
    pending = list(portfolio.pending.values())
    assert sum(p["risk_amount"] for p in pending) <= 10000 * .005
    assert all(p["risk_amount"] <= 10000 * .0025 for p in pending)
    assert all(p["reserved_cash"] <= 10000 * .25 for p in pending)
    assert sum(p["reserved_cash"] for p in pending) <= portfolio.cash
    batch(portfolio, bar(start, 365))
    assert list(portfolio.positions) == ["BTCUSDT", "ETHUSDT"]
    spent = sum(p["quantity"] * p["entry_price"] + p["entry_fee"]
                for p in portfolio.positions.values())
    assert portfolio.cash == pytest.approx(10000 - spent)
    assert portfolio.cash >= 0


def test_extreme_entry_gaps_never_spend_cash_reserved_for_other_symbol(warm_states):
    portfolio = warmed(warm_states)
    start = trigger(portfolio)
    reserved = deepcopy(portfolio.pending)
    batch(portfolio, bar(start, 20000))
    assert portfolio.cash >= 0 and len(portfolio.trades) == 2
    for trade in portfolio.trades:
        assert trade["quantity"] <= reserved[trade["symbol"]]["quantity"]
        assert trade["quantity"] * trade["entry_price"] * (1 + portfolio.fee) <= 2500
        assert_costs(trade, portfolio)


def test_floating_daily_loss_schedules_exit_without_lowering_policy(warm_states):
    portfolio = warmed(warm_states)
    start = enter_normal(portfolio)
    target = portfolio.positions["BTCUSDT"]["target"]
    # Carry unrealized gains over UTC midnight, then lose >1% while both
    # positions remain above their original stops and below their targets.
    parts = [bar(SIGNAL_START, 365, open=350, high=380, low=340),
             bar(SIGNAL_START + 300, 365)]
    for part in range(2, 12):
        current = bar(SIGNAL_START + part * 300, target - 1)
        parts.append(current)
        batch(portfolio, current, aggregate(parts) if part == 11 else None)
    assert not portfolio.trades
    midnight = SIGNAL_START + 3600
    assert midnight % 86400 == 0
    current = bar(midnight, 365, open=target - 1, high=target - .5)
    batch(portfolio, current)
    assert portfolio.policy["daily_loss_limit"] == .01
    assert portfolio.value() < portfolio.day_start * .99
    assert portfolio.day_paused
    assert set(portfolio.exits.values()) == {"daily_loss"}
    assert len(portfolio.positions) == 2 and not portfolio.trades
    batch(portfolio, bar(midnight + 300, 365))
    assert len(portfolio.trades) == 2
    assert all(t["exit_reason"] == "daily_loss" for t in portfolio.trades)


@pytest.mark.parametrize("open_stop", [False, True])
def test_range_stop_invalidates_once_and_excludes_exit_bar_from_cooldown(warm_states, open_stop):
    portfolio = warmed(warm_states, RANGE)
    start = enter_normal(portfolio, RANGE)
    stop = portfolio.positions["BTCUSDT"]["stop"]
    current = bar(start, 93.1, open=stop - 1 if open_stop else 93.1, low=stop - 1)
    batch(portfolio, current)
    kernel = portfolio.kernels["BTCUSDT"]
    assert kernel.box is None and kernel.cooldown_remaining == 12
    assert portfolio.decisions["BTCUSDT"]["mode_invalidated"]
    state = json.loads(json.dumps(portfolio.snapshot()))
    resumed = CandidatePortfolio(portfolio.policy, deepcopy(RULES))
    resumed.restore(state)
    parts = [bar(SIGNAL_START, 92.9), bar(SIGNAL_START + 300, 93.1),
             bar(SIGNAL_START + 600, 93.1), current]
    for n in range(1, 13):
        current = bar(start + n * 300, 93.1)
        parts.append(current)
        hourly = aggregate(parts[-12:]) if (current.start + 300) % 3600 == 0 else None
        batch(resumed, current, hourly)
        assert resumed.kernels["BTCUSDT"].cooldown_remaining == 12 - n
        assert not resumed.decisions["BTCUSDT"]["mode_invalidated"]
    assert not resumed.pending


@pytest.mark.parametrize("difference", ["cost", "mode", "rules", "execution", "policy"])
def test_restore_rejects_scenario_mismatch(warm_states, difference):
    source = warmed(warm_states, multiplier=2, only_mode=UP_TREND)
    state = json.loads(json.dumps(source.snapshot()))
    policy, rules = deepcopy(source.policy), deepcopy(RULES)
    if difference == "rules":
        rules["BTCUSDT"]["step_size"] = .01
    if difference == "policy":
        policy["policy_hash"] = "different-policy"
    target = CandidatePortfolio(policy, rules,
                                execution="quotes" if difference == "execution" else "ohlcv",
                                cost_multiplier=1 if difference == "cost" else 2,
                                only_mode=None if difference == "mode" else UP_TREND)
    before = deepcopy(target.snapshot())
    with pytest.raises(ValueError, match="Checkpoint"):
        target.restore(state)
    assert target.snapshot() == before


def test_json_restore_pending_then_fill_matches_uninterrupted_and_deduplicates(warm_states):
    original = warmed(warm_states, multiplier=2, only_mode=UP_TREND)
    start = trigger(original)
    restored = CandidatePortfolio(original.policy, deepcopy(RULES), cost_multiplier=2, only_mode=UP_TREND)
    restored.restore(json.loads(json.dumps(original.snapshot())))
    original.drain()
    current = bar(start, 365)
    for portfolio in (original, restored):
        batch(portfolio, current)
    assert original.snapshot() == restored.snapshot()
    assert original.drain() == restored.drain()
    before = deepcopy(restored.snapshot())
    batch(restored, current)
    assert restored.snapshot() == before
    assert not restored.drain()["events"]


def test_candidate_import_and_trade_do_not_touch_original_execution_or_stores(monkeypatch, warm_states):
    forbidden = {
        "binance_execution", "execution_service", "execution_orchestrator", "execution_store",
        "paper_store", "shadow_store", "validation_store", "evaluation_store", "evaluation_agent",
    }

    def forbidden_access(name):
        raise AssertionError("original execution/evidence accessed: " + name)

    for name in forbidden:
        module = ModuleType("kquant_crypto." + name)
        module.__getattr__ = forbidden_access
        monkeypatch.setitem(sys.modules, module.__name__, module)
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if any(part in forbidden for part in name.split(".")) or any(part in forbidden for part in fromlist or ()):
            raise AssertionError("original execution/evidence imported: " + name)
        return original_import(name, globals, locals, fromlist, level)

    policy = load_policy()
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    path = Path(__file__).resolve().parents[1] / "kquant_crypto" / "candidate_simulation.py"
    spec = importlib.util.spec_from_file_location("kquant_crypto._portfolio_isolation_test", path)
    isolated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(isolated)
    portfolio = isolated.CandidatePortfolio(policy, deepcopy(RULES))
    portfolio.restore(deepcopy(warm_states[UP_TREND, "A"]))
    start = enter_normal(portfolio)
    stop = portfolio.positions["BTCUSDT"]["stop"]
    batch(portfolio, bar(start, 365, low=stop - 1))
    assert len(portfolio.trades) == 2
    assert all(e["evidence_scope"] == "candidate_simulation" for e in portfolio.events)
    assert portfolio.status()["order_submission"] is False


def test_pending_entry_is_canceled_when_entries_are_disabled_before_fill(warm_states):
    portfolio = warmed(warm_states)
    start = trigger(portfolio)
    assert len(portfolio.pending) == 2
    batch(portfolio, bar(start, 365), allow=False)
    assert not portfolio.positions, "entry suppression must cover already pending instructions"
    assert not portfolio.pending


def test_stress_sizing_uses_stressed_loss_but_keeps_base_r_denominator(warm_states):
    base = warmed(warm_states)
    stress = warmed(warm_states, multiplier=2)
    trigger(base)
    start = trigger(stress)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        normal, stressed = base.pending[symbol], stress.pending[symbol]
        buy = stressed["entry_reference"] * 1.001
        sell = stressed["stop"] * .999
        projected = buy - sell + .002 * (buy + sell)
        assert stressed["unit_net_risk"] == normal["unit_net_risk"]
        assert stressed["quantity"] <= normal["quantity"]
        assert stressed["quantity"] * projected <= 25
        assert stressed["estimated_risk_amount"] == pytest.approx(stressed["quantity"] * projected)
    assert sum(p["estimated_risk_amount"] for p in stress.pending.values()) <= 50
    stop = stress.pending["BTCUSDT"]["stop"]
    batch(stress, bar(start, 365, low=stop - 1))
    for trade in stress.trades:
        assert_costs(trade, stress)
        assert trade["net_r"] < -1


@pytest.mark.parametrize("next_open", [355, 360])
def test_last_old_day_close_breach_survives_rollover_and_uses_actual_open_baseline(warm_states, next_open):
    portfolio = warmed(warm_states)
    # Account precondition: earlier realized losses of 80 against the unchanged
    # 10,000 day-start equity. Do not relax the frozen 1% risk threshold.
    portfolio.cash -= 80
    assert portfolio.day_start == 10000
    assert portfolio.policy["daily_loss_limit"] == .01
    enter_normal(portfolio)
    parts = [bar(SIGNAL_START, 365, open=350, high=380, low=340),
             bar(SIGNAL_START + 300, 365)]
    for part in range(2, 11):
        current = bar(SIGNAL_START + part * 300, 365)
        parts.append(current)
        batch(portfolio, current)
    assert portfolio.value() > portfolio.day_start * .99
    assert not portfolio.exits and not portfolio.trades
    old_baseline = portfolio.day_start
    midnight = SIGNAL_START + 3600
    final_bar = bar(midnight - 300, 350, open=365, low=349.9, high=365.1)
    parts.append(final_bar)
    assert final_bar.start % 86400 == 23 * 3600 + 55 * 60
    assert all(final_bar.low > p["stop"] and final_bar.high < p["target"]
               for p in portfolio.positions.values())
    batch(portfolio, final_bar, aggregate(parts))

    closing_equity = portfolio.value()
    assert closing_equity < old_baseline * .99
    breaches = [e for e in portfolio.events if e["kind"] == "DAILY_LOSS_PAUSE"]
    assert len(breaches) == 1 and breaches[0]["time"] == midnight
    assert breaches[0]["equity"] == pytest.approx(closing_equity)
    assert portfolio.day == midnight // 86400
    assert portfolio.day_start == pytest.approx(closing_equity)
    assert not portfolio.day_paused
    assert len(portfolio.positions) == 2 and not portfolio.trades
    assert portfolio.exits == {s: "daily_loss" for s in portfolio.positions}

    positions = deepcopy(portfolio.positions)
    expected_open_equity = portfolio.cash + sum(
        p["quantity"] * next_open * (1 - portfolio.slippage) * (1 - portfolio.fee)
        for p in positions.values()
    )
    assert expected_open_equity != pytest.approx(closing_equity)
    assert all(p["stop"] < next_open < p["target"] for p in positions.values())
    batch(portfolio, bar(midnight, next_open + 1, open=next_open))

    assert portfolio.day_start == pytest.approx(expected_open_equity)
    assert len(portfolio.trades) == 2 and not portfolio.positions
    assert not portfolio.exits and not portfolio.pending
    for trade in portfolio.trades:
        assert trade["exit_reason"] == "daily_loss"
        assert trade["exit_time"] == midnight
        assert trade["exit_market_reference"] == next_open
        assert_costs(trade, portfolio)
    assert portfolio.cash == pytest.approx(expected_open_equity)
