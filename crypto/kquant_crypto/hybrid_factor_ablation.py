"""Fixed leave-one-factor-out diagnostics inside the existing TRAIN partition."""
import numpy as np

from .hybrid_factor_experiments import fit_ridge, predict

FEATURES = ('return_6h', 'er24', 'relative_volume24', 'relative_core24')


def train_ablation(rows):
    rows = sorted(rows, key=lambda r: (r['as_of'], r['symbol']))
    if not rows or any(r['partition'] != 'TRAIN' or r['exclusion_reason'] is not None
                       or r['exposure'] != 'EXPOSED_RESEARCH'
                       or r['feature_order'] != list(FEATURES)
                       or r['available_at'] > r['as_of']
                       or r['label_available_at'] != r['as_of'] + 86400 for r in rows):
        raise ValueError('Only eligible frozen24h TRAIN rows are authorized')
    if len({(r['symbol'], r['as_of']) for r in rows}) != len(rows):
        raise ValueError('Duplicate opportunities')
    dates = sorted({r['as_of'] for r in rows})
    if len(dates) < 30 or any(t % 86400 for t in dates):
        raise ValueError('At least30 UTC daily dates required')
    if any(b != a + 86400 for a, b in zip(dates, dates[1:])):
        raise ValueError('Gapped daily population')
    variants = [('FULL', list(range(4)))] + [
        ('WITHOUT_' + name, [k for k in range(4) if k != j]) for j, name in enumerate(FEATURES)]
    results = []
    for fraction in (.4, .6, .8):
        start = dates[int(len(dates) * fraction)]
        end_index = min(len(dates), int(round(len(dates) * (fraction + .2))))
        end = dates[end_index] if end_index < len(dates) else dates[-1] + 86400
        train = [r for r in rows if r['as_of'] < start and r['label_available_at'] < start - 86400]
        validation = [r for r in rows if start <= r['as_of'] < end and r['label_available_at'] < end]
        if len(train) < 2 or not validation:
            raise ValueError('Insufficient purged fold')
        tx = np.asarray([r['x'] for r in train], dtype=float)
        ty = np.asarray([r['y_log_percent'] for r in train], dtype=float)
        vx = np.asarray([r['x'] for r in validation], dtype=float)
        vy = np.asarray([r['y_log_percent'] for r in validation], dtype=float)
        if not all(np.isfinite(a).all() for a in (tx, ty, vx, vy)):
            raise ValueError('Missing label/feature cannot be imputed')
        scores = []
        for name, cols in variants:
            model = fit_ridge(tx[:, cols], ty, alpha=1.0)
            forecast = predict(model, vx[:, cols])
            scores.append({'variant': name, 'features': [FEATURES[j] for j in cols],
                           'mse_log_percent': float(np.mean((forecast - vy) ** 2)),
                           'mae_log_percent': float(np.mean(abs(forecast - vy))),
                           'frozen_train_preprocessing': model})
        for score in scores:
            score['mse_difference_from_full'] = score['mse_log_percent'] - scores[0]['mse_log_percent']
        results.append({'start': start, 'end': end, 'train_rows': len(train),
                        'validation_rows': len(validation),
                        'train_ids': [[r['symbol'], r['as_of']] for r in train],
                        'validation_ids': [[r['symbol'], r['as_of']] for r in validation],
                        'train_mean_mse': float(np.mean((ty.mean() - vy) ** 2)), 'scores': scores})
    return {'scope': 'TRAIN_PARTITION_INTERNAL_DEV_DIAGNOSTIC', 'folds': results,
            'automatic_selection': False, 'runtime_enabled': False,
            'independent_oos': False, 'performance': 'PERFORMANCE_UNPROVEN',
            'limits': 'Correlated coins; fixed ablations do not change the active Bayesian features or strategy.'}
