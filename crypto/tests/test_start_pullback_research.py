from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from kquant_crypto.low_frequency_research import STEP, SYMBOLS, replay, recost
from kquant_crypto.start_pullback_research import (HOUR, FOUR, FLOW, ResearchMarket, complete_bars,
    structure_features, prepare, market_allowed, run_segments, random_frequency, random_signals)
from test_low_frequency_research import fixture_market


@pytest.fixture
def contract():
    return json.loads((Path(__file__).parents[1] / "config/start_pullback_research_v1.json").read_text())


def frames(n=88):
    times = np.arange(0, n * FOUR, STEP)
    prices = np.where(times < 60 * FOUR, 100 * np.exp(.03 * np.sin(times / (8 * HOUR))), 100.)
    frame = pd.DataFrame({"open": prices, "high": prices + .02, "low": prices - .02,
        "close": prices, "volume": 1., "quote_volume": 1., "taker_buy_quote_volume": .6,
        "trade_count": 1.}, index=times)
    def block(begin, end, opening, closing, low, quote):
        ix = (frame.index >= begin) & (frame.index < end)
        frame.loc[ix, ["open", "high", "low", "close"]] = [opening, max(opening, closing) + .02, low, closing]
        frame.loc[ix, ["quote_volume", "taker_buy_quote_volume", "trade_count"]] = [quote, quote * .7, 5]
    block(80*FOUR, 81*FOUR, 100., 100.4, 99.99, 10.)
    block(81*FOUR, 82*FOUR, 100.4, 100.5, 100.35, 1.)
    block(81*FOUR, 81*FOUR+HOUR, 100.4, 100.5, 100.35, 20.)
    block(82*FOUR, 83*FOUR, 100.5, 100.1, 99.99, 1.)
    block(83*FOUR, 83*FOUR+HOUR, 100.1, 100.2, 100.1, 20.)
    return {s: frame.copy() for s in SYMBOLS}


def test_complete_bars_requires_all_native_constituents():
    f = frames()["BTCUSDT"]
    h = complete_bars(f.drop(300), HOUR)
    four = complete_bars(f.drop(300), FOUR)
    assert not h.loc[0, "complete"] and pd.isna(h.loc[0, "close"])
    assert not four.loc[0, "complete"]
    assert h.loc[HOUR, "complete"]
    with pytest.raises(ValueError, match="Duplicate"):
        complete_bars(pd.concat([f, f.iloc[:1]]), HOUR)


def test_unknown_or_impossible_flow_not_fabricated():
    f = frames()["BTCUSDT"]
    f.loc[0, "taker_buy_quote_volume"] = 1000
    assert not complete_bars(f, HOUR).loc[0, "complete"]
    f.loc[0, list(FLOW)] = np.nan
    assert not complete_bars(f, FOUR).loc[0, "complete"]


def test_prior_structure_excludes_breakout_bar(contract):
    f = complete_bars(frames()["BTCUSDT"], FOUR)
    a = structure_features(f, contract)
    f.loc[80*FOUR, ["high", "low", "close", "quote_volume"]] = [900, 1, 500, 90000]
    b = structure_features(f, contract)
    keys = ["upper", "lower", "short_std", "long_std", "volume_median"]
    pd.testing.assert_series_equal(a.loc[80*FOUR, keys], b.loc[80*FOUR, keys])


def test_two_modes_first_confirmation_and_no_future_fill(contract):
    result = prepare(frames(), contract)
    for candidate, expected in (("START_V1", 81*FOUR+HOUR), ("PULLBACK_V1", 83*FOUR+HOUR)):
        good = [o for o in result.opportunities if o["candidate_id"] == candidate and o["symbol"] == "BTCUSDT"]
        assert len(good) == 1
        assert good[0]["reasons"] == []
        assert good[0]["confirmation_time"] == expected
        assert good[0]["entry_time"] == expected + STEP
        assert expected not in result.signals[candidate]
        assert good[0]["actual_received_at"] is None
        assert good[0]["actual_decision_committed_at"] is None
    ep = [o for o in result.opportunities if o["symbol"] == "BTCUSDT"]
    assert ep[0]["episode_id"] == ep[1]["episode_id"]


