"""TEST_ONLY archives exercise document/reply parity; no production acceptance."""
from datetime import UTC, datetime

from kquant import options_price_action_source as actions
from test_r58_p10_safe_closeout import action_method, action_observation


def test_reviewed_official_document_does_not_require_email_container(tmp_path):
    now = datetime(2026, 10, 2, 13, 35, tzinfo=UTC)
    proof = action_method(tmp_path, now)
    proof.update(source_kind='OFFICIAL_DOCUMENT',
                 source_url='https://open.longbridge.com/docs/test-only-company-actions')
    proof.pop('authenticity_review_path')
    proof.pop('authenticity_review_sha256')
    fact = actions.coverage_fact(action_observation(now), method=proof, now=now, root=tmp_path)
    assert fact['complete'] is True
    assert fact['owner_approval'] is False
    assert fact['price_scale_state'] == 'UNCHANGED'
    assert actions.valid_fact(fact, symbol='TEST', previous='2026-10-01', session='2026-10-02',
                              now=now, root=tmp_path)


def test_document_still_requires_exact_semantics_and_unchanged_original(tmp_path):
    now = datetime(2026, 10, 2, 13, 35, tzinfo=UTC)
    proof = action_method(tmp_path, now)
    proof.update(source_kind='OFFICIAL_DOCUMENT',
                 source_url='https://open.longbridge.com/docs/test-only-company-actions')
    observation = action_observation(now)
    bad = {**proof, 'source_url': 'https://untrusted.invalid/company-actions'}
    assert not actions.coverage_fact(observation, method=bad, now=now, root=tmp_path)['complete']
    assert not actions.coverage_fact(observation, method={**proof, 'claim_hash': 'wrong'},
                                     now=now, root=tmp_path)['complete']
    (tmp_path / 'action-reply.txt').write_bytes(b'changed original')
    assert not actions.coverage_fact(observation, method=proof, now=now, root=tmp_path)['complete']
