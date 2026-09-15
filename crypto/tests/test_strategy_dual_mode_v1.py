from __future__ import annotations

from dataclasses import FrozenInstanceError
import json

import pytest

from kquant_crypto.strategy_dual_mode_v1 import (
    Bar, DualRegimeKernel, MAX_HOLD_BARS, RANGE, TRANSITION, UP_TREND,
    _Indicators, expected_net_values,
)


def candle(start, close=100.0, low=None, high=None):
    return Bar(start, close, close + 0.1 if high is None else high,
               close - 0.1 if low is None else low, close)


def feed_hour(kernel, index, close=100.0, wide=False, allow_entries=True):
    last = None
    for part in range(12):
        bar = candle(index * 3600 + part * 300, close,
                     close - 10 if wide and part == 0 else None,
                     close + 10 if wide and part == 0 else None)
        hourly = candle(index * 3600, close, close - 10 if wide else None,
                        close + 10 if wide else None) if part == 11 else None
        last = kernel.on_bar(bar, hourly, allow_entries=allow_entries)
    return last


def warmed(mode=RANGE, candidate="A", hours=251):
    kernel = DualRegimeKernel(candidate)
    for h in range(hours):
        feed_hour(kernel, h, 100 + h if mode == UP_TREND else 100,
                  wide=(mode == RANGE and h == 248), allow_entries=False)
    return kernel


def next_bar(kernel, close=100.0, **kwargs):
    return candle(kernel.five_bars[-1].start + 300, close, **kwargs)


def reclaim(kernel, close=93.1):
    kernel.on_bar(next_bar(kernel, 92.9))
    return kernel.on_bar(next_bar(kernel, close))


def test_bar_contract_is_frozen_and_interval_external():
    bar = Bar(0, 1, 2, 0.5, 1.5)
    assert bar.volume == 0
    assert not hasattr(bar, "end")
    with pytest.raises(FrozenInstanceError):
        bar.close = 2


@pytest.mark.parametrize("args", [
    (-1, 1, 2, 1, 1), (0.0, 1, 2, 1, 1), (0, 1, 2, 0, 1),
    (0, 3, 2, 1, 1), (0, 1, 2, 1, 3), (0, 1, float("nan"), 1, 1),
    (0, 1, 2, 1, 1, -1),
])
def test_invalid_bars_rejected(args):
    with pytest.raises(ValueError):
        Bar(*args)


def test_indicators_seed_and_wilder_and_ema_slope():
    ind = _Indicators()
    for i in range(50):
        ind.update(candle(i * 3600, 100 + i, 99 + i, 101 + i), hourly=True)
        if i == 12:
            assert ind.atr is None
        if i == 13:
            assert ind.atr == 2
        if i == 48:
            assert ind.ema is None
    assert ind.ema == 124.5
    ind.update(candle(50 * 3600, 150, 146, 154), hourly=True)
    assert ind.atr == pytest.approx((2 * 13 + 8) / 14)
    assert ind.ema == pytest.approx(125.5)
    for i in (51, 52):
        ind.update(candle(i * 3600, 100 + i), hourly=True)
    assert ind.slope == pytest.approx(3)
    assert ind.er == 1


def test_er_uses_24_changes_and_flat_denominator():
    ind = _Indicators()
    for i in range(25):
        ind.update(candle(i * 3600, 100 + i % 2), hourly=True)
    assert ind.er == 0
    ind.update(candle(25 * 3600, 103), hourly=True)
    assert ind.er == pytest.approx(2 / 26)
    flat = _Indicators()
    for i in range(25):
        flat.update(candle(i * 3600), hourly=True)
    assert flat.er == 0


def test_warmup_and_two_post_warmup_confirmations():
    kernel = warmed(hours=249)
    assert not kernel.ready
    decision = feed_hour(kernel, 249)
    assert decision["ready"] and decision["mode"] == TRANSITION
    assert kernel.confirm_count == 1
    assert decision["signal"] is None
    decision = feed_hour(kernel, 250)
    assert decision["mode"] == RANGE
    assert kernel.box["effective_at"] == 251 * 3600
    assert kernel.box["lower"] == 90
    assert kernel.box["upper"] == 110


def test_five_minute_warmup_is_independent():
    kernel = warmed()
    kernel.five.count = 99
    assert not kernel.ready
    result = kernel.on_bar(next_bar(kernel))
    assert result["ready"]


