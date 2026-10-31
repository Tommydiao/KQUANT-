"""Bind reference contracts explicitly; never grant first-hour qualification."""
from kquant import options_opening_trend_approval as original
from first_hour import policies


def status(policy, scope_hash, **kwargs):
    expected = next((p for p in policies().values() if p['policy_id'] == policy['policy_id']), None)
    if expected is None:
        return original.status(policy, scope_hash, **kwargs)
    if policy['policy_hash'] != expected['policy_hash']:
        raise ValueError('POLICY_HASH_MISMATCH')
    root = original.ROOT
    result = original.status(policy, scope_hash,
        event_policy=root/'config/options_opening_momentum_event_coverage_v1.json',
        web_policy=root/'config/options_opening_momentum_web_policy_v1.json', **kwargs)
    result.update(qualified_signal_pipeline_enabled=False, selected_expiry_group=None)
    result['reasons'] = list(dict.fromkeys(result['reasons'] + ['FIRST_HOUR_RESEARCH_NOT_QUALIFIED_ENTRY']))
    return result
