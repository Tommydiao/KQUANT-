from dataclasses import replace

import pytest

from kquant_crypto.hybrid_label_contract import LabelRecord, eligible_training_labels


def label(**changes):
    value=LabelRecord('signal1','delayed1','executed_virtual','mature',.5,100,200,
                      'historical_ohlcv_proxy','utc_day1')
    return replace(value,**changes)


@pytest.mark.parametrize('status',['censored','unavailable'])
def test_censored_labels_cannot_be_zero_filled(status):
    assert label(status=status,net_r=None).net_r is None
    with pytest.raises(ValueError,match='zero-filled'):
        label(status=status,net_r=0)


def test_termination_is_not_a_mature_exit():
    ended=label(source='termination_liquidation',status='terminated')
    assert eligible_training_labels([ended],cutoff=300,source='executed_virtual',execution_policy_hash='delayed1')==[]
    with pytest.raises(ValueError,match='Termination'):
        label(source='termination_liquidation')


def test_future_counterfactual_policy_and_synthetic_are_not_merged():
    actual=label()
    rows=[actual,label(available_at=400),label(source='counterfactual'),
          label(execution_policy_hash='legacy_open'),label(execution_quality='synthetic_fixture')]
    assert eligible_training_labels(rows,cutoff=300,source='executed_virtual',execution_policy_hash='delayed1')==[actual]
    with pytest.raises(ValueError,match='Duplicate'):
        eligible_training_labels([actual,actual],cutoff=300,source='executed_virtual',execution_policy_hash='delayed1')


def test_proxy_cannot_claim_real_exchange_fill():
    with pytest.raises(ValueError,match='execution evidence'):
        label(execution_quality='exchange_fill')


def test_unknown_labels_never_become_finite_predictions():
    with pytest.raises(ValueError,match='Observed'):
        label(net_r=float('nan'))
    with pytest.raises(ValueError,match='signal'):
        label(available_at=99)