def test_zero_atr_disables_entries():
    kernel = DualRegimeKernel()
    for h in range(251):
        for part in range(12):
            start = h * 3600 + part * 300
            kernel.on_bar(Bar(start, 100, 100, 100, 100),
                          Bar(h * 3600, 100, 100, 100, 100) if part == 11 else None)
    result = kernel.on_bar(Bar(251 * 3600, 100, 100, 100, 100))
    assert not result["ready"]
    assert "ATR_NONPOSITIVE" in result["reason_codes"]


@pytest.mark.parametrize("candidate,multiple", [("A", 2.5), ("B", 3.0)])
def test_trend_breakout_excludes_signal_bar_and_freezes_six_bar_stop(candidate, multiple):
    kernel = warmed(UP_TREND, candidate)
    bar = next_bar(kernel, 365, low=340, high=380)
    result = kernel.on_bar(bar)
    signal = result["signal"]
    assert signal is not None
    assert signal["mode"] == UP_TREND
    assert signal["entry_reference"] == 365
    assert signal["stop"] == pytest.approx(340 - 0.25 * kernel.five.atr)
    assert signal["target"] == pytest.approx(365 + multiple * (365 - signal["stop"]))
    assert signal["signal_time"] == bar.start + 300
    profit, risk = expected_net_values(365, signal["stop"], signal["target"])
    assert signal["unit_net_risk"] == risk
    assert signal["expected_net_rr"] == profit / risk
    assert signal["expected_net_rr"] >= 2


def test_breakout_is_strict_and_net_filter_applies():
    kernel = warmed(UP_TREND)
    high = max(b.high for b in kernel.five_bars[-20:])
    assert kernel.on_bar(next_bar(kernel, high))["signal"] is None
    result = kernel.on_bar(next_bar(kernel, high + 0.101))
    assert result["signal"] is None
    assert "NET_RR_INSUFFICIENT" in result["reason_codes"]


@pytest.mark.parametrize("candidate,target", [("A", 100), ("B", 102)])
def test_range_reclaim_and_frozen_targets(candidate, target):
    kernel = warmed(candidate=candidate)
    box = dict(kernel.box)
    result = reclaim(kernel)
    assert result["signal"] is not None
    assert result["signal"]["target"] == target
    assert result["signal"]["stop"] == 90 - 0.2 * box["atr"]
    assert result["signal"]["expected_net_rr"] >= 1.5
    assert kernel.box == box


def test_range_requires_two_entire_bars_after_effective_time():
    kernel = warmed()
    result = kernel.on_bar(next_bar(kernel, 93.1))
    assert result["signal"] is None
    assert "RANGE_SIGNAL_BEFORE_EFFECTIVE" in result["reason_codes"]


@pytest.mark.parametrize("close,reason", [(93, "RANGE_NOT_TRIGGERED"),
                                         (95.01, "RANGE_NOT_TRIGGERED"),
                                         (95, "GROSS_RR_INSUFFICIENT")])
def test_range_trigger_and_gross_rr_boundaries(close, reason):
    result = reclaim(warmed(), close)
    assert result["signal"] is None
    assert reason in result["reason_codes"]


@pytest.mark.parametrize("side", ["low", "high"])
def test_box_invalidation_is_strict_and_precedes_signal(side):
    kernel = warmed()
    box = kernel.box.copy()
    boundary = box["lower"] - 0.2 * box["atr"] if side == "low" else box["upper"] + 0.2 * box["atr"]
    kernel.on_bar(next_bar(kernel, 92.9, **{side: boundary}))
    assert kernel.mode == RANGE
    result = kernel.on_bar(next_bar(kernel, 93.1, **{side: boundary + (-0.001 if side == "low" else 0.001)}))
    assert result["mode_invalidated"]
    assert result["mode"] == TRANSITION and result["signal"] is None
    assert kernel.box is None


def test_box_invalidation_hour_is_not_first_confirmation():
    kernel = warmed()
    for _ in range(11):
        kernel.on_bar(next_bar(kernel))
    result = kernel.on_bar(next_bar(kernel, low=80), candle(251 * 3600))
    assert result["mode_invalidated"] and kernel.confirm_count == 0
    assert "BOX_PRICE_INVALIDATED" in result["reason_codes"]
    assert feed_hour(kernel, 252)["mode"] == TRANSITION
    assert feed_hour(kernel, 253)["mode"] == RANGE


