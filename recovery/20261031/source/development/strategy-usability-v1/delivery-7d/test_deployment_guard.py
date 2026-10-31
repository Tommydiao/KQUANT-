from copy import deepcopy
from pathlib import Path
import pytest
from apply_accepted_delta import checked_path, digest, verify_receipt


def context(tmp_path):
    scope = tmp_path/'scope.md'
    scope.write_text('TEST_ONLY exact limited research launch')
    projection = dict(candidate_id='TEST_ONLY-new', candidate_payload_sha256='a'*64)
    recovery = dict(continuity=dict(receipt=dict(sha256='b'*64)))
    receipt = dict(gate='O-LAUNCH', approved_by='OWNER', status='APPROVED',
        candidate_id='TEST_ONLY-new', candidate_payload_sha256='a'*64,
        runtime_root=str(tmp_path/'runtime'), continuity_receipt_sha256='b'*64,
        scope='SHADOW_STARTUP_RESEARCH_OBSERVATIONS_ONLY',
        human_decision_evidence=dict(source='DIRECT_USER_REPLY', reference='TEST_ONLY',
            answer='TEST_ONLY', scope_document=str(scope), scope_document_sha256=digest(scope)))
    for name in ('qualified_signal_authorized', 'source_facts_approved', 'orders_authorized',
                 'system_clock_change_authorized', 's1_manual_policy_authorized', 'system_autostart_authorized'):
        receipt[name] = False
    return projection, recovery, receipt


def test_matching_limited_scope_validates_without_writing(tmp_path):
    projection, recovery, receipt = context(tmp_path)
    before = list(tmp_path.iterdir())
    verify_receipt(receipt, projection, recovery, tmp_path)
    assert list(tmp_path.iterdir()) == before


@pytest.mark.parametrize('field,value', [('candidate_id', 'TEST_ONLY-old'),
    ('candidate_payload_sha256', 'c'*64), ('gate', 'O-SETUP'),
    ('approved_by', 'AUTOMATED'), ('runtime_root', 'F:\\old')])
def test_old_launch_or_method_receipt_is_rejected(tmp_path, field, value):
    projection, recovery, receipt = context(tmp_path)
    receipt[field] = value
    with pytest.raises(ValueError, match='EXACT_SHADOW_ACCEPTANCE_REQUIRED'):
        verify_receipt(receipt, projection, recovery, tmp_path)


def test_extra_scope_and_changed_scope_document_fail(tmp_path):
    projection, recovery, receipt = context(tmp_path)
    modified = deepcopy(receipt)
    modified['orders_authorized'] = True
    with pytest.raises(ValueError, match='UNEXPECTED_APPROVAL_SCOPE'):
        verify_receipt(modified, projection, recovery, tmp_path)
    Path(receipt['human_decision_evidence']['scope_document']).write_text('changed')
    with pytest.raises(ValueError, match='ACCEPTED_SCOPE_CHANGED'):
        verify_receipt(receipt, projection, recovery, tmp_path)


def test_parent_escape_is_rejected(tmp_path):
    with pytest.raises(ValueError, match='PATH_OUTSIDE_APPROVED_ROOT'):
        checked_path(tmp_path/'..'/'outside.json', tmp_path)
