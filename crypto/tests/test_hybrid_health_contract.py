import json
import pytest
from kquant_crypto.hybrid_health_contract import COMPONENTS, summarize_health


def test_missing_is_not_healthy():
    report = summarize_health({}, now=100, max_age=10)
    assert report['status'] == 'ATTENTION'
    assert all(v['state'] == 'UNKNOWN' for v in report['components'].values())
    assert not report['execution_authorized']


@pytest.mark.parametrize('at,reason', [(89, 'STALE_OBSERVATION'), (101, 'FUTURE_OBSERVATION'),
                                     (True, 'INVALID_TIME'), (-1, 'INVALID_TIME')])
def test_invalid_clock_cannot_report_ok(at, reason):
    result = summarize_health({'data': {'state': 'OK', 'observed_at': at}}, now=100, max_age=10)
    assert result['components']['data']['reason'] == reason
    assert result['components']['data']['state'] == 'UNKNOWN'


def test_secrets_and_raw_errors_not_copied():
    result = summarize_health({'orders': {'state': 'FAILED', 'observed_at': 100,
                                         'error': 'SECRET', 'url': 'SECRET'}, 'SECRET': 'SECRET'},
                              now=100, max_age=10)
    assert 'SECRET' not in json.dumps(result)


def test_material_hash_ignores_normal_heartbeat_but_changes_for_failure():
    values = {name: {'state': 'OK', 'observed_at': 100} for name in COMPONENTS}
    first = summarize_health(values, now=100, max_age=10)
    for item in values.values():
        item['observed_at'] = 101
    second = summarize_health(values, now=101, max_age=10)
    assert first['material_state_hash'] == second['material_state_hash']
    assert second['status'] == 'REPORTED_OK'
    values['protection']['state'] = 'FAILED'
    third = summarize_health(values, now=101, max_age=10)
    assert third['material_state_hash'] != second['material_state_hash']
    assert not third['external_notification_sent']