def test_hourly_invalidation_does_not_count_as_new_confirmation():
    kernel = warmed(UP_TREND)
    # Exact state-boundary scenario: new hour qualifies for RANGE, not trend.
    kernel.hour.ema = 100
    kernel.hour.emas = [100] * 4
    kernel.hour.closes = [100] * 25
    result = feed_hour(kernel, 251)
    assert result["mode_invalidated"]
    assert kernel.confirm_count == 0 and kernel.mode == TRANSITION
    assert feed_hour(kernel, 252)["mode"] == TRANSITION
    assert feed_hour(kernel, 253)["mode"] == RANGE


@pytest.mark.parametrize("mode,er,slope,maintained", [
    (UP_TREND, 0.25, 0, True), (UP_TREND, 0.249, 0, False),
    (UP_TREND, 0.35, -0.001, False),
    (RANGE, 0.299, 0.5, True), (RANGE, 0.30, 0, False),
    (RANGE, 0.20, 0.501, False),
])
def test_hysteresis_exact_boundaries(monkeypatch, mode, er, slope, maintained):
    kernel = warmed(mode)
    kernel.hour.atr = 1
    kernel.hour.ema = kernel.hour.previous_close - 1
    monkeypatch.setattr(_Indicators, "er", property(lambda self: er))
    monkeypatch.setattr(_Indicators, "slope", property(lambda self: slope))
    assert kernel._update_mode(252 * 3600, []) is (not maintained)
    assert kernel.mode == (mode if maintained else TRANSITION)


def test_box_expiry_and_reconfirmation():
    kernel = warmed()
    box = kernel.box.copy()
    for h in range(251, 274):
        feed_hour(kernel, h)
        assert kernel.box == box
    result = feed_hour(kernel, 274)
    assert result["mode_invalidated"] and "BOX_EXPIRED" in result["reason_codes"]
    assert kernel.confirm_count == 0
    assert feed_hour(kernel, 275)["mode"] == TRANSITION
    assert feed_hour(kernel, 276)["mode"] == RANGE
    assert kernel.box["effective_at"] == 277 * 3600


def test_range_stop_invalidates_immediately_and_survives_checkpoint():
    kernel = warmed()
    kernel.record_exit(251 * 3600, stopped=True, mode=RANGE)
    assert kernel.mode == TRANSITION and kernel.box is None
    restored = DualRegimeKernel.from_dict(json.loads(json.dumps(kernel.to_dict())))
    result = restored.on_bar(next_bar(restored))
    assert result["mode_invalidated"]
    assert "RANGE_STOP_INVALIDATED" in result["reason_codes"]
    assert not restored.on_bar(next_bar(restored))["mode_invalidated"]


@pytest.mark.parametrize("offset", [0, 1, 299, 300])
def test_cooldown_counts_twelve_whole_bars_not_elapsed_gap(offset):
    kernel = warmed(UP_TREND)
    time = 251 * 3600 + offset
    kernel.record_exit(time, mode=UP_TREND)
    for part in range(12):
        result = kernel.on_bar(candle(251 * 3600 + part * 300, 350),
                               candle(251 * 3600, 350) if part == 11 else None)
        expected = 12 - part
        assert kernel.cooldown_remaining == expected
        assert result["signal"] is None
    result = kernel.on_bar(next_bar(kernel, 350))
    assert kernel.cooldown_remaining == 0
    assert result["entry_ready"]


def test_suppressed_entries_still_update_all_state():
    kernel = warmed(UP_TREND)
    peer = DualRegimeKernel.from_dict(kernel.to_dict())
    bar = next_bar(kernel, 365, low=340)
    assert peer.on_bar(bar)["signal"] is not None
    result = kernel.on_bar(bar, allow_entries=False)
    assert result["signal"] is None and not result["entry_ready"]
    assert "ENTRIES_SUPPRESSED" in result["reason_codes"]
    assert kernel.to_dict() == peer.to_dict()


@pytest.mark.parametrize("kind", ["five", "hour"])
def test_gaps_reset_both_warmups_and_active_mode(kind):
    kernel = warmed()
    if kind == "five":
        result = kernel.on_bar(candle(251 * 3600 + 300))
    else:
        for part in range(12):
            result = kernel.on_bar(candle(251 * 3600 + part * 300))
    assert result["mode_invalidated"]
    assert result["mode"] == TRANSITION and not result["ready"]
    assert kernel.five.count == 1 and kernel.hour.count == 0
    assert kernel.confirm_count == 0
    assert "DATA_GAP_RESET" in result["reason_codes"]


