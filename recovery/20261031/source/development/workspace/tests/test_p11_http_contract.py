from copy import deepcopy
import hashlib
import json

import pytest
from scripts import check_r58_p10_topology as harness


def fixture(monkeypatch):
    monkeypatch.setattr(harness, 'monotonic', lambda: 9)
    contract = harness.crash_http_contract(8, 7)
    fault = dict(killed_pid=8, replacement_pid=9, observer_pid=7,
                 fault_monotonic_start=10, replacement_ready_monotonic=12,
                 snapshot_ready_monotonic=13, pending_before=3, restored=3,
                 original_deadlines_preserved=True,
                 initial_snapshots={'states': {'current': 'FRESH', 'compact': 'FRESH'}},
                 http_contract=contract)
    row = dict(path='/api/stocks/health/live', observer_pid=7,
               monotonic_start=11, seconds=.1, status=503,
               response_error_code='UPSTREAM_CONNECTION_FAILED',
               response_error_origin='GATEWAY_UPSTREAM')
    success = dict(path=row['path'], observer_pid=7, monotonic_start=14, seconds=.1, status=200)
    return row, fault, success


def test_predeclared_exact_fault_requires_actual_recovery(monkeypatch):
    row, fault, success = fixture(monkeypatch)
    result = harness.classify_http_failures([row, success], [fault])[0]
    assert result['classification'] == 'EXPECTED_INJECTED_FAILURE'
    assert result['matched_contracts'] == [fault['http_contract']['sha256']]
    assert not result['causal_attribution_proven']
    assert harness.classify_http_failures([row], [fault])[0]['classification'] == 'UNEXPLAINED'


@pytest.mark.parametrize('change', [dict(status=401), dict(path='/unrelated'),
    dict(response_error_code='UNCLASSIFIED_RESPONSE'), dict(response_error_origin='UNKNOWN'),
    dict(seconds=4), dict(observer_pid=12), dict(monotonic_start=20),
    dict(response_error_code='UPSTREAM_TIMEOUT')])
def test_unrelated_failures_are_not_waived(monkeypatch, change):
    row, fault, success = fixture(monkeypatch)
    assert harness.classify_http_failures([{**row, **change}, success], [fault])[0]['classification'] == 'UNEXPLAINED'


@pytest.mark.parametrize('change', [dict(restored=2), dict(original_deadlines_preserved=False),
    dict(snapshot_ready_monotonic=30), dict(replacement_pid=8)])
def test_recovery_must_meet_bounds(monkeypatch, change):
    row, fault, success = fixture(monkeypatch)
    assert harness.classify_http_failures([row, success], [{**fault, **change}])[0]['classification'] == 'UNEXPLAINED'


def test_contract_must_precede_injection_and_be_unchanged(monkeypatch):
    row, fault, success = fixture(monkeypatch)
    fault['http_contract']['registered_monotonic'] = 11
    assert not harness.matches_crash_contract(row, fault, [success])
    unsigned = {k:v for k,v in fault['http_contract'].items() if k != 'sha256'}
    fault['http_contract']['sha256'] = hashlib.sha256(json.dumps(unsigned, sort_keys=True).encode()).hexdigest()
    assert not harness.matches_crash_contract(row, fault, [success])


def test_contract_tampering_is_rejected_independently(monkeypatch):
    row, fault, success = fixture(monkeypatch)
    assert harness.matches_crash_contract(row, fault, [success])
    fault['http_contract']['registered_monotonic'] = 8
    assert not harness.matches_crash_contract(row, fault, [success])


def test_timeout_needs_connection_phase_before_http_started(monkeypatch):
    row, fault, success = fixture(monkeypatch)
    row.update(response_error_code='UPSTREAM_TIMEOUT', response_failure_stage='CONNECT')
    assert harness.matches_crash_contract(row, fault, [success])
    row['response_failure_stage'] = 'RECEIVE'
    assert not harness.matches_crash_contract(row, fault, [success])
    row.update(response_failure_stage='CONNECT', monotonic_start=12.1)
    assert not harness.matches_crash_contract(row, fault, [success])
