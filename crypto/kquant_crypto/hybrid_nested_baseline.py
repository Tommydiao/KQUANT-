"""Small fixed inner-only regression comparison, not a trading selector."""
import numpy as np
from .hybrid_factor_experiments import fit_ridge, predict

ALPHAS = (1.0, .1, 10.0)


def inner_choice(train_x, train_y, validation_x, validation_y):
    y = np.asarray(validation_y, dtype=float)
    if not len(y) or not np.isfinite(y).all():
        raise ValueError('Finite inner validation outcomes required')
    scores = []
    for alpha in ALPHAS:
        model = fit_ridge(train_x, train_y, alpha)
        predicted = predict(model, validation_x)
        if predicted.shape != y.shape or not np.isfinite(predicted).all():
            raise ValueError('Inner prediction contract failure')
        scores.append({'alpha': alpha, 'inner_mse': float(np.mean((y-predicted)**2))})
    winner = min(range(len(scores)), key=lambda i:scores[i]['inner_mse'])
    return {'alpha': scores[winner]['alpha'], 'scores': scores,
            'selection_scope': 'INNER_EXPOSED_DEV_ONLY', 'runtime_enabled': False}