def test_gap_does_not_discharge_cooldown_by_wall_clock():
    kernel = warmed()
    kernel.record_exit(251 * 3600)
    kernel.on_bar(candle(253 * 3600))
    assert kernel.cooldown_remaining == 11


@pytest.mark.parametrize("kind", ["duplicate", "backward", "misaligned", "future_hour", "old_hour"])
def test_bad_time_inputs_rejected_before_mutation(kind):
    kernel = warmed()
    bar, hour = next_bar(kernel), None
    if kind == "duplicate":
        bar = kernel.five_bars[-1]
    elif kind == "backward":
        bar = candle(0)
    elif kind == "misaligned":
        bar = candle(bar.start + 1)
    elif kind == "future_hour":
        hour = candle(251 * 3600)
    else:
        hour = kernel.hour_bars[-1]
    state = kernel.to_dict()
    with pytest.raises(ValueError):
        kernel.on_bar(bar, hour)
    assert kernel.to_dict() == state


def test_json_recovery_decisions_match_uninterrupted_stream():
    original = warmed()
    restored = DualRegimeKernel.from_dict(json.loads(json.dumps(original.to_dict())))
    for h in range(251, 280):
        assert feed_hour(original, h) == feed_hour(restored, h)
    assert original.to_dict() == restored.to_dict()
    snapshot = original.to_dict()
    snapshot["five"]["count"] = 0
    snapshot["five_bars"][0]["close"] = 1
    assert original.five.count > 0 and original.five_bars[0].close == 100


def test_checkpoint_during_indicator_seed_matches():
    original = DualRegimeKernel()
    for h in range(10):
        feed_hour(original, h)
    restored = DualRegimeKernel.from_dict(json.loads(json.dumps(original.to_dict())))
    for h in range(10, 252):
        assert feed_hour(original, h) == feed_hour(restored, h)


def test_future_suffix_cannot_change_prior_signals():
    kernel = warmed(UP_TREND)
    signal = kernel.on_bar(next_bar(kernel, 365, low=340))["signal"]
    frozen = json.dumps(signal, sort_keys=True)
    for _ in range(5):
        kernel.on_bar(next_bar(kernel, 1, low=0.5))
    assert json.dumps(signal, sort_keys=True) == frozen


def test_cost_formula_and_exported_timeouts():
    profit, risk = expected_net_values(100, 95, 115)
    assert profit == pytest.approx(115 * .9995 - 100 * 1.0005
                                 - .001 * (100 * 1.0005 + 115 * .9995))
    assert risk == pytest.approx(100 * 1.0005 - 95 * .9995
                               + .001 * (100 * 1.0005 + 95 * .9995))
    assert MAX_HOLD_BARS == {UP_TREND: 72, RANGE: 36}
    with pytest.raises(ValueError):
        DualRegimeKernel("C")
    state = DualRegimeKernel().to_dict()
    state["schema_version"] = 2
    with pytest.raises(ValueError):
        DualRegimeKernel.from_dict(state)


@pytest.mark.parametrize("er,slope,expected", [
    (0.35, 0.001, UP_TREND), (0.349, 0.001, TRANSITION),
    (0.35, 0, TRANSITION), (0.20, 0.25, RANGE),
    (0.201, 0.25, TRANSITION), (0.20, 0.251, TRANSITION),
    (0.20, -0.25, RANGE),
])
def test_two_hour_entry_thresholds(monkeypatch, er, slope, expected):
    kernel = warmed()
    kernel._invalidate()
    kernel.hour.atr = 1
    kernel.hour.ema = kernel.hour.previous_close - 1
    monkeypatch.setattr(_Indicators, "er", property(lambda self: er))
    monkeypatch.setattr(_Indicators, "slope", property(lambda self: slope))
    kernel._update_mode(252 * 3600, [])
    assert kernel.mode == TRANSITION
    kernel._update_mode(253 * 3600, [])
    assert kernel.mode == expected


def test_confirmation_must_be_consecutive(monkeypatch):
    kernel = warmed()
    kernel._invalidate()
    kernel.hour.ema = 90
    kernel.hour.atr = 1
    monkeypatch.setattr(_Indicators, "slope", property(lambda self: 1))
    monkeypatch.setattr(_Indicators, "er", property(lambda self: 0.4))
    kernel._update_mode(252 * 3600, [])
    assert kernel.confirm_count == 1
    monkeypatch.setattr(_Indicators, "er", property(lambda self: 0.24))
    kernel._update_mode(253 * 3600, [])
    assert kernel.confirm_count == 0
    monkeypatch.setattr(_Indicators, "er", property(lambda self: 0.4))
    kernel._update_mode(254 * 3600, [])
    assert kernel.mode == TRANSITION and kernel.confirm_count == 1


