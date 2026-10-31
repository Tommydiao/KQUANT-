"""Exact version resolution for the isolated first-hour candidate."""
from copy import deepcopy
from first_hour import policies
from kquant import options_opening_momentum as baseline
from kquant import options_intraday_comparison as comparison


def policy_for(evaluation, *, validate=True):
    identity = evaluation.get('policy_id')
    expected = next((p for p in policies().values() if p['policy_id'] == identity), None)
    if expected is None:
        if identity == comparison.POLICY_ID:
            expected = comparison.load_policy()
        else:
            return baseline.policy_for(evaluation, validate=validate)
    if evaluation.get('policy_hash') != expected['policy_hash']:
        raise ValueError('POLICY_OR_SCOPE_CHANGED')
    # A payload may not smuggle changed thresholds behind a recognized hash.
    snapshot = evaluation.get('policy_snapshot')
    if snapshot is not None and snapshot != expected:
        raise ValueError('POLICY_SNAPSHOT_MISMATCH')
    return deepcopy(expected)


def first_hour_research(evaluation):
    return evaluation.get('policy_id') in {p['policy_id'] for p in policies().values()}
