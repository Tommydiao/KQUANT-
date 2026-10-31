from scripts.check_r58_p10_topology import classify_http_failures
from scripts.check_r58_p10_topology import wait_http_started
from scripts.check_r58_p10_topology import wait_initial_snapshots
from types import SimpleNamespace
import pytest


def test_only_same_observer_overlapping_requests_are_classified():
    fault = dict(observer_pid=7, killed_pid=8, fault_monotonic_start=10,
                 replacement_ready_monotonic=12)
    rows = [dict(request_id=str(i), path='/live', observer_pid=pid,
                 monotonic_start=start, seconds=duration, status=status)
            for i, (pid, start, duration, status) in enumerate([
                (7, 9.5, 1, 503), (7, 12.1, .1, 503),
                (9, 11, .1, 503), (7, 11, .1, 200)])]
    result = classify_http_failures(rows, [fault])
    assert [r['classification'] for r in result] == [
        'UNEXPLAINED', 'UNEXPLAINED', 'UNEXPLAINED']
    assert result[0]['temporal_classification'] == 'OVERLAPS_INJECTED_RECOVERY'
    assert all(r['causal_attribution_proven'] is False for r in result)


def test_legacy_missing_fault_times_does_not_explain_failure():
    rows = [dict(request_id='old', status=503, seconds=.1, monotonic_start=10)]
    assert classify_http_failures(rows, [dict(killed_pid=8)])[0]['classification'] == 'UNEXPLAINED'


def test_thread_creation_is_not_http_readiness():
    with pytest.raises(RuntimeError, match='HTTP_START_NOT_CONFIRMED'):
        wait_http_started(SimpleNamespace(started=False), SimpleNamespace(is_alive=lambda: True), budget=0)
    wait_http_started(SimpleNamespace(started=True), SimpleNamespace(is_alive=lambda: True), budget=0)


def test_initial_snapshots_require_both_fresh_without_extending_budget():
    snapshots = SimpleNamespace(read=lambda strategy, kind: {
        'snapshot': {'state': 'FRESH' if kind == 'current' else 'STALE'}})
    with pytest.raises(RuntimeError, match='INITIAL_SNAPSHOTS_NOT_READY'):
        wait_initial_snapshots(snapshots, budget=0)
    snapshots.read = lambda strategy, kind: {'snapshot': {'state': 'FRESH'}}
    assert wait_initial_snapshots(snapshots, budget=0)['states'] == {
        'current': 'FRESH', 'compact': 'FRESH'}


def test_snapshot_warmup_does_not_excuse_other_failures():
    fault = dict(observer_pid=7, killed_pid=8, fault_monotonic_start=10,
                 replacement_ready_monotonic=12, snapshot_ready_monotonic=13)
    base = dict(observer_pid=7, monotonic_start=12.5, seconds=.1, status=503)
    rows = [{**base, 'response_error_code': code} for code in (
        'CURRENT_CARDS_UNAVAILABLE', 'SNAPSHOT_READ_CAPACITY')]
    assert [r['classification'] for r in classify_http_failures(rows, [fault])] == [
        'UNEXPLAINED', 'UNEXPLAINED']


@pytest.mark.parametrize('status,code', [(401, 'UNCLASSIFIED_RESPONSE'),
    (503, 'CURRENT_CARDS_UNAVAILABLE'), (503, 'UNCLASSIFIED_RESPONSE')])
def test_overlap_is_not_an_acceptance_contract(status, code):
    fault = dict(observer_pid=7, killed_pid=8, fault_monotonic_start=10,
                 replacement_ready_monotonic=12, snapshot_ready_monotonic=13)
    row = dict(observer_pid=7, monotonic_start=11, seconds=.1, status=status,
               response_error_code=code, path='/unrelated')
    result = classify_http_failures([row], [fault])[0]
    assert result['classification'] == 'UNEXPLAINED'
    assert result['overlapping_killed_pids'] == [8]
    assert not result['causal_attribution_proven']