def test_range_rejects_net_space_even_when_gross_passes():
    kernel = warmed()
    kernel.box.update(lower=99, upper=101, width=2, midpoint=100, atr=0.01)
    kernel.on_bar(next_bar(kernel, 99.29))
    result = kernel.on_bar(next_bar(kernel, 99.31))
    assert (100 - 99.31) / (99.31 - 98.998) > 1.8
    assert "NET_RR_INSUFFICIENT" in result["reason_codes"]
    assert result["signal"] is None


def test_trend_stop_excludes_seventh_bar():
    kernel = warmed(UP_TREND)
    kernel.on_bar(next_bar(kernel, 350, low=300))
    for _ in range(5):
        kernel.on_bar(next_bar(kernel, 350, low=349))
    result = kernel.on_bar(next_bar(kernel, 365, low=348))
    assert result["signal"] is not None
    assert result["signal"]["stop"] == pytest.approx(348 - 0.25 * kernel.five.atr)


def test_checkpoint_is_detached_in_both_directions():
    original = warmed()
    state = original.to_dict()
    restored = DualRegimeKernel.from_dict(state)
    state["box"]["lower"] = 1
    state["hour"]["closes"][0] = 1
    assert restored.box["lower"] == original.box["lower"] == 90
    assert restored.hour.closes[0] == 100


def test_data_unavailable_clears_partial_confirmation():
    kernel = warmed(hours=250)
    assert kernel.confirm_count == 1
    kernel.five.atr = 0
    kernel.on_bar(Bar(250 * 3600, 100, 100, 100, 100))
    assert kernel.confirm_count == 0


def test_non_stop_range_exit_keeps_box_and_original_mode_matters():
    kernel = warmed()
    box = kernel.box.copy()
    kernel.record_exit(251 * 3600, stopped=False, mode=RANGE)
    assert kernel.box == box and kernel.mode == RANGE
    kernel.record_exit(251 * 3600, stopped=True, mode=UP_TREND)
    assert kernel.box == box and not kernel.pending_invalidation


def test_suppression_does_not_hide_mode_invalidation():
    kernel = warmed()
    result = kernel.on_bar(next_bar(kernel, low=80), allow_entries=False)
    assert result["mode_invalidated"] and result["signal"] is None
    assert "BOX_PRICE_INVALIDATED" in result["reason_codes"]


@pytest.mark.parametrize("exit_offset", [0, 150, 300])
def test_portfolio_record_exit_before_exit_bar_and_restart(exit_offset):
    kernel = warmed()
    start = 251 * 3600
    kernel.record_exit(start + exit_offset, stopped=True, mode=RANGE)
    kernel = DualRegimeKernel.from_dict(json.loads(json.dumps(kernel.to_dict())))
    first = kernel.on_bar(candle(start))
    assert first["mode_invalidated"]
    assert kernel.cooldown_remaining == 12
    assert not kernel.pending_invalidation
    for number in range(1, 13):
        current = start + number * 300
        hour = candle(current + 300 - 3600) if (current + 300) % 3600 == 0 else None
        result = kernel.on_bar(candle(current), hour)
        assert not result["mode_invalidated"]
        assert kernel.cooldown_remaining == 12 - number


def test_missing_hour_at_boundary_invalidates_without_waiting_for_next_hour():
    kernel = warmed()
    for part in range(11):
        result = kernel.on_bar(candle(251 * 3600 + part * 300))
        assert result["mode"] == RANGE
    result = kernel.on_bar(candle(251 * 3600 + 3300))
    assert result["mode_invalidated"]
    assert not result["ready"] and kernel.hour.count == 0
    assert kernel.mode == TRANSITION and kernel.box is None
    assert "DATA_GAP_RESET" in result["reason_codes"]
    for h in range(252, 501):
        feed_hour(kernel, h)
    assert kernel.hour.count == 249 and not kernel.ready
    feed_hour(kernel, 501)
    assert kernel.ready and kernel.mode == TRANSITION
    feed_hour(kernel, 502)
    assert kernel.mode == RANGE
