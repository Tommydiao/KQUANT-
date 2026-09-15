"""Research compatibility review, isolated from formal EVAL and order consumers."""
import hashlib
import json
import math

TARGETS = {
    'multifactor_entry_student_t_dev_v1': 'LEGACY_BAR_PROXY_BASE_10_5_NET_R',
    'population_student_t_dev_v1': 'DESCRIPTIVE_24H_GROSS_LOG_PERCENT',
}


def review_plan_evidence(meta, plan, *, purpose, model_available_at, training_label_cutoff):
    if purpose != 'DEV_ONLY':
        raise ValueError('Research sidecar cannot authorize a formal consumer')
    reasons = ['EXPOSED_DEVELOPMENT_MODEL_NOT_ADMISSION_EVIDENCE']
    if meta.get('scope') != 'DEV_ONLY' or meta.get('runtime_enabled') is not False:
        raise ValueError('Unsafe artifact scope')
    target = TARGETS.get(meta.get('version'))
    if target is None or target != plan.get('requested_target'):
        reasons.append('MODEL_TARGET_MISMATCH')
    signal = plan.get('signal_time')
    if type(signal) is not int or signal < 0:
        reasons.append('SIGNAL_TIME_UNKNOWN')
    else:
        if type(model_available_at) is not int:
            reasons.append('MODEL_AVAILABLE_AT_UNVERIFIED')
        elif model_available_at > signal:
            reasons.append('MODEL_NOT_AVAILABLE_AT_SIGNAL')
        if type(training_label_cutoff) is not int:
            reasons.append('TRAINING_CUTOFF_UNVERIFIED')
        elif training_label_cutoff > signal:
            reasons.append('TRAINING_LABELS_AFTER_SIGNAL')
        if type(plan.get('feature_available_at')) is not int or plan['feature_available_at'] > signal:
            reasons.append('FEATURE_AVAILABILITY_INVALID')
    if plan.get('execution_quality') != 'QUOTE_AWARE':
        reasons.append('HISTORICAL_PROXY_NOT_STRICT_QUOTE_EXECUTION')
    if plan.get('strategy_gate') != 'PASS':
        reasons.append('STRATEGY_EVIDENCE_NOT_PASSED')
    geometry = [plan.get(k) for k in ('entry', 'stop', 'target')]
    if (any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in geometry)
            or not 0 < geometry[1] < geometry[0] < geometry[2]):
        reasons.append('PLAN_GEOMETRY_INVALID')
    diagnostics = meta.get('diagnostics', {})
    for field in ('mean_validated', 'profit_probability_validated', 'tail_validated'):
        if diagnostics.get(field) is not True:
            reasons.append(field.upper() + '_NOT_GRANTED')
    identity = {'model_hash': meta.get('posterior_sha256'), 'model_version': meta.get('version'),
        'plan': plan, 'model_available_at': model_available_at, 'training_label_cutoff': training_label_cutoff}
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return {'review_id': digest, 'scope': 'DEV_ONLY', 'decision': 'ABSTAIN',
        'reasons': reasons, 'target_contract': target, 'input_evidence': identity,
        'usable_prediction': None, 'allowed_formal_eval': False, 'allowed_alert': False,
        'allowed_paper': False, 'allowed_shadow': False, 'allowed_sizing': False,
        'allowed_execution': False, 'formal_gate_changed': False,
        'review_kind': 'RETROSPECTIVE_COMPATIBILITY_AUDIT_NOT_HISTORICAL_DECISION'}
