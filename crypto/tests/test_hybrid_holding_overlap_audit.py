import pytest
from kquant_crypto.hybrid_holding_overlap_audit import audit


def row(t=400, known=1200, entry=100):
    return dict(policy='T1', trade_id='one', as_of=t, available_at=t,
        holding_features={'age_seconds': t-entry}, label_available_at=known,
        scope='DEV_ONLY', runtime_enabled=False, independent_oos=False, label_status='MATURE')


def test_cross_boundary_group_all_purged():
    result = audit([row(), row(1100)], 1000)
    assert result['policies']['T1']['observations'] == {'BOUNDARY_PURGED': 2}
    assert not result['training_enabled']


def test_labels_must_be_known_strictly_before_boundary():
    assert audit([row(known=1000)], 1000)['policies']['T1']['holding_groups'] == {'BOUNDARY_PURGED': 1}
    assert audit([row(known=900)], 1000)['policies']['T1']['holding_groups'] == {'TRAIN_LABELS_KNOWN': 1}


def test_duplicate_rejected():
    with pytest.raises(ValueError, match='Duplicate'):
        audit([row(), row()], 1000)


def test_long_holding_does_not_inherit_six_hour_bound():
    assert not audit([row(known=90000)], 1000)['policies']['T1']['original_six_hour_bound_sufficient']
