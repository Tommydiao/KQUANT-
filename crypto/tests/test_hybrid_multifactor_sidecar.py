import pytest

from kquant_crypto.hybrid_multifactor_sidecar import review_plan_evidence


def inputs():
    return ({'version': 'multifactor_entry_student_t_dev_v1', 'scope': 'DEV_ONLY',
             'runtime_enabled': False, 'posterior_sha256': 'frozen', 'diagnostics': {}},
            {'signal_time': 100, 'feature_available_at': 100, 'entry': 100, 'stop': 90,
             'target': 120, 'execution_quality': 'LEGACY_BAR_PROXY', 'strategy_gate': 'NO_GO',
             'requested_target': 'LEGACY_BAR_PROXY_BASE_10_5_NET_R'})


def test_development_model_never_grants_formal_permission():
    meta, plan = inputs()
    review = review_plan_evidence(meta, plan, purpose='DEV_ONLY',
                                  model_available_at=None, training_label_cutoff=110)
    assert review['decision'] == 'ABSTAIN'
    assert 'TRAINING_LABELS_AFTER_SIGNAL' in review['reasons']
    assert 'MODEL_AVAILABLE_AT_UNVERIFIED' in review['reasons']
    assert review['usable_prediction'] is None
    assert all(v is False for k, v in review.items() if k.startswith('allowed_'))


def test_population_gross_return_is_not_plan_net_r():
    meta, plan = inputs()
    meta['version'] = 'population_student_t_dev_v1'
    review = review_plan_evidence(meta, plan, purpose='DEV_ONLY', model_available_at=90, training_label_cutoff=80)
    assert 'MODEL_TARGET_MISMATCH' in review['reasons']


@pytest.mark.parametrize('purpose', ['EVAL', 'PAPER', 'SHADOW', 'LIVE', 'SIZING'])
def test_formal_consumers_rejected(purpose):
    meta, plan = inputs()
    with pytest.raises(ValueError):
        review_plan_evidence(meta, plan, purpose=purpose, model_available_at=0, training_label_cutoff=0)
