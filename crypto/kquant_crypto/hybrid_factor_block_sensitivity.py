"""TRAIN-only calendar-block influence diagnostics, never a selection gate."""
import numpy as np
from scipy.stats import spearmanr

from .hybrid_factor_ablation import FEATURES


def sensitivity(rows):
    rows = sorted(rows, key=lambda r: (r['as_of'], r['symbol']))
    if not rows or any(r['partition'] != 'TRAIN' or r['exclusion_reason'] is not None
        or r['exposure'] != 'EXPOSED_RESEARCH' or r['feature_order'] != list(FEATURES)
        or r['available_at'] > r['as_of']
        or r['label_available_at'] != r['as_of'] + 86400 for r in rows):
        raise ValueError('Frozen eligible TRAIN rows required')
    keys = [(r['symbol'], r['as_of']) for r in rows]
    if len(set(keys)) != len(keys):
        raise ValueError('Duplicate population rows')
    dates = sorted({r['as_of'] for r in rows})
    if len(dates) < 84 or any(t % 86400 for t in dates):
        raise ValueError('At least twelve weeks of UTC daily rows required')
    if any(b-a != 86400 for a, b in zip(dates, dates[1:])):
        raise ValueError('Gapped daily population')
    if any({r['symbol'] for r in rows if r['as_of'] == t} !=
           {'BTCUSDT', 'ETHUSDT', 'SOLUSDT'} for t in dates):
        raise ValueError('Synchronized core universe required')
    x = np.asarray([r['x'] for r in rows], dtype=float)
    y = np.asarray([r['y_log_percent'] for r in rows], dtype=float)
    if x.shape != (len(rows), len(FEATURES)) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Missing/nonfinite inputs cannot be imputed')
    times = np.asarray([r['as_of'] for r in rows])

    def relation(ids, j):
        a, b = x[ids, j], y[ids]
        if len(np.unique(a)) < 2 or len(np.unique(b)) < 2:
            return None
        return float(spearmanr(a, b).statistic)

    full = [relation(np.ones(len(rows), dtype=bool), j) for j in range(len(FEATURES))]
    blocks = []
    for start in range(dates[0], dates[-1]+86400, 7*86400):
        end = start+7*86400
        removed = (times >= start) & (times < end)
        kept = ~removed
        blocks.append(dict(start=start, end=end, removed_rows=int(removed.sum()),
            partial=end > dates[-1]+86400,
            correlations={f: relation(kept, j) for j, f in enumerate(FEATURES)}))
    factors = {}
    for j, f in enumerate(FEATURES):
        values = [b['correlations'][f] for b in blocks if b['correlations'][f] is not None]
        base = full[j]
        factors[f] = dict(full_spearman=base, deletion_min=min(values) if values else None,
            deletion_max=max(values) if values else None,
            sign_flips=sum(base*v < 0 for v in values) if base is not None else None,
            max_absolute_change=max(abs(v-base) for v in values) if values and base is not None else None)
    return dict(scope='DEV_ONLY_TRAIN_DESCRIPTIVE', rows=len(rows), dates=len(dates),
        factors=factors, blocks=blocks, automatic_selection=False, runtime_enabled=False,
        independent_oos=False, performance='PERFORMANCE_UNPROVEN',
        limitations='Overlapping deletion samples are not independent folds or confidence intervals. '
                    'Target is gross24h log-percent return, not net trade R. No probability calibration.')
