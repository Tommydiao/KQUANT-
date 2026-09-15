"""Paired exposed-development diagnostics; never a model admission gate."""
import math

import numpy as np


def diagnostic_breakdown(rows, prediction, probability, lower, upper, *,
                         training_mean, training_positive_fraction,
                         seed=202609078, replicates=2000, block_days=7):
    n = len(rows)
    arrays = [np.asarray(v, dtype=float) for v in (prediction, probability, lower, upper)]
    if n == 0 or any(v.shape != (n,) or not np.isfinite(v).all() for v in arrays):
        raise ValueError('Finite aligned prediction vectors required')
    prediction, probability, lower, upper = arrays
    if (np.any((probability < 0) | (probability > 1)) or np.any(lower > upper)
            or not math.isfinite(training_mean) or not 0 <= training_positive_fraction <= 1):
        raise ValueError('Invalid probability, interval or baseline')
    if replicates < 2 or block_days < 1:
        raise ValueError('Invalid resampling contract')
    identities = [(r['symbol'], r['as_of']) for r in rows]
    if len(set(identities)) != n:
        raise ValueError('Duplicate opportunity cannot be another observation')
    if any(r['exclusion_reason'] is not None or r['partition'] != 'DEVELOPMENT_DIAGNOSTIC'
           or r['exposure'] != 'EXPOSED_RESEARCH'
           or r['available_at'] > r['as_of']
           or r['dependency_group'] != r['as_of'] // 86400 for r in rows):
        raise ValueError('Eligible exposed diagnostic rows required')
    y = np.asarray([r['y_log_percent'] for r in rows], dtype=float)
    if not np.isfinite(y).all():
        raise ValueError('Unknown label cannot become zero return')
    actual = (y > 0).astype(float)
    mse = (prediction - y) ** 2
    brier = (probability - actual) ** 2
    interval_score = upper - lower + 20 * np.maximum(lower - y, 0) + 20 * np.maximum(y - upper, 0)
    differences = np.column_stack((mse - (training_mean - y) ** 2,
                                   brier - (training_positive_fraction - actual) ** 2))

    def summarize(indices):
        i = np.asarray(indices)
        return {'rows': len(i), 'dependency_dates': len({rows[j]['dependency_group'] for j in i}),
                'rmse_log_percent': float(np.sqrt(mse[i].mean())),
                'mae_log_percent': float(np.abs(prediction[i] - y[i]).mean()),
                'positive_gross_brier': float(brier[i].mean()),
                'coverage90': float(((y[i] >= lower[i]) & (y[i] <= upper[i])).mean()),
                'mean_interval_width_log_percent': float((upper[i] - lower[i]).mean()),
                'mean_interval_score90_log_percent': float(interval_score[i].mean()),
                'paired_mse_difference': float(differences[i, 0].mean()),
                'paired_brier_difference': float(differences[i, 1].mean())}

    strata = {}
    for dimension in ('symbol', 'mode', 'symbol_mode'):
        groups = {}
        for i, r in enumerate(rows):
            key = r['symbol'] + ':' + r['mode'] if dimension == 'symbol_mode' else r[dimension]
            groups.setdefault(key, []).append(i)
        strata[dimension] = {key: summarize(groups[key]) for key in sorted(groups)}
    dates = sorted({r['dependency_group'] for r in rows})
    # Fixed equal calendar thirds, not outcome-selected windows or OOS folds.
    span = dates[-1] - dates[0] + 1
    temporal = {}
    for part in range(3):
        indices = [i for i, r in enumerate(rows)
                   if min(2, 3 * (r['dependency_group'] - dates[0]) // span) == part]
        temporal[str(part + 1)] = summarize(indices) if indices else {'rows': 0}
    by_date = {date: [i for i, r in enumerate(rows) if r['dependency_group'] == date] for date in dates}
    resampling = {'seed': seed, 'replicates': replicates, 'block_days': block_days,
                  'independent_oos': False, 'calibration': False,
                  'unit': 'synchronized UTC dates, all coins retained together',
                  'difference': 'model error minus frozen training-baseline error; negative is better',
                  'stable_block_count': len(dates) // block_days >= 12}
    # Never bridge a missing calendar day as if it were a continuous market block.
    if len(dates) < block_days or any(b != a + 1 for a, b in zip(dates, dates[1:])):
        resampling.update(status='UNAVAILABLE', reason='SHORT_OR_GAPPED_DATE_SERIES')
    else:
        rng = np.random.default_rng(seed)
        sums = np.asarray([differences[by_date[d]].sum(axis=0) for d in dates])
        counts = np.asarray([len(by_date[d]) for d in dates])
        values = []
        for _ in range(replicates):
            starts = rng.integers(0, len(dates) - block_days + 1,
                                  size=math.ceil(len(dates) / block_days))
            sampled = np.concatenate([np.arange(s, s + block_days) for s in starts])[:len(dates)]
            values.append(sums[sampled].sum(axis=0) / counts[sampled].sum())
        bounds = np.quantile(values, [.025, .975], axis=0)
        resampling.update(status='EXPOSED_DESCRIPTIVE_ONLY',
                          paired_mse_difference_interval95=bounds[:, 0].tolist(),
                          paired_brier_difference_interval95=bounds[:, 1].tolist())
    return {'scope': 'DEV_ONLY', 'overall': summarize(range(n)), 'strata': strata,
            'calendar_thirds_descriptive_only': temporal,
            'paired_date_block_comparison': resampling, 'runtime_enabled': False,
            'performance': 'PERFORMANCE_UNPROVEN', 'probability_calibrated': False}
