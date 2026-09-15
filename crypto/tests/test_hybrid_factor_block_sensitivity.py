import copy

import pytest

pytest.importorskip('scipy', reason='Factor sensitivity runs in the isolated math environment')
from kquant_crypto.hybrid_factor_block_sensitivity import sensitivity, FEATURES


def rows():
    return [dict(symbol=symbol, as_of=day*86400, available_at=day*86400,
        label_available_at=(day+1)*86400, partition='TRAIN', exclusion_reason=None,
        exposure='EXPOSED_RESEARCH', feature_order=list(FEATURES),
        x=[day, -day, 1, day % 9], y_log_percent=day)
        for day in range(100, 185) for symbol in ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')]


def test_calendar_deletion_preserves_cross_asset_group_and_constant_missing():
    source = rows()
    before = copy.deepcopy(source)
    result = sensitivity(source)
    assert source == before
    assert result['rows'] == 255 and result['dates'] == 85
    assert len(result['blocks']) == 13
    assert result['blocks'][-1]['removed_rows'] == 3
    assert result['blocks'][-1]['partial'] is True
    assert all(b['removed_rows'] == 21 for b in result['blocks'][:-1])
    assert result['factors']['return_6h']['full_spearman'] == pytest.approx(1)
    assert result['factors']['er24']['full_spearman'] == pytest.approx(-1)
    assert result['factors']['relative_volume24']['full_spearman'] is None
    assert result['automatic_selection'] is False
    assert result['independent_oos'] is False
    assert sensitivity(list(reversed(source))) == result


@pytest.mark.parametrize('field,value', [('partition', 'TEST'), ('available_at', 10**12),
    ('label_available_at', 0), ('exposure', 'UNEXPOSED'), ('x', [float('nan')]*4)])
def test_invalid_training_contract_rejected(field, value):
    data = rows()
    data[0][field] = value
    with pytest.raises(ValueError):
        sensitivity(data)


def test_duplicates_and_missing_coin_rejected():
    data = rows()
    with pytest.raises(ValueError, match='Duplicate'):
        sensitivity(data+[data[0]])
    with pytest.raises(ValueError, match='Synchronized'):
        sensitivity(data[1:])
