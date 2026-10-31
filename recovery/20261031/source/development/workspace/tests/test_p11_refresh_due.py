from datetime import UTC, datetime, timedelta

from kquant.options_price_action_source import refresh_due_at, action_counts


def observation(now, elapsed, ttl):
    return {'requested_at': now.isoformat(),
            'received_at': (now + timedelta(seconds=elapsed)).isoformat(),
            'coverage_fact': {'valid_until': (now + timedelta(seconds=ttl)).isoformat()}}


def test_expiry_shortened_by_source_proof_is_respected():
    now = datetime(2026, 10, 12, tzinfo=UTC)
    row = observation(now, 2, 120)
    assert refresh_due_at(row, completed_at=now + timedelta(seconds=3)) == now + timedelta(seconds=60)


def test_request_latency_is_reserved_before_expiry():
    now = datetime(2026, 10, 12, tzinfo=UTC)
    row = observation(now, 100, 900)
    assert refresh_due_at(row, completed_at=now + timedelta(seconds=101)) == now + timedelta(seconds=795)


def test_expired_response_does_not_create_tight_retry_loop():
    now = datetime(2026, 10, 12, tzinfo=UTC)
    row = observation(now, 100, 90)
    completed = now + timedelta(seconds=101)
    assert refresh_due_at(row, completed_at=completed) == completed + timedelta(seconds=5)


def test_failure_backoff_starts_at_completion():
    now = datetime(2026, 10, 12, tzinfo=UTC)
    assert refresh_due_at({'status': 'SOURCE_REQUEST_FAILED'}, completed_at=now) == now + timedelta(seconds=300)


def test_observed_incomplete_is_not_fresh_and_expired_is_separate():
    now = datetime(2026, 10, 12, tzinfo=UTC)
    ready = {'coverage_complete': True, 'price_scale_state': 'UNCHANGED',
             'received_at': now.isoformat(), 'valid_until': (now + timedelta(seconds=10)).isoformat()}
    rows = {'ready': ready, 'partial': {**ready, 'coverage_complete': False},
            'expired': {**ready, 'valid_until': now.isoformat()},
            'missing': {'queued_at': (now - timedelta(seconds=60)).isoformat()}}
    result = action_counts(rows, now)
    assert result['fresh'] == 1
    assert result['expired'] == 1
    assert result['not_observed'] == 1
    assert result['oldest_first_coverage_age_seconds'] == 60
