from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from kquant_crypto.low_frequency_research import DAY, STEP, SYMBOLS, replay, recost
from kquant_crypto.low_frequency_recovery import independent_segments, safe_metrics
from test_low_frequency_research import policy, fixture_market


def test_halt_never_executes_and_reopen_gap_protects(policy):
    m = fixture_market(1800)
    m.frames["BTCUSDT"] = m.frames["BTCUSDT"].drop([600,900])
    m.frames["BTCUSDT"].loc[1200] = [80,125,70,100]
    r = replay(m,policy,"LF_FIXED_V1",0,1800,confirmed_halts={("BTCUSDT",600),("BTCUSDT",900)})
    assert not r["uncertain"]
    assert r["trades"][0]["exit_time"] == 1200
    assert r["trades"][0]["exit_reason"] == "gap_stop"
    assert r["trades"][0]["exit_reference"] == 80
    assert len([e for e in r["events"] if e["reason"]=="confirmed_venue_halt_no_execution"])==2


def test_halt_cannot_override_observed_price(policy):
    with pytest.raises(ValueError,match="conflicts"):
        replay(fixture_market(),policy,"LF_FIXED_V1",0,900,confirmed_halts={("BTCUSDT",600)})


def test_unknown_is_still_censored_not_zero(policy):
    m=fixture_market(1800)
    m.frames["BTCUSDT"]=m.frames["BTCUSDT"].drop(600)
    r=replay(m,policy,"LF_FIXED_V1",0,1800)
    assert r["trades"][0]["net_r"] is None
    assert safe_metrics(r)["capital_return"] is None
    assert safe_metrics(r)["max_drawdown"] is None


def test_halt_blocks_entry_without_backfill(policy):
    m=fixture_market(1500)
    m.frames["BTCUSDT"]=m.frames["BTCUSDT"].drop(300)
    r=replay(m,policy,"LF_FIXED_V1",0,1500,confirmed_halts={("BTCUSDT",300)})
    assert not r["trades"]
    assert r["events"][0]["reason"]=="confirmed_venue_halt_no_entry"


def test_trailing_not_updated_during_halt(policy):
    m=fixture_market(29400)
    m.frames["BTCUSDT"]=m.frames["BTCUSDT"].drop(28500)
    m.four["BTCUSDT"]=pd.DataFrame({"close":[150.]},index=[14400])
    m.frames["BTCUSDT"].loc[28800]=[100,110,95,100]
    r=replay(m,policy,"LF_TRAIL_V1",0,29400,confirmed_halts={("BTCUSDT",28500)})
    assert r["trades"][0]["stop"]==90
    assert r["trades"][0]["label_status"]=="CENSORED"


def test_independent_restart_full_warmup_no_capital_transfer(policy):
    end=64*DAY
    m=fixture_market(end)
    for s in SYMBOLS: m.frames[s]=m.frames[s].drop(600)
    restart=62*DAY+300
    p=deepcopy(m.signals[300][0])
    p.update(entry_time=restart,signal_time=restart-300,opportunity_id="new")
    m.signals[restart]=[p]
    m.frames["BTCUSDT"].loc[restart]=[100,125,99,120]
    seg=independent_segments(m,policy,"LF_FIXED_V1",0,end,m.signals)
    assert len(seg)==2
    assert seg[0]["end"]==900
    assert seg[1]["start"]==restart
    assert seg[1]["result"]["equity"][0]["equity"]==policy["capital"]
    assert not seg[1]["capital_inherited"]
    assert seg[0]["result"]["trades"][0]["net_r"] is None
    assert seg[1]["result"]["trades"][0]["opportunity_id"]=="new"
    assert seg[1]["result"]["trades"][0]["label_status"]=="MATURE"
    ids=[t["opportunity_id"] for s in seg for t in s["result"]["trades"]]
    assert len(ids)==len(set(ids))


def test_recovery_default_identical_and_cost_r_unchanged(policy):
    m=fixture_market()
    m.frames["BTCUSDT"].loc[600]=[100,125,95,120]
    a=replay(m,policy,"LF_FIXED_V1",0,900)
    b=replay(m,policy,"LF_FIXED_V1",0,900,confirmed_halts=frozenset())
    assert a==b
    stress=recost(a["trades"],policy,2)
    assert stress[0]["risk_amount"]==a["trades"][0]["risk_amount"]
    assert stress[0]["net_r"]<a["trades"][0]["net_r"]


def test_halt_replay_future_perturbation_and_repeatability(policy):
    m=fixture_market(2400)
    m.frames["BTCUSDT"]=m.frames["BTCUSDT"].drop(600)
    m.frames["BTCUSDT"].loc[900]=[80,90,70,85]
    halts={("BTCUSDT",600)}
    a=replay(m,policy,"LF_FIXED_V1",0,2400,confirmed_halts=halts)
    for f in m.frames.values(): f.loc[f.index>=1500]*=3
    b=replay(m,policy,"LF_FIXED_V1",0,2400,confirmed_halts=halts)
    assert a["trades"]==b["trades"]
    assert b==replay(m,policy,"LF_FIXED_V1",0,2400,confirmed_halts=halts)
