from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kquant_crypto.low_frequency_research import (
    DAY, STEP, SYMBOLS, Market, aggregate, load_contract, prepare_market,
    replay, protection, next_trailing_stop, recost, centered_block_test,
)


@pytest.fixture
def policy():
    return load_contract(Path(__file__).resolve().parents[1] / "config/low_frequency_research_v1.json")


def fixture_market(end=900, plans=None):
    frame = pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100.}, index=np.arange(0, end, STEP))
    plan = {"symbol": "BTCUSDT", "signal_time": 0, "entry_time": 300, "reference": 100.,
            "stop": 90., "target": 120., "rank": 1., "opportunity_id": "one"}
    four = {s: pd.DataFrame(columns=["close"]) for s in SYMBOLS}
    return Market({s: frame.copy() for s in SYMBOLS}, {}, four, {300: plans or [plan]}, {}, {})


def test_closed_aggregation_rejects_missing_and_forming_day():
    f = pd.DataFrame({"open": 1., "high": 1., "low": 1., "close": 1.}, index=np.arange(0, DAY, STEP))
    assert len(aggregate(f, DAY)) == 1
    assert aggregate(f.iloc[:-1], DAY).empty
    assert aggregate(f.drop(300), DAY).empty


def test_future_bars_cannot_change_past_signals(policy):
    idx = np.arange(0, 75 * DAY, STEP)
    prices = 100 * np.exp(idx / DAY * .003 + .001 * np.sin(idx / 3600))
    frame = pd.DataFrame({"open": prices, "close": prices, "high": prices * 1.001, "low": prices * .999}, index=idx)
    frames = {s: frame.copy() for s in SYMBOLS}
    before = prepare_market(frames, policy)
    for s in SYMBOLS:
        frames[s].loc[frames[s].index >= 68 * DAY] *= 5
    after = prepare_market(frames, policy)
    past = {t: p for t, p in before.signals.items() if t < 68 * DAY}
    assert past
    assert past == {t: p for t, p in after.signals.items() if t < 68 * DAY}
    assert all(t % DAY == 300 for t in past)


def test_stop_first_and_open_gap():
    p = {"stop": 90., "target": 120.}
    assert protection(p, (100, 125, 85, 110), "LF_FIXED_V1") == (90., "stop", False)
    assert protection(p, (80, 125, 75, 110), "LF_FIXED_V1") == (80., "gap_stop", True)
    assert protection(p, (100, 125, 95, 110), "LF_TRAIL_V1") is None


def test_trailing_never_lowers():
    assert next_trailing_stop({"stop": 95, "initial_distance": 10}, 100) == 95


def test_trailing_cannot_retroactively_stop_prior_bar(policy):
    market = fixture_market(29400)
    market.four["BTCUSDT"] = pd.DataFrame({"close": [110.]}, index=[14400])
    market.frames["BTCUSDT"].loc[28500] = [100, 111, 97, 110]
    market.frames["BTCUSDT"].loc[28800] = [105, 106, 99, 103]
    result = replay(market, policy, "LF_TRAIL_V1", 0, 29400)
    t = result["trades"][0]
    assert t["exit_reference"] == 100
    assert t["exit_time"] == 29100
    assert t["initial_stop"] == 90


def test_entry_bar_protected_and_cost_denominator_fixed(policy):
    market = fixture_market()
    market.frames["BTCUSDT"].loc[300] = [100, 125, 80, 90]
    result = replay(market, policy, "LF_FIXED_V1", 0, 900)
    t = result["trades"][0]
    assert t["exit_reason"] == "stop"
    assert t["net_r"] == pytest.approx(-1)
    stress = recost([t], policy, 2)[0]
    assert stress["risk_amount"] == t["risk_amount"]
    assert stress["net_r"] < t["net_r"]


def test_missing_entry_never_retrofills(policy):
    market = fixture_market()
    market.frames["BTCUSDT"] = market.frames["BTCUSDT"].drop(300)
    r = replay(market, policy, "LF_FIXED_V1", 0, 900)
    assert r["trades"] == []
    assert r["events"][0]["reason"] == "missing_entry_bar"


def test_gap_preserves_unknown_instead_of_fake_loss(policy):
    market = fixture_market(1200)
    market.frames["BTCUSDT"] = market.frames["BTCUSDT"].drop(600)
    r = replay(market, policy, "LF_FIXED_V1", 0, 1200)
    assert r["uncertain"]
    assert r["trades"][0]["label_status"] == "CENSORED"
    assert r["trades"][0]["net_pnl"] is None


def test_capital_competition_and_determinism(policy):
    market = fixture_market()
    plan = market.signals[300][0]
    market.signals[300] = [{**plan, "symbol": s, "opportunity_id": s} for s in reversed(SYMBOLS)]
    a = replay(market, policy, "LF_FIXED_V1", 0, 900)
    b = replay(market, policy, "LF_FIXED_V1", 0, 900)
    assert a == b
    assert [t["symbol"] for t in a["trades"]] == ["BTCUSDT", "ETHUSDT"]
    assert sum(t["risk_amount"] for t in a["trades"]) <= policy["capital"] * policy["max_open_risk"]


def test_regime_exit_uses_open_and_keeps_stop_priority(policy):
    market = fixture_market(1200)
    market.regimes[("BTCUSDT", 600)] = False
    market.frames["BTCUSDT"].loc[600] = [80, 90, 75, 85]
    r = replay(market, policy, "LF_FIXED_V1", 0, 1200)
    assert r["trades"][0]["exit_reason"] == "gap_stop"


def test_null_centered_bootstrap_and_negative_edge(policy):
    trades = [{"label_status": "MATURE", "exit_time": i * DAY, "net_r": -1.} for i in range(365)]
    result = centered_block_test(trades, 0, 365 * DAY, policy)
    assert result["p_value"] == 1
    assert result["mean_r_upper"] < 0
    json.dumps(result, allow_nan=False)
    assert policy["purge_days"] == policy["embargo_days"] == policy["max_holding_days"]


def test_thirty_day_timeout_uses_next_open(policy):
    end = 30 * DAY + 900
    market = fixture_market(end)
    market.frames["BTCUSDT"].loc[30 * DAY + 300] = [105, 110, 100, 106]
    r = replay(market, policy, "LF_FIXED_V1", 0, end)
    assert r["trades"][0]["exit_time"] == 30 * DAY + 300
    assert r["trades"][0]["exit_reference"] == 105
    assert r["trades"][0]["exit_reason"] == "time_exit"