def test_failed_start_does_not_prevent_pullback(contract):
    f = frames()
    for frame in f.values():
        frame.loc[81*FOUR:81*FOUR+HOUR-STEP, "taker_buy_quote_volume"] = 1
    result = prepare(f, contract)
    assert result.signals["START_V1"] == {}
    assert result.signals["PULLBACK_V1"]
    assert all("confirmation_buy_share_not_above_half" in o["reasons"]
               for o in result.opportunities if o["candidate_id"] == "START_V1")


def test_first_failed_confirmation_not_retried(contract):
    f = frames()
    for frame in f.values():
        frame.loc[81*FOUR:81*FOUR+HOUR-STEP, "close"] = 100.
        frame.loc[81*FOUR+HOUR:81*FOUR+2*HOUR-STEP, "quote_volume"] = 100
        frame.loc[81*FOUR+HOUR:81*FOUR+2*HOUR-STEP, "taker_buy_quote_volume"] = 90
    r = prepare(f, contract)
    assert not r.signals["START_V1"]
    assert len([o for o in r.opportunities if o["candidate_id"] == "START_V1"]) == 3


def test_missing_confirmation_cancels_and_unknown_is_not_zero_return(contract):
    f = {s: df.drop(81*FOUR+STEP) for s, df in frames().items()}
    r = prepare(f, contract)
    assert not r.signals["START_V1"]
    assert all(o["label_status"] == "NOT_APPLICABLE" and o["fill_status"] == "NOT_ATTEMPTED"
               for o in r.opportunities if o["candidate_id"] == "START_V1")
    assert all("missing_first_confirmation_hour" in o["reasons"]
               for o in r.opportunities if o["candidate_id"] == "START_V1")


def test_structure_break_cancels_reclaim(contract):
    f = frames()
    for frame in f.values(): frame.loc[82*FOUR, "low"] = 98
    r = prepare(f, contract)
    assert not r.signals["PULLBACK_V1"]
    assert any(e["end_reason"] == "structure_low_broken" for e in r.episodes)


def test_future_changes_do_not_change_completed_decisions(contract):
    f = frames()
    a = prepare(f, contract)
    cutoff = 84*FOUR
    for frame in f.values(): frame.loc[frame.index >= cutoff, ["open", "high", "low", "close"]] *= 2
    b = prepare(f, contract)
    assert [o for o in a.opportunities if o["confirmation_time"] <= cutoff] == [o for o in b.opportunities if o["confirmation_time"] <= cutoff]
    truncated = prepare({s: frame.loc[frame.index < cutoff] for s, frame in f.items()}, contract)
    assert [o for o in a.opportunities if o["confirmation_time"] <= cutoff] == [o for o in truncated.opportunities if o["confirmation_time"] <= cutoff]


def test_market_threshold_and_missing_data(contract):
    normal = pd.Series({"sigma": .02, "return_48h": -.02})
    assert market_allowed(normal, normal, contract) is True
    assert market_allowed(normal, pd.Series({"sigma": .02, "return_48h": -.0201}), contract) is False
    assert market_allowed(normal, None, contract) is None
    assert market_allowed(normal, pd.Series({"sigma": 0, "return_48h": 1}), contract) is None


def test_regime_exit_scheduled_after_closed_four_hour(contract):
    f = frames()
    r = prepare(f, contract)
    assert all(t % FOUR == STEP for _, t in r.market.regimes)
    assert ("BTCUSDT", 81*FOUR) not in r.market.regimes


def test_repeatability_and_random_rate_training_isolation(contract):
    a = prepare(frames(), contract)
    b = prepare(frames(), contract)
    assert a.signals == b.signals
    ids = [o["opportunity_id"] for o in a.opportunities]
    assert len(ids) == len(set(ids))
    cutoff = 82*FOUR
    rates = random_frequency(a, contract, cutoff)
    b.signals["START_V1"][90*FOUR] = [{"symbol": "BTCUSDT"}]*100
    assert rates == random_frequency(b, contract, cutoff)
    assert random_signals(a, contract, "START_V1", rates) == random_signals(a, contract, "START_V1", rates)


