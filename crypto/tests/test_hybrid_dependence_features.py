import math
import pytest
from kquant_crypto.strategy_dual_mode_v1 import Bar
from kquant_crypto.hybrid_multifactor_dev import CORE_SYMBOLS
from kquant_crypto.hybrid_dependence_features import dependence_snapshot


def history(scale):
    prices = [100.0]
    for i in range(24):
        prices.append(prices[-1] * math.exp(scale * (.01 if i % 2 else -.005)))
    return [Bar(i*3600, p, p, p, p, 10) for i,p in enumerate(prices)]


def test_synchronized_covariance_and_future_invariance():
    rows = {s: history(scale) for s,scale in zip(CORE_SYMBOLS, [1,2,-1])}
    result = dependence_snapshot(rows, 'ETHUSDT', 25*3600)
    assert result['status'] == 'AVAILABLE'
    assert result['values']['corr_btc24'] == pytest.approx(1)
    assert result['values']['core_mean_pair_corr24'] == pytest.approx(-1/3)
    matrix = result['covariance_matrix']
    assert matrix[0][1] == matrix[1][0]
    assert matrix[1][1] == pytest.approx(4 * matrix[0][0])
    rows['BTCUSDT'].append(Bar(25*3600, 1, 999, 1, 500, 0))
    assert dependence_snapshot(rows, 'ETHUSDT', 25*3600) == result


def test_missing_peer_or_bar_not_substituted_and_flat_series_unknown():
    rows = {s: history(0) for s in CORE_SYMBOLS}
    result = dependence_snapshot(rows, 'ETHUSDT', 25*3600)
    assert result['values']['corr_btc24'] is None
    assert result['values']['vol6_to_prior18'] is None
    del rows['BTCUSDT'][4]
    assert dependence_snapshot(rows, 'ETHUSDT', 25*3600)['status'] != 'AVAILABLE'
