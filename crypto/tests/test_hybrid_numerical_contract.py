import math

import pytest


def test_general_alpha_is_inverted_without_clipping_to_point_estimate():
    from kquant_crypto.hybrid_numerical_contract import binomial_upper
    assert binomial_upper(1,2,alpha=.9)==pytest.approx((.1)**.5)

from kquant_crypto.hybrid_numerical_contract import binomial_upper, expected_shortfall, synthetic_posterior_summary


def test_zero_observations_are_not_zero_risk():
    upper = binomial_upper(0, 5000, alpha=.05 / 12)
    assert upper == pytest.approx(1 - (.05 / 12) ** (1 / 5000), abs=1e-12)
    assert upper > 0
    assert binomial_upper(5000, 5000, alpha=.05 / 12) == 1


def test_49_percent_point_estimate_does_not_pass_five_percent_gate():
    assert 245 / 5000 < .05
    assert binomial_upper(245, 5000, alpha=.05 / 12) > .05


def test_exact_bound_has_enumerated_binomial_coverage():
    n, alpha = 20, .05
    for p in (.01, .05, .2, .5, .9, .99):
        coverage = sum(math.comb(n, k) * p**k * (1 - p)**(n-k)
                       for k in range(n+1) if p <= binomial_upper(k, n, alpha=alpha))
        assert coverage >= 1 - alpha - 1e-12


def test_multiplicity_budget_is_more_conservative_and_deterministic():
    result = binomial_upper(100, 5000, alpha=.05 / 12)
    assert result == binomial_upper(100, 5000, alpha=.05 / 12)
    assert result > binomial_upper(100, 5000, alpha=.05)


@pytest.mark.parametrize('k,n,alpha', [(-1,5,.05),(6,5,.05),(1,0,.05),(1,5,0),(1,5,1),
                                     (True,5,.05),(1,5,float('nan'))])
def test_invalid_count_or_error_budget_rejected(k,n,alpha):
    with pytest.raises(ValueError):
        binomial_upper(k,n,alpha=alpha)


def test_fractional_tail_mass_es_not_rounded_to_one_observation():
    # Worst 25% of six observations: one full + half the next.
    assert expected_shortfall([0,1,2,3,4,5], alpha=.75) == pytest.approx((5 + .5*4)/1.5)
    assert expected_shortfall([-5,-4,-3], alpha=.5) < 0


def test_pwin_and_pedge_are_different_objects():
    summary = synthetic_posterior_summary(conditional_means=[1,2,3], predictive_returns=[-3,-2,-1])
    assert summary['p_edge'] == 1
    assert summary['p_win'] == 0
    assert summary['q05_mu'] > 0
    assert summary['predictive_q05'] < 0
    assert summary['source_kind'] == 'SYNTHETIC_CONTRACT_ONLY'


def test_empty_and_nonfinite_samples_not_fake_neutral():
    with pytest.raises(ValueError):
        synthetic_posterior_summary(conditional_means=[], predictive_returns=[])
    with pytest.raises(ValueError):
        expected_shortfall([1, float('inf')])
