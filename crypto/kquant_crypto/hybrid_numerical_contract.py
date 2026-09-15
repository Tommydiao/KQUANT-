"""M1 numerical definitions; no model fitting, market paths or admission."""

import math


def _probability(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value < 1:
        raise ValueError('Probability must be finite and strictly between zero and one')


def _samples(values):
    values = list(values)
    if not values or any(isinstance(x, bool) or not isinstance(x, (int,float)) or not math.isfinite(x) for x in values):
        raise ValueError('Nonempty finite samples required')
    return sorted(values)


def binomial_upper(k, n, *, alpha=.05):
    """One-sided exact binomial bound, by inversion of P_p(X<=k)=alpha.

    Assumes independently sampled path indicators. It controls numerical Monte
    Carlo sampling error only, never historical/model uncertainty.
    """
    if type(k) is not int or type(n) is not int or n <= 0 or not 0 <= k <= n:
        raise ValueError('Invalid binomial count')
    _probability(alpha)
    if k == n:
        return 1.0
    if k == 0:
        return -math.expm1(math.log(alpha) / n)
    log_combinations = [math.lgamma(n+1)-math.lgamma(j+1)-math.lgamma(n-j+1) for j in range(k+1)]
    lo, hi = 0.0, 1.0
    for _ in range(64):
        p = (lo+hi)/2
        if p == lo or p == hi:
            break
        terms = [c+j*math.log(p)+(n-j)*math.log1p(-p) for j,c in enumerate(log_combinations)]
        largest = max(terms)
        log_cdf = largest + math.log(math.fsum(math.exp(t-largest) for t in terms))
        if log_cdf > math.log(alpha):
            lo = p
        else:
            hi = p
    return hi


def quantile_linear(values, probability):
    values = _samples(values)
    _probability(probability)
    index = (len(values)-1)*probability
    lower = int(index)
    upper = min(lower+1,len(values)-1)
    return values[lower] + (index-lower)*(values[upper]-values[lower])


def expected_shortfall(losses, *, alpha=.95):
    values = list(reversed(_samples(losses)))
    _probability(alpha)
    mass = len(values)*(1-alpha)
    whole = int(mass)
    tail = math.fsum(values[:whole])
    if whole < len(values):
        tail += (mass-whole)*values[whole]
    return tail/mass


def synthetic_posterior_summary(*, conditional_means, predictive_returns):
    means, outcomes = _samples(conditional_means), _samples(predictive_returns)
    return {'p_edge': sum(x>0 for x in means)/len(means),
            'p_win': sum(x>0 for x in outcomes)/len(outcomes),
            'q05_mu': quantile_linear(means,.05),
            'predictive_q05': quantile_linear(outcomes,.05),
            'source_kind': 'SYNTHETIC_CONTRACT_ONLY'}
