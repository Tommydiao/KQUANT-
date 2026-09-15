"""Model-conditional Monte Carlo error bounds, never a financial admission gate."""
import math


def upper_event_probability(k, n, *, family_alpha, comparisons):
    """One-sided exact binomial upper bound with predeclared Bonferroni budget.

    Independent draws are required across paths, conditional on a frozen model.
    Common paths across alternatives are allowed by the union bound. This says
    nothing about market calibration, overlapping historical labels or model bias.
    """
    if type(k) is not int or type(n) is not int or not 0 <= k <= n or n < 1:
        raise ValueError('Integer successes and positive path count required')
    if type(comparisons) is not int or comparisons < 1:
        raise ValueError('Predeclared positive comparison budget required')
    if type(family_alpha) not in (float, int) or not math.isfinite(family_alpha) or not 0 < family_alpha < 1:
        raise ValueError('Explicit family error probability required')
    alpha = family_alpha / comparisons
    if not 0 < alpha < 1:
        raise ValueError('Numerically unsupported error budget')
    if k == n:
        upper = 1.0
    elif k == 0:
        upper = -math.expm1(math.log(alpha) / n)
    else:
        from scipy.stats import beta
        upper = float(beta.isf(alpha, k + 1, n - k))
    if not math.isfinite(upper) or not k / n <= upper <= 1:
        raise ValueError('Numerical bound unavailable; do not use plug-in estimate')
    return {'count': k, 'paths': n, 'estimate': k / n, 'upper': upper,
            'family_alpha': family_alpha, 'comparisons': comparisons,
            'method': 'one_sided_clopper_pearson_bonferroni',
            'scope': 'FROZEN_MODEL_MONTE_CARLO_ERROR_ONLY',
            'market_calibration_verified': False, 'admission': 'ABSTAIN'}


def path_risk(curve, *, initial_equity, historical_high_watermark, opening_resets=(), day_resets=()):
    """Summarize an already costed, synchronized path with explicit daily lines.

    The execution owner supplies day_start_equity on every row. No budget resets,
    synthetic intra-bar multi-asset extrema, extra fees or BASE R recomputation.
    Initial risk breaches count even when a future path recovers.
    """
    for value in (initial_equity, historical_high_watermark):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise ValueError('Finite positive absolute equity references required')
    if historical_high_watermark < initial_equity or not curve:
        raise ValueError('Existing high watermark and nonempty curve required')
    if curve[0]['equity'] != initial_equity:
        raise ValueError('First valuation must include the initial risk state')
    resets = {}
    days = {}
    for reset in day_resets:
        t = reset['time']
        if (type(t) is not int or t % 86400 or t in days
                or reset.get('source') != 'CandidatePortfolio._clock(day_change)'
                or reset['new_day'] != t // 86400 or reset['previous_day'] != t // 86400 - 1):
            raise ValueError('Original day transition evidence required')
        days[t] = reset
    for reset in opening_resets:
        t = reset['time']
        if (type(t) is not int or t % 86400 or t < curve[0]['time']
                or t > curve[-1]['time'] or t in resets
                or reset.get('source') != 'CandidatePortfolio._clock(force=True)'):
            raise ValueError('Only recorded original midnight-opening transitions allowed')
        for field in ('previous_baseline', 'new_baseline'):
            if not isinstance(reset[field], (int, float)) or not math.isfinite(reset[field]) or reset[field] <= 0:
                raise ValueError('Invalid original opening baseline')
        resets[t] = reset
    local_peak = initial_equity
    absolute_peak = historical_high_watermark
    incremental_dd = absolute_dd = 0.0
    absolute_dd = 1 - initial_equity / absolute_peak
    daily_breach = False
    prior_time = None
    baselines = {}
    for row in curve:
        t, eq = row['time'], row['equity']
        day, baseline, limit = row['risk_day_id'], row['day_start_equity'], row['daily_loss_limit']
        values = (t, eq, baseline, limit)
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in values):
            raise ValueError('Unknown valuation/baseline cannot become zero risk')
        if t < 0 or eq < 0 or baseline <= 0 or not 0 < limit < 1 or type(day) is not int or day != int(t) // 86400:
            raise ValueError('Invalid day/equity/limit')
        if prior_time is not None and t <= prior_time:
            raise ValueError('Ordered unique valuation times required')
        if prior_time is not None and t != prior_time + 300:
            raise ValueError('Risk observation gaps cannot imply non-breach')
        if prior_time is not None and day != int(prior_time) // 86400:
            reset = days.get(t)
            if (not reset or reset['new_baseline'] != baseline
                    or reset['previous_baseline'] != baselines[day - 1][0]):
                raise ValueError('Unaudited new day baseline')
        if day in baselines and baselines[day] != (baseline, limit):
            reset = resets.get(day * 86400)
            if not (reset and prior_time == reset['time'] and t == prior_time + 300
                    and baselines[day] == (reset['previous_baseline'], limit)
                    and baseline == reset['new_baseline']):
                raise ValueError('Daily budget changed inside the same UTC day')
        baselines[day] = (baseline, limit)
        prior_time = t
        local_peak, absolute_peak = max(local_peak, eq), max(absolute_peak, eq)
        incremental_dd = max(incremental_dd, 1 - eq / local_peak)
        absolute_dd = max(absolute_dd, 1 - eq / absolute_peak)
        daily_breach |= eq <= baseline * (1 - limit)
    return {'incremental_peak_drawdown': incremental_dd,
            'absolute_high_watermark_drawdown': absolute_dd,
            'daily_loss_line_breached': daily_breach,
            'terminal_net_change': curve[-1]['equity'] - initial_equity,
            'valuation_basis': 'SUPPLIED_SYNCHRONIZED_NET_EQUITY',
            'intra_bar_tail_verified': False, 'admission': 'ABSTAIN'}
