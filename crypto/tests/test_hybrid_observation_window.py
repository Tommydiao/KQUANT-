from types import SimpleNamespace
import pytest
from kquant_crypto.hybrid_observation_window import planned_window, registration_wait, connection_failure_detail


def test_window_frozen_before_bootstrap_and_never_from_quote_span():
    window = planned_window(100, 86400)
    assert window['start_monotonic'] == 102
    assert window['end_monotonic'] == 86502
    assert registration_wait(window, 101) == 1
    for late in (102, 103, 99, float('nan')):
        with pytest.raises(ValueError):
            registration_wait(window, late)
    with pytest.raises(ValueError):
        registration_wait(window | {'end_monotonic': 300}, 101)


@pytest.mark.parametrize('value', [True, 0, -1, float('nan'), float('inf')])
def test_bad_clock_registration_rejected(value):
    with pytest.raises(ValueError):
        planned_window(value, 86400)


def test_close_diagnostic_never_logs_remote_reason_or_url():
    error = SimpleNamespace(rcvd=SimpleNamespace(code=1001, reason='secret text'),
                            sent=SimpleNamespace(code=1011), rcvd_then_sent=False)
    result = connection_failure_detail(error)
    assert result == {'rcvd_close_code': 1001, 'sent_close_code': 1011,
                      'close_order_received_then_sent': False}
    assert connection_failure_detail(Exception())['rcvd_close_code'] is None
