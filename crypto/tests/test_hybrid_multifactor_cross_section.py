import pytest

from kquant_crypto.hybrid_multifactor_dev import CORE_SYMBOLS, cross_section


def peers():
    return {s: {'status': 'AVAILABLE', 'as_of': 100, 'available_at': 100,
                'values': {'return_24h': r}}
            for s, r in zip(CORE_SYMBOLS, (.1, .2, -.3))}


def test_cross_section_exact_time_and_scope():
    result = cross_section(peers(), 'ETHUSDT', 100)
    assert result['values']['relative_btc24'] == pytest.approx(.1)
    assert result['values']['relative_core24'] == pytest.approx(.2)
    assert result['values']['core_positive_breadth24'] == 2/3
    assert result['scope'] == 'THREE_CORE_ASSETS_NOT_WHOLE_MARKET'


@pytest.mark.parametrize('fault', ['missing', 'stale', 'future', 'nan'])
def test_peer_contract_fails_closed(fault):
    rows = peers()
    if fault == 'missing':
        del rows['BTCUSDT']
    elif fault == 'stale':
        rows['BTCUSDT']['as_of'] = 99
    elif fault == 'future':
        rows['BTCUSDT']['available_at'] = 101
    else:
        rows['BTCUSDT']['values']['return_24h'] = float('nan')
    result = cross_section(rows, 'ETHUSDT', 100)
    assert result['status'] == 'UNAVAILABLE_PEER_CONTRACT'
    assert all(v is None for v in result['values'].values())
