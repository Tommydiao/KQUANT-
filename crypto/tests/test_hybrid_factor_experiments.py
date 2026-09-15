import numpy as np
import pytest
from kquant_crypto.hybrid_factor_experiments import fit_ridge, predict, diagnostics


def test_training_only_and_finite_constant_feature():
    x = np.column_stack((np.arange(20.), np.ones(20)))
    y = np.arange(20.)/100
    model = fit_ridge(x[:10],y[:10])
    baseline = dict(model)
    x[10:] = 999999
    y[10:] = -999
    assert fit_ridge(x[:10],y[:10]) == baseline
    assert np.isfinite(predict(model,x[10:])).all()
    report = diagnostics(x[:10],y[:10],['varying','constant'])
    assert report['correlation'][1][1] is None
    assert sum(g['count'] for g in report['buckets']['constant']['groups']) == 10


def test_missing_values_not_imputed():
    with pytest.raises(ValueError):
        fit_ridge([[1],[float('nan')]],[0,1])
