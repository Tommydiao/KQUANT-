"""Offline CBRM implementation. No runtime or strategy imports/consumers."""
from __future__ import annotations

def fit_development(train, evaluate, *, protocol, synthetic=False):
    """Return reproducible numeric model parameters and every evaluation row.

    Synthetic execution tests mechanics only. Real data requires a separately
    approved protocol and fixed split dates; it never changes a runtime policy.
    """
    if not synthetic and (not protocol.get('owner_approved') or not protocol.get('split', {}).get('dates')):
        raise PermissionError('RESEARCH_PROTOCOL_AND_SPLIT_APPROVAL_REQUIRED')
    import numpy as np
    from sklearn.linear_model import LogisticRegression, QuantileRegressor
    from sklearn.metrics import brier_score_loss, log_loss, mean_pinball_loss
    from sklearn.preprocessing import StandardScaler
    if not train or not evaluate:
        raise ValueError('EMPTY_PARTITION')
    rights = {r['right'] for r in train + evaluate}
    if len(rights) != 1 or not rights <= {'CALL', 'PUT'}:
        raise ValueError('FIT_RIGHTS_SEPARATELY')
    ids = [r['economic_event_id'] for r in train + evaluate]
    if len(set(ids)) != len(ids):
        raise ValueError('DUPLICATE_ECONOMIC_EVENT')
    from datetime import datetime
    first_eval = min(datetime.fromisoformat(r['signal_at']) for r in evaluate)
    if any(datetime.fromisoformat(r['label_available_at']) >= first_eval for r in train):
        raise ValueError('LABEL_BOUNDARY_LEAKAGE')
    if {r['session'] for r in train} & {r['session'] for r in evaluate}:
        raise ValueError('SESSION_SPLIT_LEAKAGE')
    support = protocol['minimum_fit_support']
    classes = np.array([r['F'] for r in train], dtype=float)
    y = np.array([r['Y'] for r in train], dtype=float)
    truth_f = np.array([r['F'] for r in evaluate], dtype=float)
    truth_y = np.array([r['Y'] for r in evaluate], dtype=float)
    if not np.isfinite(np.concatenate([classes, y, truth_f, truth_y])).all() or not set(classes) <= {0, 1} or not set(truth_f) <= {0, 1}:
        raise ValueError('INVALID_LABEL')
    if (len(train) < support['training_events_per_right'] or len({r['session'] for r in train}) < support['training_dates_per_right']
            or min(sum(classes == 0), sum(classes == 1)) < support['training_per_class']):
        return {'model_status': 'INSUFFICIENT_SUPPORT', 'training_events': len(train), 'production_consumption': False}
    result = {'model_id': protocol['protocol_id'], 'model_status': 'SYNTHETIC_TEST_ONLY' if synthetic else 'DEV_ONLY',
              'target_kind': 'UNDERLYING_PROXY_NOT_OPTION_PNL', 'production_consumption': False,
              'option_profit_probability': None, 'expected_option_pnl': None, 'calibration_status': 'NOT_CALIBRATED', 'variants': {}}
    for variant, names in [('NO_V', ['C','B','G']), ('WITH_V', ['C','V_log','B','G'])]:
        x = np.array([[r['features'][k] for k in names] for r in train], dtype=float)
        xe = np.array([[r['features'][k] for k in names] for r in evaluate], dtype=float)
        if not np.isfinite(x).all() or not np.isfinite(xe).all():
            raise ValueError('INVALID_FEATURE')
        scaler = StandardScaler().fit(x)
        xs, es = scaler.transform(x), scaler.transform(xe)
        classifier = LogisticRegression(C=protocol['logistic']['C'], max_iter=protocol['logistic']['max_iter'], random_state=protocol['seed']).fit(xs, classes)
        p = classifier.predict_proba(es)[:, 1]
        base_p = np.full(len(evaluate), classes.mean())
        quantiles, parameters, losses = [], [], []
        for q in protocol['quantile']['quantiles']:
            model = QuantileRegressor(quantile=q, alpha=protocol['quantile']['alpha'], solver='highs').fit(xs, y)
            prediction = model.predict(es)
            quantiles.append(prediction)
            parameters.append({'q': q, 'coef': model.coef_.tolist(), 'intercept': float(model.intercept_)})
            losses.append({'q': q, 'pinball': mean_pinball_loss(truth_y, prediction, alpha=q),
                           'baseline_pinball': mean_pinball_loss(truth_y, np.full(len(evaluate), np.quantile(y, q)), alpha=q)})
        qs = np.array(quantiles).T
        crossing = np.any(np.diff(qs, axis=1) < 0, axis=1)
        result['variants'][variant] = {'features': names, 'scaler_mean': scaler.mean_.tolist(), 'scaler_scale': scaler.scale_.tolist(),
            'logistic_coef': classifier.coef_.tolist(), 'logistic_intercept': classifier.intercept_.tolist(), 'quantile_parameters': parameters,
            'log_loss': log_loss(truth_f, p, labels=[0,1]), 'baseline_log_loss': log_loss(truth_f, base_p, labels=[0,1]),
            'brier': brier_score_loss(truth_f, p), 'baseline_brier': brier_score_loss(truth_f, base_p), 'quantile_metrics': losses,
            'crossing_count': int(crossing.sum()), 'predictions': [dict(economic_event_id=r['economic_event_id'], p_underlying_invalidation=float(p[i]),
                raw_quantiles=qs[i].tolist(), directional_quantiles=None if crossing[i] else qs[i].tolist(),
                state='ABSTAIN_QUANTILE_CROSSING' if crossing[i] else 'DEVELOPMENT_PREDICTION', actual_F=r['F'], actual_Y=r['Y']) for i,r in enumerate(evaluate)]}
    return result
