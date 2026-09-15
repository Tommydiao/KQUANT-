from types import SimpleNamespace

import pytest

np = pytest.importorskip('numpy')
xr = pytest.importorskip('xarray')

from scripts.localize_hybrid_sampler_saturation import scalar_series


def test_modes_preserve_names_and_draws():
    scalar = xr.DataArray(np.ones((1, 3)), dims=('chain', 'draw'))
    modes = xr.DataArray(np.array([[[1, 8], [2, 9], [3, 10]]]),
                         dims=('chain', 'draw', 'mode'),
                         coords={'mode': ['TREND', 'RANGE']})
    trace = SimpleNamespace(
        sample_stats={n: scalar for n in ('acceptance_rate', 'energy', 'lp')},
        posterior={'tau': modes, 'sigma': modes, 'nu': scalar})
    result = dict(scalar_series(trace, 0))
    assert result['tau[TREND]'].tolist() == [1, 2, 3]
    assert result['tau[RANGE]'].tolist() == [8, 9, 10]
    assert result['nu'].shape == (3,)
    trace.posterior['tau'] = modes.rename({'mode': 'unknown'})
    with pytest.raises(ValueError, match='Unexpected posterior dimensions'):
        dict(scalar_series(trace, 0))
