import pytest
from kquant_crypto.hybrid_rule_archive import save_snapshot, read_snapshot


def save(path, at=10):
    return save_snapshot(path, {'symbols':[]}, received_at=at, source='BINANCE_SPOT_PUBLIC_EXCHANGE_INFO')


def test_immutable_versions_and_duplicate(tmp_path):
    first=save(tmp_path)
    assert save(tmp_path)==first
    second=save(tmp_path,11)
    assert second != first
    assert read_snapshot(tmp_path,first)['received_at']==10
    assert not read_snapshot(tmp_path,second)['execution_allowed']


def test_corruption_rejected_not_overwritten(tmp_path):
    first=save(tmp_path)
    (tmp_path / (first+'.json')).write_text('{}')
    with pytest.raises(ValueError):
        read_snapshot(tmp_path,first)
    with pytest.raises(ValueError):
        save(tmp_path)


def test_path_not_accepted_as_identity(tmp_path):
    with pytest.raises(ValueError):
        read_snapshot(tmp_path,'../other')
