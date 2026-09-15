import math

import pytest

from kquant_crypto.hybrid_mc_numerics_v12 import path_risk, upper_event_probability


def bound(k, n=5000, comparisons=6):
    return upper_event_probability(k, n, family_alpha=.05, comparisons=comparisons)


def row(t, eq, baseline=100, limit=.01):
    return dict(time=t, equity=eq, risk_day_id=t // 86400,
                day_start_equity=baseline, daily_loss_limit=limit)


def test_zero_and_all_events_are_not_zero_uncertainty():
    assert bound(0)['upper'] == pytest.approx(1 - (.05 / 6) ** (1 / 5000))
    assert bound(5000)['upper'] == 1
    assert bound(0)['upper'] > 0


def test_threshold_and_multiple_comparisons_are_conservative():
    pytest.importorskip('scipy', reason='Numerical quantiles run in the isolated math environment')
    assert bound(250)['estimate'] == .05
    assert bound(250)['upper'] > .05
    assert bound(250, comparisons=12)['upper'] > bound(250)['upper']
    assert bound(250)['admission'] == 'ABSTAIN'


@pytest.mark.parametrize('k,n', [(-1, 10), (11, 10), (0, 0), (True, 10), (1.0, 10)])
def test_bad_counts_rejected(k, n):
    with pytest.raises(ValueError):
        bound(k, n)


def test_original_budget_and_high_watermark_not_reset():
    r = path_risk([row(0, 99), row(300, 100)], initial_equity=99, historical_high_watermark=110)
    assert r['daily_loss_line_breached']
    assert r['incremental_peak_drawdown'] == 0
    assert r['absolute_high_watermark_drawdown'] == pytest.approx(.1)
    assert r['terminal_net_change'] == 1


def test_cannot_drop_initial_breach_by_starting_with_recovery():
    with pytest.raises(ValueError, match='initial risk state'):
        path_risk([row(300, 100)], initial_equity=99, historical_high_watermark=110)


def test_new_day_baseline_explicit_and_same_day_immutable():
    curve = [row(86100, 100), row(86400, 99.5, 99.5), row(86700, 98.5, 99.5)]
    with pytest.raises(ValueError, match='Unaudited'):
        path_risk(curve, initial_equity=100, historical_high_watermark=100)
    reset = dict(time=86400, previous_day=0, new_day=1, previous_baseline=100,
                 new_baseline=99.5, source='CandidatePortfolio._clock(day_change)')
    assert path_risk(curve, initial_equity=100, historical_high_watermark=100,
                     day_resets=[reset])['daily_loss_line_breached']
    with pytest.raises(ValueError, match='budget changed'):
        path_risk([row(0, 100), row(300, 99, 99)], initial_equity=100, historical_high_watermark=100)


def test_observation_gap_cannot_imply_non_breach():
    with pytest.raises(ValueError, match='gaps'):
        path_risk([row(0, 100), row(600, 100)], initial_equity=100, historical_high_watermark=100)


def test_recorded_original_midnight_open_is_not_arbitrary_budget_reset():
    reset = dict(time=0, previous_baseline=100, new_baseline=101,
                 source='CandidatePortfolio._clock(force=True)')
    r = path_risk([row(0, 100), row(300, 101, 101)], initial_equity=100,
                  historical_high_watermark=100, opening_resets=[reset])
    assert not r['daily_loss_line_breached']
    with pytest.raises(ValueError, match='midnight'):
        path_risk([row(0, 100), row(300, 101, 101)], initial_equity=100,
                  historical_high_watermark=100, opening_resets=[{**reset, 'time': 300}])


@pytest.mark.parametrize('value', [None, math.nan, math.inf])
def test_missing_or_nonfinite_valuation_abstains(value):
    with pytest.raises(ValueError):
        path_risk([row(0, value)], initial_equity=100, historical_high_watermark=100)
