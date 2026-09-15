import copy
import pytest
from kquant_crypto.hybrid_population_sidecar import review_population


def inputs():
    meta = dict(version='population_student_t_dev_v1', scope='DEV_ONLY', runtime_enabled=False,
        target='100*log(1+24h gross return), NOT trade netR',
        feature_order=['x'], posterior_sha256='p', diagnostics=dict(divergences=1))
    row = dict(partition='DEVELOPMENT_DIAGNOSTIC', exclusion_reason=None, symbol='BTCUSDT',
        as_of=100, mode='TREND', exposure='EXPOSED_RESEARCH', feature_order=['x'],
        available_at=100, factor_snapshot_hash='f')
    prediction = dict(symbol='BTCUSDT', as_of=100, mode='TREND', scope='DEV_ONLY',
        expected_log_percent=.1, positive_gross_probability_uncalibrated=.51,
        log_percent_quantiles05_50_95=[-2, 0, 2], actual_log_percent=999)
    return meta, [prediction], [row]


def review(args):
    return review_population(*args, prediction_hash='hash', training_label_cutoff=90)


def test_real_forecast_retained_but_outcome_excluded_and_permissions_false():
    args = inputs()
    result = review(args)[0]
    assert result['forecast']['expected_log_percent'] == .1
    decision = result['research_review']
    assert decision['decision'] == 'ABSTAIN'
    assert 'MODEL_TARGET_MISMATCH' in decision['reasons']
    assert 'NUMERICAL_DIVERGENCE_GATE_NOT_PASSED' in decision['reasons']
    assert all(v is False for k, v in decision.items() if k.startswith('allowed_'))
    args[1][0]['actual_log_percent'] = -999
    assert review(args)[0] == result


@pytest.mark.parametrize('field,value', [('scope', 'LIVE'), ('mode', 'OTHER'),
    ('positive_gross_probability_uncalibrated', 1.2),
    ('log_percent_quantiles05_50_95', [3, 2, 1]), ('expected_log_percent', float('nan'))])
def test_invalid_forecast_rejected(field, value):
    args = inputs()
    args[1][0][field] = value
    with pytest.raises(ValueError):
        review(args)


def test_duplicates_and_metadata_changes():
    args = inputs()
    original = review(args)[0]['evidence_id']
    args[0]['diagnostics']['divergences'] = 0
    assert review(args)[0]['evidence_id'] != original
    args[1].append(copy.deepcopy(args[1][0]))
    with pytest.raises(ValueError, match='identity'):
        review(args)


def test_net_r_relabel_or_missing_target_rejected():
    args=inputs();args[0]['target']='ENTRY_POLICY_NET_R'
    with pytest.raises(ValueError,match='target'):review(args)
    args[0].pop('target')
    with pytest.raises(ValueError,match='target'):review(args)