def test_shared_engine_protection_and_costs_unchanged(contract):
    m = fixture_market(1800)
    m.signals[300][0]["confirmation_time"] = 0
    m.frames["BTCUSDT"].loc[600] = [100, 150, 95, 110]
    r = ResearchMarket(m, {}, [], [], {}, {}, {})
    original = replay(m, contract, "LF_TRAIL_V1", 0, 1800, signals=m.signals)
    wrapped = run_segments(r, contract, "START_V1", 0, 1800, m.signals, frozenset())[0]["result"]
    assert wrapped["equity"] == original["equity"]
    assert wrapped["metrics"] == original["metrics"]
    assert wrapped["trades"][0]["label_status"] == "CENSORED"  # no fixed take profit
    m.frames["BTCUSDT"].loc[600] = [80, 100, 70, 90]
    closed = run_segments(r, contract, "PULLBACK_V1", 0, 1800, m.signals, frozenset())[0]["result"]
    t = closed["trades"][0]
    assert t["exit_reason"] == "gap_stop" and t["exit_reference"] == 80
    assert t["execution_policy"].startswith("DELAYED_BAR_PROXY")
    assert t["candidate_id"] == "PULLBACK_V1"
    stress = recost(closed["trades"], contract, 2)[0]
    assert stress["risk_amount"] == t["risk_amount"] and stress["net_r"] < t["net_r"]


def test_price_protection_survives_missing_flow(contract):
    f = frames()
    f["BTCUSDT"].loc[83*FOUR+300, "quote_volume"] = np.nan
    r = prepare(f, contract)
    assert 83*FOUR+300 in r.market.frames["BTCUSDT"].index
    assert 83*FOUR in r.market.four["BTCUSDT"].index
    assert not r.hourly["BTCUSDT"].loc[83*FOUR+HOUR, "complete"]


def test_signal_cooldown_after_new_episode_does_not_depend_on_fills(contract):
    f = frames()
    for frame in f.values():
        frame.loc[84*FOUR, "low"] = 98
        frame.loc[85*FOUR:86*FOUR-STEP, ["open", "high", "low", "close"]] = [100.6, 100.8, 100.55, 100.7]
        frame.loc[85*FOUR:86*FOUR-STEP, ["quote_volume", "taker_buy_quote_volume"]] = [50, 35]
        frame.loc[86*FOUR:86*FOUR+HOUR-STEP, ["open", "high", "low", "close"]] = [100.7, 100.8, 100.6, 100.75]
        frame.loc[86*FOUR:86*FOUR+HOUR-STEP, ["quote_volume", "taker_buy_quote_volume"]] = [50, 35]
    r = prepare(f, contract)
    second = [o for o in r.opportunities if o["candidate_id"] == "START_V1" and o["setup_time"] == 86*FOUR]
    assert len(second) == 3
    assert all(o["reasons"] == ["signal_cooldown_24h"] for o in second)


def test_episode_expiry_does_not_wait_for_profit(contract):
    r = prepare(frames(104), contract)
    assert len(r.episodes) == 3
    assert all(e["end_reason"] == "episode_expired" and e["ended_at"] == 100*FOUR for e in r.episodes)


def test_partition_windows_and_control_history_are_fixed(contract):
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    from run_start_pullback_research import entry_windows, mask_signals
    windows = entry_windows(contract)
    for start, entry_end, end in windows:
        assert end-entry_end == 30*86400+STEP
        assert mask_signals({start-STEP:[1], start:[2], entry_end-STEP:[3], entry_end:[4]}, [(start, entry_end, end)]) == {start:[2], entry_end-STEP:[3]}


def test_empty_trade_file_does_not_fabricate_zero_r(tmp_path):
    import sys
    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    from run_start_pullback_research import load_primary_trades, csv_write
    csv_write(tmp_path / "START_V1_continuous_base_00_trades.csv.gz", [])
    assert load_primary_trades(tmp_path, "START_V1") == []
