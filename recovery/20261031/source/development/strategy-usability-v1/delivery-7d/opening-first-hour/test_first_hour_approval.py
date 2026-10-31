import pytest
from first_hour import policies
from first_hour_approval import status
import first_hour_store


def test_reference_contracts_do_not_approve_first_hour():
    for policy in policies().values():
        result = status(policy, 'TEST_ONLY_SCOPE')
        assert result['qualified_signal_pipeline_enabled'] is False
        assert result['selected_expiry_group'] is None
        assert result['event_policy_sha256']
        assert result['web_policy_sha256']
        assert 'FIRST_HOUR_RESEARCH_NOT_QUALIFIED_ENTRY' in result['reasons']


def test_bad_policy_hash_rejected():
    policy = {**policies()['S1'], 'policy_hash': 'wrong'}
    with pytest.raises(ValueError, match='POLICY_HASH_MISMATCH'):
        status(policy, 'TEST_ONLY_SCOPE')
